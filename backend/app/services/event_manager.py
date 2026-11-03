"""Event engine.

State machine:  IDLE --trigger--> RECORDING --(no trigger for POST s or MAX reached)--> FINALISING --> IDLE

* On the first trigger the previous PRE seconds are pulled from the circular
  buffer and written, followed by every live frame, into ONE recorder.
* Every further trigger (same or other object/zone) extends the event, so the
  post-event window always counts from the *last* relevant observation.
* Higher-priority triggers upgrade the event type
  (motion < object_detection < zone_violation < loitering).
* Finalising (H.264 transcode, AI summary, notifications) runs on a worker
  pool so the capture loop is never blocked.
"""
from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np

from app.core.config import settings as cfg
from app.database.database import session_scope
from app.database.models import Event, EventObject
from app.services.circular_buffer import CircularFrameBuffer
from app.services.event_bus import event_bus
from app.services.video_recorder import EventRecorder
from app.utils.image_utils import save_jpeg
from app.utils.logger import get_logger

log = get_logger("events")

PRIORITY = {"motion": 0, "object_detection": 1, "zone_violation": 2, "loitering": 3}


@dataclass
class TriggerSignal:
    event_type: str
    object_class: str | None = None
    confidence: float = 0.0
    track_id: int | None = None
    zone_id: int | None = None
    zone_name: str | None = None
    bbox: list[float] | None = None
    detail: dict = field(default_factory=dict)


@dataclass
class TrackedObject:
    track_id: int
    object_class: str
    max_confidence: float
    first_seen: datetime
    last_seen: datetime
    zones: set[str] = field(default_factory=set)
    trajectory: list[list[float]] = field(default_factory=list)


@dataclass
class ActiveEvent:
    event_id: int
    event_type: str
    start_ts: float
    start_wall: datetime
    last_trigger_ts: float
    last_trigger_wall: datetime
    object_class: str | None
    confidence: float
    zone_id: int | None
    zone_name: str | None
    recorder: EventRecorder
    raw_path: Path
    final_path: Path
    snapshot_path: Path
    pre_seconds: float
    start_frame: int | None = None
    track_id: int | None = None  # tracking ID of the object that triggered / defines the event
    objects: dict[int, TrackedObject] = field(default_factory=dict)
    triggers: list[dict] = field(default_factory=list)
    loiter_dwell: float = 0.0


def rel_storage(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(cfg.storage_dir)).replace("\\", "/")
    except ValueError:
        return str(path)


class EventManager:
    def __init__(self, buffer: CircularFrameBuffer, settings_getter: Callable[[], dict],
                 post_processor: Callable[[int], None] | None = None,
                 fps: float | None = None, frame_size: tuple[int, int] | None = None,
                 executor: ThreadPoolExecutor | None = None, analysis_id: int | None = None,
                 source: str = "live") -> None:
        self.buffer = buffer
        self.analysis_id = analysis_id  # set when processing an uploaded video
        self.source = source  # "live" | "video"
        self.last_frame: tuple[float, datetime] | None = None
        self.get_settings = settings_getter
        self.post_processor = post_processor
        self.fps = float(fps or cfg.CAMERA_FPS)
        self.frame_size = frame_size or (cfg.CAMERA_WIDTH, cfg.CAMERA_HEIGHT)
        self.executor = executor or ThreadPoolExecutor(max_workers=2, thread_name_prefix="event-post")
        self.active: ActiveEvent | None = None
        self._last_end_ts: float | None = None
        self._lock = threading.RLock()
        self._pending: list = []

    # ------------------------------------------------------------- public --
    @property
    def active_event_id(self) -> int | None:
        return self.active.event_id if self.active else None

    def trigger(self, signal: TriggerSignal, ts: float, wall: datetime, snapshot: np.ndarray | None = None,
                frame_index: int | None = None) -> int | None:
        """Start or extend an event. Returns the event id, or None if suppressed."""
        with self._lock:
            s = self.get_settings()
            if self.active is None:
                if self._last_end_ts is not None and ts - self._last_end_ts < s["event_cooldown_seconds"]:
                    return None
                self._start(signal, ts, wall, snapshot, s, frame_index)
            else:
                self._extend(signal, ts, wall, snapshot)
            return self.active.event_id if self.active else None

    def observe_track(self, track_id: int, cls: str, confidence: float, bbox: list[float],
                      zones: list[str], ts: float, wall: datetime) -> None:
        """Record trajectory/metadata of an object participating in the active event."""
        with self._lock:
            ev = self.active
            if ev is None:
                return
            obj = ev.objects.get(track_id)
            if obj is None:
                obj = TrackedObject(track_id, cls, confidence, wall, wall)
                ev.objects[track_id] = obj
            obj.max_confidence = max(obj.max_confidence, confidence)
            obj.last_seen = wall
            obj.zones.update(zones)
            w, h = self.frame_size
            cx, cy = (bbox[0] + bbox[2]) / 2 / w, (bbox[1] + bbox[3]) / 2 / h
            if len(obj.trajectory) < 600:
                obj.trajectory.append([round(ts - ev.start_ts, 2), round(cx, 4), round(cy, 4)])

    def on_frame(self, ts: float, image: np.ndarray, wall: datetime) -> None:
        """Called for every frame (after triggers for that frame)."""
        with self._lock:
            self.last_frame = (ts, wall)
            ev = self.active
            if ev is None:
                return
            ev.recorder.write(ts, image)
            s = self.get_settings()
            idle = ts - ev.last_trigger_ts
            total = ts - ev.start_ts
            if idle >= s["post_event_seconds"] or total >= s["max_event_seconds"]:
                reason = "post-event window elapsed" if idle >= s["post_event_seconds"] else "max duration reached"
                self._finish(ts, wall, reason)

    def force_finish(self, reason: str = "camera stopped") -> None:
        with self._lock:
            if self.active is not None:
                ts, wall = self.last_frame or (self.active.last_trigger_ts, datetime.now())
                self._finish(ts, wall, reason)

    def wait_idle(self, timeout: float = 120.0) -> None:
        """Block until all finalisation jobs are done (used by tests/shutdown)."""
        for fut in list(self._pending):
            fut.result(timeout=timeout)

    # ------------------------------------------------------------ private --
    def _start(self, signal: TriggerSignal, ts: float, wall: datetime, snapshot: np.ndarray | None, s: dict,
               frame_index: int | None = None) -> None:
        day = wall.strftime("%Y-%m-%d")
        with session_scope() as db:
            ev = Event(
                event_type=signal.event_type, status="recording", timestamp=wall, start_time=wall,
                object_class=signal.object_class, confidence=signal.confidence,
                zone_id=signal.zone_id, zone_name=signal.zone_name, metadata_json={},
                analysis_id=self.analysis_id, source=self.source,
                video_offset=round(ts, 3) if self.source == "video" else None,
            )
            db.add(ev)
            db.flush()
            event_id = ev.id
        events_dir = cfg.subdir("events") / day
        snap_path = cfg.subdir("snapshots") / day / f"event_{event_id}.jpg"
        raw_path = events_dir / f"event_{event_id}.raw.mp4"
        final_path = events_dir / f"event_{event_id}.mp4"

        recorder = EventRecorder(raw_path, self.fps, self.frame_size)
        pre = self.buffer.get_frames(before_ts=ts)
        pre = [(t, f) for t, f in pre if ts - t <= s["pre_event_seconds"]]
        recorder.start(pre)
        pre_seconds = (ts - pre[0][0]) if pre else 0.0

        if snapshot is not None:
            save_jpeg(snapshot, snap_path)
        with session_scope() as db:
            row = db.get(Event, event_id)
            row.snapshot_path = rel_storage(snap_path) if snapshot is not None else None

        self.active = ActiveEvent(
            event_id=event_id, event_type=signal.event_type, start_ts=ts, start_wall=wall,
            last_trigger_ts=ts, last_trigger_wall=wall, object_class=signal.object_class,
            confidence=signal.confidence, zone_id=signal.zone_id, zone_name=signal.zone_name,
            recorder=recorder, raw_path=raw_path, final_path=final_path, snapshot_path=snap_path,
            pre_seconds=pre_seconds, start_frame=frame_index, track_id=signal.track_id,
        )
        self._record_trigger(signal, ts)
        log.info("Event %d created: %s (%s%s)", event_id, signal.event_type, signal.object_class or "-",
                 f" in {signal.zone_name}" if signal.zone_name else "")
        event_bus.publish("event_started", {
            "event_id": event_id, "analysis_id": self.analysis_id, "event_type": signal.event_type, "object_class": signal.object_class,
            "confidence": signal.confidence, "zone_name": signal.zone_name, "start_time": wall.astimezone().isoformat(),
        })

    def _extend(self, signal: TriggerSignal, ts: float, wall: datetime, snapshot: np.ndarray | None) -> None:
        ev = self.active
        ev.last_trigger_ts = max(ev.last_trigger_ts, ts)
        ev.last_trigger_wall = wall
        if signal.event_type == "loitering":
            ev.loiter_dwell = max(ev.loiter_dwell, signal.detail.get("dwell", 0.0))
        upgraded = PRIORITY.get(signal.event_type, 0) > PRIORITY.get(ev.event_type, 0)
        if upgraded:
            log.info("Event %d upgraded: %s -> %s", ev.event_id, ev.event_type, signal.event_type)
            ev.event_type = signal.event_type
            ev.object_class = signal.object_class or ev.object_class
            ev.track_id = signal.track_id or ev.track_id
            ev.zone_id, ev.zone_name = signal.zone_id or ev.zone_id, signal.zone_name or ev.zone_name
            if snapshot is not None:
                save_jpeg(snapshot, ev.snapshot_path)
            self._record_trigger(signal, ts)
            try:  # keep the DB row current so dashboards/searches see the upgraded type immediately
                with session_scope() as db:
                    row = db.get(Event, ev.event_id)
                    row.event_type, row.zone_id, row.zone_name = ev.event_type, ev.zone_id, ev.zone_name
            except Exception as exc:
                log.warning("Could not persist upgrade of event %d: %s", ev.event_id, exc)
            event_bus.publish("event_updated", {"event_id": ev.event_id, "analysis_id": self.analysis_id,
                                                "event_type": ev.event_type, "object_class": ev.object_class,
                                                "zone_name": ev.zone_name})
        elif ev.object_class is None and signal.object_class:
            ev.object_class = signal.object_class
        if signal.object_class == ev.object_class and signal.confidence > ev.confidence:
            if snapshot is not None and not upgraded and signal.confidence >= ev.confidence + 0.03:
                save_jpeg(snapshot, ev.snapshot_path)  # keep the clearest view of the primary object
            ev.confidence = signal.confidence
        if not upgraded and len(ev.triggers) < 200:
            self._record_trigger(signal, ts)

    def _record_trigger(self, signal: TriggerSignal, ts: float) -> None:
        ev = self.active
        entry = {"type": signal.event_type, "t": round(ts - ev.start_ts, 2), "object": signal.object_class,
                 "track_id": signal.track_id, "zone": signal.zone_name}
        # one log entry per distinct (type, track, zone) – repeated keep-alive triggers are not logged
        key = (signal.event_type, signal.track_id, signal.zone_name)
        if any((e["type"], e["track_id"], e["zone"]) == key for e in ev.triggers):
            return
        if signal.detail:
            entry.update(signal.detail)
        ev.triggers.append(entry)
        if signal.event_type == "loitering":
            ev.loiter_dwell = max(ev.loiter_dwell, signal.detail.get("dwell", 0.0))

    def _finish(self, ts: float, wall: datetime, reason: str) -> None:
        ev = self.active
        self.active = None
        self._last_end_ts = ts
        observed = max(0.0, ev.last_trigger_ts - ev.start_ts)
        log.info("Event %d ending (%s), observed %.1fs", ev.event_id, reason, observed)
        fut = self.executor.submit(self._finalise, ev, wall, observed, reason, ts)
        self._pending = [f for f in self._pending if not f.done()] + [fut]

    def _finalise(self, ev: ActiveEvent, end_wall: datetime, observed: float, reason: str,
                  end_ts: float | None = None) -> None:
        try:
            with session_scope() as db:
                db.get(Event, ev.event_id).status = "processing"
            final = ev.recorder.close(ev.final_path)
            size = final.stat().st_size if final.exists() else 0
            classes: dict[str, int] = {}
            for o in ev.objects.values():
                classes[o.object_class] = classes.get(o.object_class, 0) + 1
            duration = max(observed, ev.loiter_dwell)
            metadata = {
                "pre_event_seconds": round(ev.pre_seconds, 2),
                "post_event_seconds": self.get_settings()["post_event_seconds"],
                "video_duration": round(ev.recorder.duration, 2),
                "video_frames": ev.recorder.frames_written,
                "pre_event_frames": ev.recorder.pre_frames,
                "fps": self.fps,
                "end_reason": reason,
                "object_counts": classes,
                "triggers": ev.triggers,
                "loitering_dwell": round(ev.loiter_dwell, 1) if ev.loiter_dwell else None,
                "frame_size": list(self.frame_size),
                "source": self.source,
                "track_id": ev.track_id,
            }
            if self.source == "video":
                # positions in the uploaded video (seconds) – lets the UI seek the original file
                clip_start = ev.recorder.first_ts if ev.recorder.first_ts is not None else ev.start_ts
                metadata.update({
                    "video_event_start": round(ev.start_ts, 2),
                    "video_event_end": round(ev.last_trigger_ts, 2),
                    "video_clip_start": round(clip_start, 2),
                    "video_clip_end": round(end_ts if end_ts is not None else ev.last_trigger_ts, 2),
                    "start_frame": ev.start_frame,
                })
            with session_scope() as db:
                row = db.get(Event, ev.event_id)
                row.event_type = ev.event_type
                row.end_time = end_wall
                row.duration = round(duration, 2)
                row.object_class = ev.object_class
                row.confidence = round(ev.confidence, 3)
                row.zone_id, row.zone_name = ev.zone_id, ev.zone_name
                row.video_path = rel_storage(final) if final.exists() else None
                row.video_size_bytes = size
                row.metadata_json = metadata
                for o in ev.objects.values():
                    db.add(EventObject(
                        event_id=ev.event_id, track_id=o.track_id, object_class=o.object_class,
                        max_confidence=round(o.max_confidence, 3), first_seen=o.first_seen,
                        last_seen=o.last_seen, zones=sorted(o.zones), trajectory=o.trajectory,
                    ))
                if row.confidence == 0 and ev.objects:
                    row.confidence = round(max(o.max_confidence for o in ev.objects.values()), 3)
        except Exception as exc:
            log.exception("Finalising event %d failed: %s", ev.event_id, exc)
            try:
                with session_scope() as db:
                    db.get(Event, ev.event_id).status = "failed"
            except Exception:
                pass
            return

        if self.post_processor:
            try:
                self.post_processor(ev.event_id)
            except Exception as exc:  # summary / notification problems never lose the event
                log.exception("Post-processing of event %d failed: %s", ev.event_id, exc)
        with session_scope() as db:
            row = db.get(Event, ev.event_id)
            row.status = "completed"
            payload = {"event_id": row.id, "analysis_id": row.analysis_id, "event_type": row.event_type, "object_class": row.object_class,
                       "zone_name": row.zone_name, "duration": row.duration, "summary": row.summary,
                       "confidence": row.confidence}
        event_bus.publish("event_completed", payload)
