"""Daily timelapse: condenses all event clips of a day into one video.

Clips are taken in chronological order, every Nth frame is kept (speed-up),
and each frame is stamped with the event id, type and wall-clock time so the
timelapse remains a usable review tool. A title card separates events.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import cv2
import numpy as np

from app.core.config import settings as cfg
from app.database.database import session_scope
from app.database.models import Event, Timelapse
from app.services.event_manager import rel_storage
from app.utils.logger import get_logger
from app.utils.video_utils import finalize_mp4, open_writer

log = get_logger("timelapse")


def _title_card(size: tuple[int, int], lines: list[str]) -> np.ndarray:
    w, h = size
    img = np.full((h, w, 3), (30, 23, 15), np.uint8)
    for i, line in enumerate(lines):
        scale = 0.9 if i == 0 else 0.55
        (tw, th), _ = cv2.getTextSize(line, cv2.FONT_HERSHEY_SIMPLEX, scale, 2 if i == 0 else 1)
        y = h // 2 - 20 + i * 34
        cv2.putText(img, line, ((w - tw) // 2, y), cv2.FONT_HERSHEY_SIMPLEX, scale,
                    (212, 182, 6) if i == 0 else (220, 220, 220), 2 if i == 0 else 1, cv2.LINE_AA)
    return img


def create_job(day: str) -> int:
    with session_scope() as db:
        tl = Timelapse(date=day, status="processing")
        db.add(tl)
        db.flush()
        return tl.id


def generate(timelapse_id: int, day: str, speed: int = 4, fps: float | None = None) -> None:
    fps = fps or float(cfg.CAMERA_FPS)
    size = (cfg.CAMERA_WIDTH, cfg.CAMERA_HEIGHT)
    try:
        start = datetime.strptime(day, "%Y-%m-%d")
        with session_scope() as db:
            events = (db.query(Event)
                      .filter(Event.start_time >= start, Event.start_time < start + timedelta(days=1),
                              Event.video_path.isnot(None))
                      .order_by(Event.start_time.asc()).all())
            clips = [(e.id, e.event_type, e.object_class, e.zone_name, e.start_time, e.video_path) for e in events]
        if not clips:
            raise ValueError(f"No recorded events on {day}")

        out_dir = cfg.subdir("timelapse") / day
        raw = out_dir / f"timelapse_{timelapse_id}.raw.mp4"
        final = out_dir / f"timelapse_{day}_{timelapse_id}.mp4"
        writer = open_writer(raw, fps, size)
        written, used = 0, 0
        try:
            for frame in [_title_card(size, [f"PreVuCam Daily Timelapse", day, f"{len(clips)} events · {speed}x"])] * int(fps * 1.5):
                writer.write(frame)
                written += 1
            for event_id, etype, obj, zone, started, rel in clips:
                path = cfg.storage_dir / rel
                cap = cv2.VideoCapture(str(path))
                if not cap.isOpened():
                    log.warning("Skipping unreadable clip %s", rel)
                    continue
                used += 1
                src_fps = cap.get(cv2.CAP_PROP_FPS) or fps
                label = f"#{event_id} {etype.replace('_', ' ')} {obj or ''} {('@ ' + zone) if zone else ''}".strip()
                for _ in range(int(fps * 0.5)):
                    writer.write(_title_card(size, [started.strftime("%H:%M:%S"), label]))
                    written += 1
                idx = 0
                while True:
                    ok, frame = cap.read()
                    if not ok:
                        break
                    if idx % speed == 0:
                        if frame.shape[1] != size[0] or frame.shape[0] != size[1]:
                            frame = cv2.resize(frame, size)
                        stamp = started + timedelta(seconds=idx / src_fps)
                        cv2.rectangle(frame, (0, 0), (size[0], 24), (15, 15, 15), -1)
                        cv2.putText(frame, f"{stamp:%H:%M:%S}  {label}  [{speed}x]", (8, 17),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (230, 230, 230), 1, cv2.LINE_AA)
                        writer.write(frame)
                        written += 1
                    idx += 1
                cap.release()
        finally:
            writer.release()
        if used == 0:
            raw.unlink(missing_ok=True)
            raise ValueError("None of the event clips could be read")
        final = finalize_mp4(raw, final)
        with session_scope() as db:
            tl = db.get(Timelapse, timelapse_id)
            tl.status, tl.file_path = "completed", rel_storage(final)
            tl.event_count, tl.duration = used, round(written / fps, 2)
            tl.size_bytes = final.stat().st_size
        log.info("Timelapse %d for %s completed: %d events, %.1fs", timelapse_id, day, used, written / fps)
    except Exception as exc:
        log.error("Timelapse %d for %s failed: %s", timelapse_id, day, exc)
        with session_scope() as db:
            tl = db.get(Timelapse, timelapse_id)
            if tl:
                tl.status, tl.error = "failed", str(exc)[:500]
