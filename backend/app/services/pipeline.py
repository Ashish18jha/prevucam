"""Live surveillance mode: the shared DetectionEngine fed by the CameraService.

Recorded-video mode (services/video_analysis_service.py) drives the very same
engine from an uploaded file instead of a camera.
"""
from __future__ import annotations

import threading

import numpy as np

from app.services.camera_service import CameraService, browser_inbox
from app.services.detection_engine import DetectionEngine
from app.services.event_bus import event_bus
from app.services.event_processor import process_event
from app.services.object_detector import ObjectDetector


class SurveillancePipeline(DetectionEngine):
    def __init__(self, detector: ObjectDetector | None = None, camera: CameraService | None = None,
                 post_processor=process_event) -> None:
        super().__init__(detector=detector, post_processor=post_processor, source="live", live_view=True)
        self.camera = camera or CameraService()
        self.camera.on_frame = self.process
        self.camera.on_stopped = self.flush  # e.g. a non-looping test video reached its end
        self.camera.on_status = lambda st: event_bus.publish("camera_status", self.status())

    def hud_text(self, ts, wall) -> str:
        return f"{wall:%Y-%m-%d %H:%M:%S}  {self.camera.fps:.0f} fps"

    def start(self, **kwargs) -> None:
        self.reset()
        self.camera.start(**kwargs)

    def stop(self) -> None:
        self.camera.stop()
        self.flush()

    def raw_frame(self) -> np.ndarray | None:
        f = self.camera.latest()
        return f.image if f else None

    def status(self) -> dict:
        c = self.camera
        return {
            "running": c.running, "connected": c.connected, "source_type": c.source_type, "source": str(c.source),
            "fps": c.fps, "resolution": list(self.size), "frames_processed": c.frames,
            "last_frame_at": c.last_frame_at, "error": c.error, "motion": self._last_motion,
            "detector_available": self.detector._model is not None,
            "detector_error": self.detector.error, "active_event_id": self.events.active_event_id,
            "tracks": len(self.tracker.tracks),
            "webcam_connected": c.source_type == "browser" and browser_inbox.connected,
            "webcam_label": browser_inbox.label or None,
        }


_pipeline: SurveillancePipeline | None = None
_lock = threading.Lock()


def get_pipeline() -> SurveillancePipeline:
    global _pipeline
    with _lock:
        if _pipeline is None:
            _pipeline = SurveillancePipeline()
        return _pipeline
