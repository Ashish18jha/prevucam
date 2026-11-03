"""The PreVuCam detection engine – one implementation for live cameras AND uploaded videos.

Per frame:
    motion gate → (every N frames, while motion / live tracks / an active event)
    YOLO → tracker → zones → loitering → relevant-object filter → event triggers
    → event recorder (pre-event ring buffer + live frames + post-event window)

The engine is clock-agnostic: every frame carries a source timestamp `ts` (seconds)
and the wall-clock time it represents. Live mode feeds monotonic time; recorded-video
mode feeds media time (frame_index / fps), so "previous 7 s", the event and "next 7 s"
are measured on the video's own timeline no matter how fast it is processed.
"""
from __future__ import annotations

import threading
import time
from collections import Counter
from collections.abc import Callable
from datetime import datetime

import numpy as np

from app.core.config import settings as cfg
from app.database.database import session_scope
from app.database.models import LoiteringRecord, Zone
from app.services.camera_service import Frame
from app.services.circular_buffer import CircularFrameBuffer
from app.services.event_bus import event_bus
from app.services.event_manager import EventManager, TriggerSignal
from app.services.loitering_detector import LoiteringDetector, Stay
from app.services.motion_detector import MotionDetector
from app.services.object_detector import ObjectDetector
from app.services.settings_service import settings_service
from app.services.tracker import ObjectTracker, Track
from app.services.zone_detector import ZoneDetector
from app.utils.image_utils import draw_hud, draw_tracks, draw_zones
from app.utils.logger import get_logger

log = get_logger("engine")

_shared_detector: ObjectDetector | None = None
_detector_lock = threading.Lock()


def shared_detector() -> ObjectDetector:
    """One YOLO model instance for the whole process (live + every video analysis)."""
    global _shared_detector
    with _detector_lock:
        if _shared_detector is None:
            _shared_detector = ObjectDetector()
        return _shared_detector


def load_zones() -> list[dict]:
    with session_scope() as db:
        return [{"id": z.id, "name": z.name, "points": z.points, "color": z.color,
                 "zone_type": z.zone_type, "active": z.active, "trigger_on_entry": z.trigger_on_entry,
                 "loitering_enabled": z.loitering_enabled, "loitering_seconds": z.loitering_seconds}
                for z in db.query(Zone).all()]


class DetectionEngine:
    def __init__(self, *, detector: ObjectDetector | None = None, post_processor: Callable[[int], None] | None = None,
                 fps: float | None = None, frame_size: tuple[int, int] | None = None, source: str = "live",
                 analysis_id: int | None = None, live_view: bool = True, follow_settings: bool = True) -> None:
        s = settings_service.get()
        self.source = source
        self.analysis_id = analysis_id
        self.live_view = live_view  # keep an annotated copy of every frame (MJPEG); off for offline analysis
        self.fps = float(fps or cfg.CAMERA_FPS)
        self.size = frame_size or (cfg.CAMERA_WIDTH, cfg.CAMERA_HEIGHT)
        self.detector = detector or shared_detector()
        self.motion = MotionDetector(s["motion_sensitivity"], self._scaled_min_area(s), cfg.MOTION_PROCESS_WIDTH)
        self.tracker = ObjectTracker(max_age=self._track_max_age(s))
        self.zones = ZoneDetector()
        self.loitering = LoiteringDetector(s["loitering_seconds"], s["loitering_classes"])
        self.buffer = CircularFrameBuffer(s["pre_event_seconds"], self.fps, cfg.BUFFER_JPEG_QUALITY)
        self.events = EventManager(self.buffer, settings_service.get, post_processor, fps=self.fps,
                                   frame_size=self.size, analysis_id=analysis_id, source=source)
        self._settings = s
        self._frame_counter = 0
        self._last_motion = False
        self._last_motion_log = 0.0
        self._last_publish = 0.0
        self._annotated: np.ndarray | None = None
        self._annotated_lock = threading.Lock()
        self.last_detections: list[dict] = []
        self.live_tracks_info: list[dict] = []  # tracks visible in the latest frame (live overlay)
        self.last_detection_at: datetime | None = None
        # statistics (used by video analysis progress)
        self.detections_run = 0
        self.confirmed_tracks: dict[int, str] = {}
        self._follow = follow_settings
        if follow_settings:
            settings_service.subscribe(self.apply_settings)
        self.reload_zones()

    # ---------------------------------------------------------- settings --
    def _scaled_min_area(self, s: dict) -> int:
        """`motion_min_area` is defined for the reference camera resolution; scale it to this frame size."""
        ref = cfg.CAMERA_WIDTH * cfg.CAMERA_HEIGHT
        return max(10, int(s["motion_min_area"] * (self.size[0] * self.size[1]) / ref))

    def _track_max_age(self, s: dict) -> float:
        return max(2.0, s["detection_interval"] / cfg.CAMERA_FPS * 4)

    def detection_every(self, s: dict) -> int:
        """Run YOLO every N frames. The interval is defined at CAMERA_FPS, so keep the same rate per second."""
        return max(1, round(s["detection_interval"] * self.fps / cfg.CAMERA_FPS))

    def apply_settings(self, s: dict) -> None:
        self._settings = s
        self.motion.configure(s["motion_sensitivity"], self._scaled_min_area(s))
        self.loitering.configure(s["loitering_seconds"], s["loitering_classes"])
        self.detector.confidence = s["yolo_confidence"]
        if abs(self.buffer.seconds - s["pre_event_seconds"]) > 1e-6:
            self.buffer.resize(s["pre_event_seconds"])

    def close(self) -> None:
        if self._follow:
            settings_service.unsubscribe(self.apply_settings)
            self._follow = False

    def reload_zones(self) -> None:
        try:
            self.zones.set_zones(load_zones())
        except Exception as exc:
            log.error("Could not load zones: %s", exc)

    def reset(self) -> None:
        self.motion.reset()
        self.tracker.reset()
        self.buffer.clear()

    def flush(self, reason: str = "camera stopped") -> None:
        """Close any open event and stay records (camera stopped / video ended / cancelled)."""
        self.events.force_finish(reason)
        for stay in self.loitering.reset():
            self._persist_stay(stay)
        self.tracker.reset()
        self.last_detections = []
        self.live_tracks_info = []

    # -------------------------------------------------------- per-frame --
    def process(self, frame: Frame) -> None:
        s = self._settings
        img, ts, wall = frame.image, frame.ts, frame.wall
        self._frame_counter += 1

        motion = self.motion.detect(img)
        if motion.motion and not self._last_motion and time.monotonic() - self._last_motion_log > 5:
            log.info("Motion detected (area=%d px)%s", motion.area, self._where(ts))
            self._last_motion_log = time.monotonic()
        self._last_motion = motion.motion

        busy = motion.motion or bool(self.tracker.tracks) or self.events.active is not None
        run_detection = busy and self._frame_counter % self.detection_every(s) == 0 and self.detector.available

        if run_detection:
            self._detect_and_trigger(img, ts, wall, s, frame.index)
        else:
            removed = self.tracker.expire(ts)
            if removed:
                ended = self.loitering.update([], {z["id"]: z for z in self.zones.zones}, ts, removed, wall).ended
                for stay in ended:
                    self._persist_stay(stay)

        if s["trigger_on_motion"] and motion.motion:
            self.events.trigger(TriggerSignal("motion", detail={"area": motion.area}), ts, wall,
                                self._annotate(img, list(self.tracker.tracks.values()), ts, wall), frame.index)

        self.events.on_frame(ts, img, wall)
        self.buffer.push(ts, img)

        if self.live_view:
            live_tracks = [t for t in self.tracker.tracks.values() if ts - t.last_ts < 1.0]
            self.live_tracks_info = [self._track_dict(t) for t in live_tracks]
            annotated = self._annotate(img, live_tracks, ts, wall)
            with self._annotated_lock:
                self._annotated = annotated

    def _detect_and_trigger(self, img: np.ndarray, ts: float, wall: datetime, s: dict, frame_index: int) -> None:
        detections = self.detector.detect(img, s["yolo_confidence"], frame_index=frame_index, timestamp=wall)
        self.detections_run += 1
        active, removed = self.tracker.update(detections, ts, self.size)
        self.zones.update(active, self.size)
        zone_map = {z["id"]: z for z in self.zones.zones}
        loiter = self.loitering.update(active, zone_map, ts, removed, wall)
        for stay in loiter.ended:
            self._persist_stay(stay)

        relevant = set(s["relevant_objects"])
        signals: list[TriggerSignal] = []
        for t in active:
            confirmed = t.hits >= cfg.MIN_TRACK_HITS
            if confirmed:
                self.confirmed_tracks.setdefault(t.track_id, t.cls)
            t.relevant = t.cls in relevant and confirmed
            t.state = "relevant" if t.relevant else "normal"
            if t.relevant and not t.announced:
                t.announced = True
                log.info("Object detected: %s #%d (%.2f)%s", t.cls, t.track_id, t.confidence, self._where(ts))
            trigger_zones = [zone_map[z] for z in t.zones if z in zone_map and zone_map[z].get("trigger_on_entry")]
            if t.relevant and trigger_zones:
                t.state = "zone"
                if s["trigger_on_zone_entry"]:
                    restricted_first = sorted(trigger_zones, key=lambda z: z.get("zone_type") != "restricted")
                    z = restricted_first[0]
                    signals.append(TriggerSignal("zone_violation", t.cls, t.confidence, t.track_id,
                                                 z["id"], z["name"], t.bbox))
            if t.relevant and s["trigger_on_relevant_object"]:
                z = zone_map.get(next(iter(t.zones), -1))
                signals.append(TriggerSignal("object_detection", t.cls, t.confidence, t.track_id,
                                             z["id"] if z else None, z["name"] if z else None, t.bbox))

        for (tid, zid), stay in self.loitering.stays.items():
            if not stay.triggered or stay.last_ts != ts:
                continue
            track = self.tracker.tracks.get(tid)
            if track is None:
                continue
            track.state = "loitering"
            if s["trigger_on_loitering"]:
                if stay in loiter.triggered:
                    log.info("Loitering: track #%d in %s for %.1fs%s", tid, stay.zone_name, stay.duration,
                             self._where(ts))
                signals.append(TriggerSignal("loitering", track.cls, track.confidence, tid, zid, stay.zone_name,
                                             track.bbox, detail={"dwell": round(stay.duration, 1)}))

        if signals:
            snapshot = self._annotate(img, active, ts, wall)
            signals.sort(key=lambda sig: {"loitering": 0, "zone_violation": 1}.get(sig.event_type, 2))
            for sig in signals:
                event_id = self.events.trigger(sig, ts, wall, snapshot, frame_index)
                if sig.event_type == "loitering" and event_id:
                    st = self.loitering.stays.get((sig.track_id, sig.zone_id))
                    if st and st.event_id is None:
                        st.event_id = event_id
        if self.events.active is not None:
            for t in active:
                if t.relevant or t.state == "loitering":
                    names = [zone_map[z]["name"] for z in t.zones if z in zone_map]
                    self.events.observe_track(t.track_id, t.cls, t.confidence, t.bbox, names, ts, wall)

        self.last_detection_at = wall
        self.last_detections = [self._track_dict(t) for t in active]
        if self.source == "live" and time.monotonic() - self._last_publish > 0.5:
            self._last_publish = time.monotonic()
            event_bus.publish("detections", {"at": wall.astimezone().isoformat(), "tracks": self.last_detections,
                                             "active_event_id": self.events.active_event_id})
        if detections:
            log.debug("Detected: %s", ", ".join(f"{d.cls}:{d.confidence:.2f}" for d in detections))

    # ---------------------------------------------------------- helpers --
    def _where(self, ts: float) -> str:
        return f" at {int(ts // 60):02d}:{ts % 60:04.1f} in video #{self.analysis_id}" if self.source == "video" else ""

    def hud_text(self, ts: float, wall: datetime) -> str:
        return f"{wall:%Y-%m-%d %H:%M:%S}  {self.fps:.0f} fps"

    def _track_dict(self, t: Track) -> dict:
        return {"track_id": t.track_id, "class": t.cls, "confidence": round(t.confidence, 3),
                "bbox": [round(v, 1) for v in t.bbox], "state": t.state, "relevant": t.relevant,
                "zones": [self.zones.zone_by_id(z)["name"] for z in t.zones if self.zones.zone_by_id(z)],
                "dwell": round(self.loitering.dwell(t.track_id), 1)}

    def _annotate(self, img: np.ndarray, tracks: list[Track], ts: float, wall: datetime) -> np.ndarray:
        out = img.copy()
        draw_zones(out, self.zones.zones)
        draw_tracks(out, [self._track_dict(t) for t in tracks])
        ev = self.events.active
        hud = self.hud_text(ts, wall)
        if ev:
            hud += f"  EVENT #{ev.event_id} {ev.event_type}"
        draw_hud(out, hud, recording=ev is not None)
        return out

    def _persist_stay(self, stay: Stay) -> None:
        try:
            with session_scope() as db:
                db.add(LoiteringRecord(
                    track_id=stay.track_id, object_class=stay.object_class, zone_id=stay.zone_id,
                    zone_name=stay.zone_name, enter_time=stay.enter_wall,
                    exit_time=LoiteringDetector.exit_wall(stay), duration=round(stay.duration, 2),
                    threshold=stay.threshold, status="triggered" if stay.triggered else "cleared",
                    event_id=stay.event_id, analysis_id=self.analysis_id,
                ))
        except Exception as exc:
            log.error("Could not save loitering record: %s", exc)

    def annotated_frame(self) -> np.ndarray | None:
        with self._annotated_lock:
            return self._annotated

    def object_counts(self) -> dict[str, int]:
        return dict(Counter(self.confirmed_tracks.values()))

    def active_stays(self) -> list[dict]:
        return [{"track_id": s.track_id, "object_class": s.object_class, "zone_id": s.zone_id,
                 "zone_name": s.zone_name, "enter_time": s.enter_wall.isoformat(),
                 "duration": round(s.duration, 1), "threshold": s.threshold, "triggered": s.triggered,
                 "event_id": s.event_id}
                for s in self.loitering.stays.values()]
