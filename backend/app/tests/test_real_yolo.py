"""End-to-end test with the real YOLOv8 model on the generated sample video.

Skipped automatically when the weights or the sample video are missing.
Create the video with:  python scripts/make_sample_video.py
"""
from datetime import datetime
from pathlib import Path

import cv2
import pytest

from app.core.config import PROJECT_ROOT
from app.core.config import settings as cfg
from app.database.database import session_scope
from app.database.models import Event, Zone
from app.services.camera_service import Frame
from app.services.object_detector import ObjectDetector
from app.services.settings_service import settings_service

SAMPLE = PROJECT_ROOT / "storage" / "uploads" / "sample_walkin.mp4"

pytestmark = pytest.mark.skipif(not (Path(cfg.MODEL_PATH).exists() and SAMPLE.exists()),
                                reason="needs models/yolov8n.pt and storage/uploads/sample_walkin.mp4")


def test_yolo_detects_person_in_sample():
    det = ObjectDetector()
    cap = cv2.VideoCapture(str(SAMPLE))
    cap.set(cv2.CAP_PROP_POS_FRAMES, 20 * 15)
    ok, frame = cap.read()
    cap.release()
    dets = det.detect(frame, 0.5)
    assert ok and any(d.cls == "person" and d.confidence > 0.5 for d in dets)
    d = dets[0].to_dict()
    assert set(d) == {"class", "confidence", "bbox", "timestamp"} and len(d["bbox"]) == 4


def test_full_pipeline_with_real_yolo():
    from unittest.mock import patch

    from app.services.event_processor import process_event
    from app.services.pipeline import SurveillancePipeline

    settings_service.update({"detection_interval": 3})
    with session_scope() as db:
        db.add(Zone(name="Restricted Area", zone_type="restricted",
                    points=[[0.5, 0.3], [0.98, 0.3], [0.98, 0.98], [0.5, 0.98]]))
    with patch("app.services.notification_service.notify_event"):
        p = SurveillancePipeline(post_processor=process_event)
        cap = cv2.VideoCapture(str(SAMPLE))
        fps = cap.get(cv2.CAP_PROP_FPS)
        p.events.fps = fps
        i = 0
        while True:
            ok, img = cap.read()
            if not ok:
                break
            p.process(Frame(image=img, ts=i / fps, wall=datetime.now(), index=i))
            i += 1
        cap.release()
        p.flush()
        p.events.wait_idle(timeout=180)

    with session_scope() as db:
        ev = db.query(Event).one()
        assert ev.event_type == "loitering" and ev.zone_name == "Restricted Area" and ev.object_class == "person"
        assert ev.metadata_json["loitering_dwell"] > 20
        assert ev.metadata_json["pre_event_seconds"] > 5
        assert (cfg.storage_dir / ev.video_path).exists()
        # person visible ~6-43 s -> 7 s pre + ~36 s + 7 s post
        assert 44 <= ev.metadata_json["video_duration"] <= 56
