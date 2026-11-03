"""Recorded video analysis: upload validation, background run through the shared engine,
7 s pre / post context on the video timeline, merging, relevant-object filtering, cancel, re-run."""
import io
import threading
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import cv2
import pytest
from fastapi.testclient import TestClient

from app.core.config import PROJECT_ROOT
from app.core.config import settings as cfg
from app.database.database import session_scope
from app.database.models import Event, LoiteringRecord, Notification, VideoAnalysis, Zone
from app.main import app
from app.services import video_analysis_service as svc
from app.services.settings_service import settings_service
from app.tests.conftest import FakeDetector, scene
from app.utils.video_utils import VideoError

FPS = 10


def write_video(path: Path, seconds: float, person=lambda t: None, dog=lambda t: None, fps: int = FPS) -> Path:
    w = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (640, 480))
    for i in range(int(seconds * fps)):
        t = i / fps
        w.write(scene(person_x=person(t), dog_x=dog(t)))
    w.release()
    return path


def upload(path: Path, name: str | None = None, recorded_at=None) -> VideoAnalysis:
    with path.open("rb") as fh:
        return svc.save_upload(fh, name or path.name, recorded_at)


def run(analysis_id: int, detector=None, cancel: threading.Event | None = None) -> VideoAnalysis:
    """Run synchronously (what the background worker does) with a deterministic detector."""
    with patch("app.services.video_analysis_service.shared_detector", return_value=detector or FakeDetector()), \
         patch("app.services.notification_service.notify_event"):
        svc.run_analysis(analysis_id, cancel or threading.Event())
    return svc.get(analysis_id)


def events_of(analysis_id: int) -> list[Event]:
    with session_scope() as db:
        return db.query(Event).filter(Event.analysis_id == analysis_id).order_by(Event.video_offset).all()


# ------------------------------------------------------------------ upload --
def test_upload_extracts_metadata_and_stores_safely(tmp_path):
    va = upload(write_video(tmp_path / "clip.mp4", 6), name="../../evil name!.mp4")
    assert va.status == "uploaded" and va.total_frames == 60 and va.fps == pytest.approx(10)
    assert (va.width, va.height) == (640, 480) and va.duration == pytest.approx(6.0)
    stored = cfg.storage_dir / va.file_path
    assert stored.exists() and stored.parent == cfg.storage_dir / "uploads"
    assert ".." not in va.filename and " " not in va.filename and va.filename.startswith("evilname")


@pytest.mark.parametrize("name,data,msg", [
    ("notes.txt", b"hello", "Unsupported format"),
    ("empty.mp4", b"", "empty"),
    ("broken.mp4", b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 5000, "corrupted"),
])
def test_upload_rejects_invalid_files(name, data, msg):
    with pytest.raises(VideoError, match=msg):
        svc.save_upload(io.BytesIO(data), name)
    assert not any(p.name.startswith(Path(name).stem) for p in (cfg.storage_dir / "uploads").glob("*"))


def test_upload_size_limit(tmp_path):
    with patch.object(cfg, "MAX_UPLOAD_MB", 0), pytest.raises(VideoError, match="larger than"):
        upload(write_video(tmp_path / "big.mp4", 2))


# --------------------------------------------------------------- pipeline --
def test_pre_and_post_event_context_on_video_timeline(tmp_path):
    """Person visible 10–15 s: ONE event, clip = 3–22 s (7 s before + event + 7 s after)."""
    path = write_video(tmp_path / "walk.mp4", 30, person=lambda t: 120 + int((t - 10) * 20) if 10 <= t < 15 else None)
    va = run(upload(path, recorded_at=datetime(2026, 11, 2, 21, 32, 0)).id)
    assert va.status == "completed" and va.progress == 100 and va.frames_processed == 300
    evs = events_of(va.id)
    assert len(evs) == 1  # continuous detections are merged into a single event
    ev = evs[0]
    m = ev.metadata_json
    assert ev.source == "video" and ev.object_class == "person" and ev.event_type == "object_detection"
    assert 10.0 <= ev.video_offset <= 10.5 and m["video_event_start"] == pytest.approx(ev.video_offset, abs=0.01)
    assert m["video_clip_start"] == pytest.approx(ev.video_offset - 7, abs=0.11)
    assert m["video_clip_end"] == pytest.approx(m["video_event_end"] + 7, abs=0.11)
    assert m["video_duration"] == pytest.approx(m["video_clip_end"] - m["video_clip_start"], abs=0.25)
    assert 14.3 <= m["video_event_end"] <= 15.0
    # wall-clock time is the recording start + position in the video
    assert ev.start_time.replace(microsecond=0) == datetime(2026, 11, 2, 21, 32, 10)
    clip = cfg.storage_dir / ev.video_path
    cap = cv2.VideoCapture(str(clip))
    frames, fps = cap.get(cv2.CAP_PROP_FRAME_COUNT), cap.get(cv2.CAP_PROP_FPS)
    cap.release()
    assert frames / fps == pytest.approx(m["video_duration"], abs=0.15)  # one consolidated MP4
    assert (cfg.storage_dir / ev.snapshot_path).exists()
    assert ev.summary.startswith("At 9:32 PM (00:10 in the video), a person was detected")
    assert va.objects_detected == 1 and va.events_detected == 1 and va.object_counts == {"person": 1}


def test_event_at_start_of_video_has_partial_pre_context(tmp_path):
    path = write_video(tmp_path / "early.mp4", 15, person=lambda t: 200 if 2 <= t < 5 else None)
    va = run(upload(path).id)
    ev = events_of(va.id)[0]
    assert ev.metadata_json["video_clip_start"] == pytest.approx(0.0, abs=0.01)  # only 2 s exist before it
    assert ev.summary.startswith("At 00:02 in early.mp4")  # no real-world clock -> video position


def test_event_still_open_at_end_of_video_is_closed(tmp_path):
    path = write_video(tmp_path / "tail.mp4", 12, person=lambda t: 200 if t >= 9 else None)
    va = run(upload(path).id)
    ev = events_of(va.id)[0]
    assert ev.status == "completed" and ev.metadata_json["end_reason"] == "end of video"


def test_irrelevant_objects_are_ignored(tmp_path):
    settings_service.update({"relevant_objects": ["person", "car", "motorcycle"]})
    path = write_video(tmp_path / "dog.mp4", 15, dog=lambda t: 50 + int(t * 30))
    det = FakeDetector()
    va = run(upload(path).id, det)
    assert det.calls > 0 and va.status == "completed"
    assert events_of(va.id) == [] and va.object_counts == {"dog": 1}


def test_zone_violation_and_loitering_from_video(tmp_path):
    settings_service.update({"loitering_seconds": 5})
    with session_scope() as db:
        db.add(Zone(name="Restricted Area", zone_type="restricted",
                    points=[[0.5, 0.0], [1.0, 0.0], [1.0, 1.0], [0.5, 1.0]]))
    path = write_video(tmp_path / "loiter.mp4", 30, person=lambda t: 420 if 5 <= t < 15 else None)
    va = run(upload(path).id)
    evs = events_of(va.id)
    assert len(evs) == 1 and evs[0].event_type == "loitering" and evs[0].zone_name == "Restricted Area"
    assert va.loitering_events == 1
    with session_scope() as db:
        rec = db.query(LoiteringRecord).one()
        assert rec.analysis_id == va.id and rec.event_id == evs[0].id and rec.duration >= 9
        # entry time is on the video's clock: within one detection step of the event start
        assert abs((rec.enter_time - evs[0].start_time).total_seconds()) <= 0.5


def test_cancel_stops_safely(tmp_path):
    path = write_video(tmp_path / "long.mp4", 40, person=lambda t: 200 if t >= 3 else None)
    va = upload(path)
    cancel = threading.Event()

    class SlowDetector(FakeDetector):
        def detect(self, *a, **k):
            if self.calls == 20:
                cancel.set()  # user presses Cancel mid-analysis
            return super().detect(*a, **k)

    va = run(va.id, SlowDetector(), cancel)
    assert va.status == "cancelled" and 0 < va.frames_processed < 400 and va.progress < 100
    evs = events_of(va.id)
    assert len(evs) == 1 and evs[0].status == "completed"  # the open event was closed, not left "recording"
    assert evs[0].metadata_json["end_reason"] == "analysis cancelled"
    assert (cfg.storage_dir / evs[0].video_path).exists()


def test_rerun_replaces_previous_events(tmp_path):
    path = write_video(tmp_path / "rerun.mp4", 15, person=lambda t: 200 if 4 <= t < 7 else None)
    va = run(upload(path).id)
    first = events_of(va.id)
    with pytest.raises(ValueError, match="already been analysed"):
        svc.manager.start(va.id)
    with patch.object(svc.AnalysisManager, "_executor"):
        svc.manager.start(va.id, force=True)
    va = run(va.id)
    second = events_of(va.id)
    assert len(first) == len(second) == 1 and second[0].created_at > first[0].created_at
    with session_scope() as db:
        assert db.query(Event).count() == 1  # replaced, not duplicated


def test_detector_unavailable_fails_with_message(tmp_path):
    va = upload(write_video(tmp_path / "x.mp4", 3))
    det = FakeDetector()
    det.available, det.error = False, "YOLO weights not found"
    va = run(va.id, det)
    assert va.status == "failed" and "YOLO weights not found" in va.error


def test_notifications_once_per_event(tmp_path):
    path = write_video(tmp_path / "notify.mp4", 40, person=lambda t: 200 if 5 <= t < 9 or 25 <= t < 29 else None)
    va = upload(path)
    sent = []
    with patch("app.services.video_analysis_service.shared_detector", return_value=FakeDetector()), \
         patch("app.services.telegram_service.is_configured", return_value=True), \
         patch("app.services.email_service.is_configured", return_value=True), \
         patch("app.services.telegram_service.send_alert", side_effect=RuntimeError("telegram down")), \
         patch("app.services.email_service.send_alert", side_effect=lambda *a, **k: sent.append(a[0])):
        svc.run_analysis(va.id, threading.Event())
    evs = events_of(va.id)
    assert svc.get(va.id).status == "completed" and len(evs) == 2
    assert len(sent) == 2 and all("PreVuCam Alert" in s for s in sent)  # one email per event, not per frame
    with session_scope() as db:
        assert db.query(Notification).filter_by(channel="telegram", status="failed").count() == 2
    assert all(e.notification_status == "partial" for e in evs)


# --------------------------------------------------------------------- API --
def test_api_upload_start_status_events(tmp_path):
    path = write_video(tmp_path / "api.mp4", 20, person=lambda t: 200 if 6 <= t < 10 else None)
    with TestClient(app) as c, \
            patch("app.services.video_analysis_service.shared_detector", return_value=FakeDetector()):
        r = c.post("/api/video-analysis/upload", files={"file": ("security_video.mp4", path.read_bytes(), "video/mp4")})
        assert r.status_code == 201
        body = r.json()
        aid = body["analysis_id"]
        assert body["status"] == "uploaded" and body["total_frames"] == 200 and body["width"] == 640
        assert c.post(f"/api/video-analysis/{aid}/start").json() == {"analysis_id": aid, "status": "queued"}
        for _ in range(200):
            st = c.get(f"/api/video-analysis/{aid}/status").json()
            if st["status"] in ("completed", "failed", "cancelled"):
                break
            time.sleep(0.1)
        assert st["status"] == "completed" and st["progress"] == 100 and st["events_detected"] == 1
        assert st["persons_detected"] == 1
        evs = c.get(f"/api/video-analysis/{aid}/events").json()
        assert len(evs) == 1 and evs[0]["analysis_id"] == aid and evs[0]["analysis_name"] == "security_video.mp4"
        # the events show up in the normal Events search, filterable by analysis
        assert c.get("/api/events", params={"analysis_id": aid}).json()["total"] == 1
        assert c.get("/api/events", params={"source": "live"}).json()["total"] == 0
        assert c.get("/api/events", params={"keyword": "security_video"}).json()["total"] == 1
        assert c.get("/api/analytics/summary").json()["person_detections"] == 1
        assert c.get(f"/api/video-analysis/{aid}/video").status_code == 200
        rep = c.post(f"/api/reports/events/{evs[0]['id']}")
        assert rep.status_code == 201
        assert c.post(f"/api/video-analysis/{aid}/cancel").status_code == 409
        assert c.post("/api/video-analysis/999/start").status_code == 404
        bad = c.post("/api/video-analysis/upload", files={"file": ("x.mov", b"garbage", "video/quicktime")})
        assert bad.status_code == 400 and "corrupted" in bad.json()["detail"]


def test_restart_recovers_interrupted_jobs(tmp_path):
    va = upload(write_video(tmp_path / "r.mp4", 2))
    with session_scope() as db:
        db.get(VideoAnalysis, va.id).status = "processing"
        db.add(Event(event_type="object_detection", status="recording", source="video", analysis_id=va.id))
    svc.recover_interrupted()
    assert svc.get(va.id).status == "failed" and "restart" in svc.get(va.id).error
    assert events_of(va.id)[0].status == "failed"


# --------------------------------------------------------- real YOLOv8n ---
SECURITY = next((p for p in (PROJECT_ROOT / "samples" / "security_test.mp4",
                              PROJECT_ROOT / "storage" / "uploads" / "security_test.mp4") if p.exists()),
                PROJECT_ROOT / "samples" / "security_test.mp4")


@pytest.mark.skipif(not (Path(cfg.MODEL_PATH).exists() and SECURITY.exists()),
                    reason="needs models/yolov8n.pt and scripts/make_security_test_video.py output")
def test_security_video_with_real_yolo():
    settings_service.update({"detection_interval": 3})  # production default
    with session_scope() as db:
        db.add(Zone(name="Restricted Area", zone_type="restricted",
                    points=[[0.55, 0.35], [0.99, 0.35], [0.99, 0.99], [0.55, 0.99]]))
    va = upload(SECURITY)
    with patch("app.services.notification_service.notify_event"):
        svc.run_analysis(va.id, threading.Event())
    va = svc.get(va.id)
    evs = events_of(va.id)
    assert va.status == "completed"
    assert [(e.event_type, e.object_class) for e in evs] == [
        ("object_detection", "person"), ("zone_violation", "bus"), ("loitering", "person")]
    assert va.object_counts == {"person": 2, "bus": 1}
    assert va.detections_run < va.total_frames / 4  # motion gate + interval keep YOLO off most frames
    for e in evs:
        m = e.metadata_json
        assert m["pre_event_seconds"] == pytest.approx(7, abs=0.1)
        assert m["video_clip_end"] - m["video_event_end"] == pytest.approx(7, abs=0.1)
