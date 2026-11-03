"""Recorded video analysis: upload → metadata → background run of the shared DetectionEngine.

The uploaded file is read incrementally with OpenCV (never loaded into RAM). Each frame is
timestamped with its media time (frame_index / fps) and handed to the same DetectionEngine
the live camera uses, so motion gating, YOLO, relevant-object filtering, tracking, zones,
loitering, the 7 s pre-event ring buffer, event recording, summaries and alerts all behave
exactly as they do live. Events land in the normal `events` table, tagged with analysis_id.
"""
from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from typing import BinaryIO

import cv2

from app.core.config import settings as cfg
from app.database.database import session_scope
from app.database.models import Event, VideoAnalysis
from app.services import storage_service
from app.services.camera_service import Frame
from app.services.detection_engine import DetectionEngine, shared_detector
from app.services.event_bus import event_bus
from app.services.event_manager import rel_storage
from app.services.event_processor import process_event
from app.services.object_detector import VEHICLE_CLASSES
from app.utils.logger import get_logger
from app.utils.video_utils import VideoError, is_browser_playable, probe_video, transcode_to_h264

log = get_logger("video_analysis")

ALLOWED_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".webm"}
CHUNK = 1024 * 1024
ACTIVE = ("queued", "processing")


class AnalysisCancelled(Exception):
    pass


def _uploads() -> Path:
    return cfg.subdir("uploads")


# ------------------------------------------------------------------ upload --
def save_upload(stream: BinaryIO, original_name: str, recorded_at: datetime | None = None) -> VideoAnalysis:
    """Validate, store and probe an uploaded video. Raises VideoError with a user-facing message."""
    ext = Path(original_name or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise VideoError(f"Unsupported format '{ext or 'unknown'}'. Use one of: "
                         + ", ".join(sorted(ALLOWED_EXTENSIONS)))
    if not storage_service.has_free_space():
        raise VideoError("Not enough free disk space to store this video.")
    max_bytes = cfg.MAX_UPLOAD_MB * 1024 * 1024
    stem = "".join(c for c in Path(original_name).stem if c.isalnum() or c in "-_")[:60] or "video"
    filename = f"{stem}_{datetime.now():%Y%m%d%H%M%S}_{uuid.uuid4().hex[:6]}{ext}"
    dest = _uploads() / filename
    written = 0
    try:
        with dest.open("wb") as fh:
            while chunk := stream.read(CHUNK):
                written += len(chunk)
                if written > max_bytes:
                    raise VideoError(f"File is larger than the {cfg.MAX_UPLOAD_MB} MB upload limit.")
                fh.write(chunk)
        if written == 0:
            raise VideoError("The uploaded file is empty.")
        info = probe_video(dest)
        if info.frames < 2:
            raise VideoError("Unable to process this video because it contains no playable frames.")
    except VideoError:
        dest.unlink(missing_ok=True)
        raise
    except OSError as exc:
        dest.unlink(missing_ok=True)
        raise VideoError(f"Could not save the video (storage error: {exc.strerror or exc}).") from exc

    with session_scope() as db:
        va = VideoAnalysis(
            original_name=Path(original_name).name[:255], filename=filename, file_path=rel_storage(dest),
            size_bytes=written, duration=round(info.duration, 3), width=info.width, height=info.height,
            fps=round(info.fps, 3), total_frames=info.frames, codec=info.codec or None,
            recorded_at=recorded_at, status="uploaded",
        )
        if is_browser_playable(dest, info.codec):
            va.preview_path = va.file_path
        db.add(va)
        db.flush()
        analysis_id = va.id
    log.info("Video uploaded: %s -> %s (%dx%d, %.1f fps, %d frames, %.1fs)", original_name, filename,
             info.width, info.height, info.fps, info.frames, info.duration)
    if not is_browser_playable(dest, info.codec):
        threading.Thread(target=_make_preview, args=(analysis_id,), daemon=True, name="preview").start()
    return get(analysis_id)


def _make_preview(analysis_id: int) -> None:
    """Browser-playable H.264 copy for review in the UI (the original is kept untouched)."""
    va = get(analysis_id)
    if va is None:
        return
    src = cfg.storage_dir / va.file_path
    dst = _uploads() / "previews" / f"{Path(va.filename).stem}.mp4"
    dst.parent.mkdir(parents=True, exist_ok=True)
    if transcode_to_h264(src, dst, max_width=cfg.ANALYSIS_MAX_WIDTH):
        with session_scope() as db:
            row = db.get(VideoAnalysis, analysis_id)
            if row:
                row.preview_path = rel_storage(dst)
        log.info("Preview ready for analysis %d", analysis_id)
    else:
        log.warning("No browser preview for analysis %d (FFmpeg unavailable or failed)", analysis_id)


def frame_at(analysis_id: int, seconds: float | None = None) -> bytes:
    """JPEG of the uploaded video at `seconds` (default: 1/3 in) – background for drawing zones."""
    va = get(analysis_id)
    if va is None:
        raise LookupError(f"Analysis {analysis_id} not found")
    cap = cv2.VideoCapture(str(cfg.storage_dir / va.file_path))
    try:
        t = va.duration / 3 if seconds is None else max(0.0, min(seconds, max(0.0, va.duration - 0.1)))
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, img = cap.read()
        if not ok:
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, img = cap.read()
        if not ok:
            raise VideoError("Could not read a frame from this video.")
        ok, buf = cv2.imencode(".jpg", cv2.resize(img, _processing_size(img.shape[1], img.shape[0])),
                               [cv2.IMWRITE_JPEG_QUALITY, 85])
        return buf.tobytes()
    finally:
        cap.release()


def get(analysis_id: int) -> VideoAnalysis | None:
    with session_scope() as db:
        return db.get(VideoAnalysis, analysis_id)


# ------------------------------------------------------------- run control --
class AnalysisManager:
    """Single-worker queue: analyses run one at a time so a laptop/Pi is never oversubscribed."""

    def __init__(self) -> None:
        self._pool: ThreadPoolExecutor | None = None
        self._cancel: dict[int, threading.Event] = {}
        self._lock = threading.Lock()

    @property
    def _executor(self) -> ThreadPoolExecutor:
        # created on demand so the app can be stopped and started again in one process (tests, --reload)
        if self._pool is None:
            self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="video-analysis")
        return self._pool

    def start(self, analysis_id: int, force: bool = False) -> VideoAnalysis:
        with self._lock, session_scope() as db:
            va = db.get(VideoAnalysis, analysis_id)
            if va is None:
                raise LookupError(f"Analysis {analysis_id} not found")
            if va.status in ACTIVE:
                raise ValueError("This video is already being analysed.")
            if va.status == "completed" and not force:
                raise ValueError("This video has already been analysed. Use re-analyse to run it again.")
            if not (cfg.storage_dir / va.file_path).exists():
                raise ValueError("The uploaded video file is missing from storage – upload it again.")
            # a re-run replaces the results of the previous run instead of duplicating them
            previous = db.query(Event).filter(Event.analysis_id == analysis_id).all()
            for ev in previous:
                storage_service.delete_event(db, ev)
            for k in ("progress", "current_time", "processing_seconds"):
                setattr(va, k, 0.0)
            for k in ("frames_processed", "events_detected", "objects_detected", "zone_violations",
                      "loitering_events", "detections_run"):
                setattr(va, k, 0)
            va.object_counts, va.error, va.warning, va.completed_at = {}, None, None, None
            va.status, va.stage = "queued", "waiting for the analysis worker"
            self._cancel[analysis_id] = threading.Event()
        self._executor.submit(self._run_safely, analysis_id)
        log.info("Analysis %d queued%s", analysis_id, f" (replacing {len(previous)} previous events)" if previous else "")
        return get(analysis_id)

    def cancel(self, analysis_id: int) -> VideoAnalysis:
        with self._lock, session_scope() as db:
            va = db.get(VideoAnalysis, analysis_id)
            if va is None:
                raise LookupError(f"Analysis {analysis_id} not found")
            if va.status not in ACTIVE:
                raise ValueError(f"Analysis is not running (status: {va.status}).")
            flag = self._cancel.get(analysis_id)
            if flag:
                flag.set()
            if va.status == "queued":
                va.status, va.stage = "cancelled", None
            else:
                va.stage = "cancelling"
        log.info("Cancellation requested for analysis %d", analysis_id)
        return get(analysis_id)

    def is_running(self, analysis_id: int) -> bool:
        flag = self._cancel.get(analysis_id)
        return flag is not None and not flag.is_set()

    def shutdown(self) -> None:
        """Stop any running analysis cleanly (it is marked cancelled) and wait for the worker."""
        for flag in list(self._cancel.values()):
            flag.set()
        if self._pool is not None:
            self._pool.shutdown(wait=True, cancel_futures=True)
            self._pool = None

    # ---------------------------------------------------------------- run --
    def _run_safely(self, analysis_id: int) -> None:
        flag = self._cancel.get(analysis_id) or threading.Event()
        try:
            if flag.is_set():  # cancelled while queued
                return
            run_analysis(analysis_id, flag)
        except Exception as exc:  # last-resort guard – never leaves a job "processing"
            log.exception("Analysis %d crashed: %s", analysis_id, exc)
            _update(analysis_id, status="failed", stage=None, error=f"Unexpected error: {exc}")
        finally:
            self._cancel.pop(analysis_id, None)


def _update(analysis_id: int, **fields) -> None:
    try:
        with session_scope() as db:
            va = db.get(VideoAnalysis, analysis_id)
            if va is not None:
                for k, v in fields.items():
                    setattr(va, k, v)
    except Exception as exc:
        log.error("Could not update analysis %d: %s", analysis_id, exc)


def _event_counts(analysis_id: int) -> dict:
    with session_scope() as db:
        rows = db.query(Event.event_type).filter(Event.analysis_id == analysis_id).all()
    types = [r[0] for r in rows]
    return {"events_detected": len(types), "zone_violations": types.count("zone_violation"),
            "loitering_events": types.count("loitering")}


def _processing_size(width: int, height: int) -> tuple[int, int]:
    if width <= cfg.ANALYSIS_MAX_WIDTH:
        return width - width % 2, height - height % 2
    scale = cfg.ANALYSIS_MAX_WIDTH / width
    w, h = int(width * scale), int(height * scale)
    return w - w % 2, h - h % 2


def run_analysis(analysis_id: int, cancel: threading.Event, post_processor=process_event) -> None:
    va = get(analysis_id)
    src = cfg.storage_dir / va.file_path
    detector = shared_detector()
    if not detector.available:
        _update(analysis_id, status="failed", stage=None,
                error=f"Object detection is unavailable – {detector.error or 'YOLO model could not be loaded'}.")
        return
    if not storage_service.has_free_space():
        _update(analysis_id, status="failed", stage=None, error="Storage is full – free some disk space and retry.")
        return

    started = datetime.now()
    base_wall = va.recorded_at or started
    fps = va.fps or 15.0
    size = _processing_size(va.width, va.height)
    total = max(1, va.total_frames)
    _update(analysis_id, status="processing", stage="analysing frames", started_at=started)
    log.info("Analysis %d started: %s at %dx%d, %.2f fps, %d frames", analysis_id, va.original_name, *size, fps, total)
    event_bus.publish("analysis_status", {"analysis_id": analysis_id, "status": "processing"})

    engine = DetectionEngine(detector=detector, post_processor=post_processor, fps=fps, frame_size=size,
                             source="video", analysis_id=analysis_id, live_view=False, follow_settings=False)
    engine.hud_text = lambda ts, wall: f"{va.original_name[:40]}  {int(ts // 60):02d}:{ts % 60:05.2f}  {wall:%H:%M:%S}"
    cap = cv2.VideoCapture(str(src))
    idx, read_failures, t0, last_report = 0, 0, time.monotonic(), 0.0
    outcome, error, warning = "completed", None, None
    try:
        if not cap.isOpened():
            raise VideoError("Unable to process this video because the file is corrupted or unreadable.")
        while True:
            if cancel.is_set():
                raise AnalysisCancelled()
            ok, img = cap.read()
            if not ok or img is None:
                # a few undecodable frames mid-file are skipped; a run of them means end of stream
                if idx < total - 1 and read_failures < 25:
                    read_failures += 1
                    continue
                break
            if img.shape[1] != size[0] or img.shape[0] != size[1]:
                img = cv2.resize(img, size, interpolation=cv2.INTER_AREA)
            ts = idx / fps
            engine.process(Frame(image=img, ts=ts, wall=base_wall + timedelta(seconds=ts), index=idx))
            idx += 1
            now = time.monotonic()
            if now - last_report >= 0.5:
                last_report = now
                _report(analysis_id, engine, idx, total, ts, now - t0)
        if idx == 0:
            raise VideoError("Unable to process this video because the file is corrupted or contains no frames.")
        if idx < total * 0.97 and total - idx > fps:
            warning = (f"The video ended early: decoded {idx} of {total} frames "
                       f"({idx / fps:.1f}s of {total / fps:.1f}s). The file may be truncated or partly corrupted.")
            log.warning("Analysis %d: %s", analysis_id, warning)
        engine.flush("end of video")
    except AnalysisCancelled:
        outcome = "cancelled"
        engine.flush("analysis cancelled")
        log.info("Analysis %d cancelled at frame %d/%d", analysis_id, idx, total)
    except VideoError as exc:
        outcome, error = "failed", str(exc)
        engine.flush("analysis failed")
    except OSError as exc:
        outcome, error = "failed", f"Storage error while writing event files: {exc.strerror or exc}"
        engine.flush("analysis failed")
    except Exception as exc:
        log.exception("Analysis %d failed: %s", analysis_id, exc)
        outcome, error = "failed", f"Processing error: {exc}"
        engine.flush("analysis failed")
    finally:
        cap.release()  # always release the decoder

    # wait for clip transcoding, summaries and notifications of every event of this video
    _update(analysis_id, stage="finalising events (video encoding, AI summaries, alerts)",
            frames_processed=idx, current_time=round(idx / fps, 2))
    try:
        engine.events.wait_idle(timeout=900)
    except Exception as exc:
        log.error("Analysis %d: finalising events failed: %s", analysis_id, exc)
        warning = (warning + " " if warning else "") + f"Some events could not be finalised: {exc}"
    finally:
        engine.events.executor.shutdown(wait=True)
        engine.close()

    counts = _event_counts(analysis_id)
    progress = 100.0 if outcome == "completed" else round(100.0 * idx / total, 1)
    _update(analysis_id, status=outcome, stage=None, progress=progress, frames_processed=idx,
            current_time=round(idx / fps, 2), objects_detected=len(engine.confirmed_tracks),
            object_counts=engine.object_counts(), detections_run=engine.detections_run,
            processing_seconds=round(time.monotonic() - t0, 1), error=error, warning=warning,
            completed_at=datetime.now(), **counts)
    log.info("Analysis %d %s: %d frames, %d YOLO passes, %d events, objects %s (%.1fs)", analysis_id, outcome,
             idx, engine.detections_run, counts["events_detected"], engine.object_counts(), time.monotonic() - t0)
    event_bus.publish("analysis_status", {"analysis_id": analysis_id, "status": outcome, **counts})


def _report(analysis_id: int, engine: DetectionEngine, idx: int, total: int, ts: float, elapsed: float) -> None:
    counts = _event_counts(analysis_id)
    progress = round(min(99.9, 100.0 * idx / total), 1)
    _update(analysis_id, progress=progress, frames_processed=idx, current_time=round(ts, 2),
            objects_detected=len(engine.confirmed_tracks), object_counts=engine.object_counts(),
            detections_run=engine.detections_run, processing_seconds=round(elapsed, 1), **counts)
    event_bus.publish("analysis_progress", {"analysis_id": analysis_id, "progress": progress,
                                            "frames_processed": idx, **counts})


def summary_counts(va: VideoAnalysis) -> dict:
    counts = va.object_counts or {}
    return {"persons_detected": counts.get("person", 0),
            "vehicles_detected": sum(v for k, v in counts.items() if k in VEHICLE_CLASSES)}


def recover_interrupted() -> None:
    """After a restart, nothing can still be running: mark orphaned jobs and half-written events."""
    with session_scope() as db:
        for va in db.query(VideoAnalysis).filter(VideoAnalysis.status.in_(ACTIVE)).all():
            va.status, va.stage = "failed", None
            va.error = "Interrupted by a server restart – start the analysis again."
            log.warning("Analysis %d was interrupted by a restart", va.id)
        for ev in db.query(Event).filter(Event.status.in_(["recording", "processing"])).all():
            ev.status = "failed"
            log.warning("Event %d was interrupted by a restart", ev.id)


def delete_analysis(analysis_id: int, delete_events: bool) -> int:
    with session_scope() as db:
        va = db.get(VideoAnalysis, analysis_id)
        if va is None:
            raise LookupError(f"Analysis {analysis_id} not found")
        if va.status in ACTIVE:
            raise ValueError("Cancel the analysis before deleting it.")
        freed = 0
        for rel in {va.file_path, va.preview_path}:
            p = storage_service.resolve(rel) if rel else None
            if p and p.exists():
                freed += p.stat().st_size
                p.unlink()
        if delete_events:
            for ev in db.query(Event).filter(Event.analysis_id == analysis_id).all():
                freed += storage_service.delete_event(db, ev)
        db.delete(va)
        return freed


manager = AnalysisManager()
