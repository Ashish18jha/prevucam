"""Recorder, event manager and full pipeline integration tests."""
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import cv2
import pytest

from app.core.config import settings as cfg
from app.database.database import session_scope
from app.database.models import Event, LoiteringRecord, Notification, Zone
from app.services.camera_service import Frame
from app.services.circular_buffer import CircularFrameBuffer
from app.services.event_manager import EventManager, TriggerSignal
from app.services.settings_service import settings_service
from app.services.video_recorder import EventRecorder
from app.tests.conftest import FakeDetector, scene

FPS = 10.0


def video_stats(path: Path) -> tuple[int, float]:
    cap = cv2.VideoCapture(str(path))
    frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    cap.release()
    return frames, frames / fps


# ---------------------------------------------------------------- recorder --
def test_recorder_writes_single_continuous_file(tmp_path):
    rec = EventRecorder(tmp_path / "r.raw.mp4", FPS, (640, 480))
    pre = [(i / FPS, scene()) for i in range(70)]  # 7 s pre-event
    rec.start(pre)
    for i in range(70, 170):  # 10 s event + post
        rec.write(i / FPS, scene(person_x=100))
    out = rec.close(tmp_path / "r.mp4")
    frames, duration = video_stats(out)
    assert out.exists() and not (tmp_path / "r.raw.mp4").exists()
    assert frames == 170 and abs(duration - 17.0) < 0.15
    assert rec.pre_frames == 70


def test_recorder_pads_slow_capture_to_real_time(tmp_path):
    rec = EventRecorder(tmp_path / "s.raw.mp4", FPS, (640, 480))
    rec.start([])
    for i in range(21):  # capture at only 2 fps for 10 s
        rec.write(i * 0.5, scene())
    out = rec.close(tmp_path / "s.mp4")
    _, duration = video_stats(out)
    assert abs(duration - 10.1) < 0.2  # duration follows timestamps, not frame count


# ----------------------------------------------------------- event manager --
def _manager(post=None):
    buf = CircularFrameBuffer(7, FPS, 80)
    return buf, EventManager(buf, settings_service.get, post, fps=FPS, frame_size=(640, 480))


def _feed(buf, em, start, end, trigger_until=None, signal=None):
    t = start
    while t < end - 1e-9:
        img = scene(person_x=200)
        wall = datetime(2026, 11, 1, 21, 34) + timedelta(seconds=t)
        if signal and trigger_until is not None and t < trigger_until:
            em.trigger(signal, t, wall, img)
        em.on_frame(t, img, wall)
        buf.push(t, img)
        t = round(t + 1 / FPS, 4)


def test_event_pre_event_plus_post_event_recording():
    buf, em = _manager()
    sig = TriggerSignal("object_detection", "person", 0.92, track_id=1)
    # 10 s idle, triggers from 10 s to 15 s, then idle until 30 s
    _feed(buf, em, 0.0, 10.0)
    _feed(buf, em, 10.0, 30.0, trigger_until=15.0, signal=sig)
    em.wait_idle()
    with session_scope() as db:
        events = db.query(Event).all()
        assert len(events) == 1
        ev = events[0]
        assert ev.status == "completed" and ev.object_class == "person" and ev.confidence == pytest.approx(0.92)
        meta = ev.metadata_json
        assert meta["pre_event_seconds"] == pytest.approx(7.0, abs=0.15)
        # 7 s pre + ~5 s event + 7 s post, all in ONE file
        assert meta["video_duration"] == pytest.approx(19.0, abs=0.3)
        path = cfg.storage_dir / ev.video_path
        assert path.exists() and path.suffix == ".mp4"
        assert (cfg.storage_dir / ev.snapshot_path).exists()
        assert ev.duration == pytest.approx(4.9, abs=0.2)


def test_event_extends_while_triggers_continue_and_respects_max_duration():
    settings_service.update({"max_event_seconds": 10})
    buf, em = _manager()
    sig = TriggerSignal("object_detection", "person", 0.8, track_id=1)
    _feed(buf, em, 0.0, 30.0, trigger_until=30.0, signal=sig)
    em.force_finish()
    em.wait_idle()
    with session_scope() as db:
        events = db.query(Event).order_by(Event.id).all()
        assert len(events) >= 2
        assert events[0].metadata_json["end_reason"] == "max duration reached"


def test_event_type_upgrade_and_cooldown():
    settings_service.update({"event_cooldown_seconds": 5})
    buf, em = _manager()
    _feed(buf, em, 0.0, 2.0, trigger_until=2.0, signal=TriggerSignal("object_detection", "person", 0.7, 1))
    _feed(buf, em, 2.0, 4.0, trigger_until=4.0,
          signal=TriggerSignal("zone_violation", "person", 0.8, 1, zone_id=None, zone_name="Main Gate"))
    _feed(buf, em, 4.0, 11.5)  # post window ends at 11.0
    assert em.active is None
    _feed(buf, em, 11.5, 13.0, trigger_until=13.0, signal=TriggerSignal("object_detection", "person", 0.7, 1))
    assert em.active is None  # inside cooldown
    em.wait_idle()
    with session_scope() as db:
        ev = db.query(Event).one()
        assert ev.event_type == "zone_violation" and ev.zone_name == "Main Gate"
        assert [t["type"] for t in ev.metadata_json["triggers"]][:2] == ["object_detection", "zone_violation"]


def test_post_processing_failure_does_not_lose_event():
    def boom(_):
        raise RuntimeError("gemini + telegram down")
    buf, em = _manager(post=boom)
    _feed(buf, em, 0.0, 12.0, trigger_until=2.0, signal=TriggerSignal("object_detection", "person", 0.9, 1))
    em.wait_idle()
    with session_scope() as db:
        ev = db.query(Event).one()
        assert ev.status == "completed" and ev.video_path


# ------------------------------------------------------ pipeline integration --
def _run_pipeline(pipeline, seconds, person_path, dog=False):
    """Drive the pipeline frame by frame (no camera thread) on a synthetic scene."""
    for i in range(int(seconds * FPS)):
        t = i / FPS
        x = person_path(t)
        img = scene(person_x=x, dog_x=100 if dog else None)
        pipeline.process(Frame(image=img, ts=t, wall=datetime.now(), index=i))


def _make_pipeline():
    from app.services.event_processor import process_event
    from app.services.pipeline import SurveillancePipeline
    p = SurveillancePipeline(detector=FakeDetector(), post_processor=process_event)
    p.events.fps = FPS
    p.buffer.resize(7, FPS)
    return p


def test_integration_motion_object_event_recording_metadata_notification():
    """Motion -> object -> event -> recording -> metadata -> summary -> notification."""
    with session_scope() as db:
        db.add(Zone(name="Main Gate", points=[[0.5, 0.0], [1.0, 0.0], [1.0, 1.0], [0.5, 1.0]], zone_type="restricted"))
    sent = []
    with patch("app.services.telegram_service.is_configured", return_value=True), \
         patch("app.services.email_service.is_configured", return_value=True), \
         patch("app.services.telegram_service.send_alert", side_effect=lambda *a, **k: sent.append("tg")), \
         patch("app.services.email_service.send_alert", side_effect=lambda *a, **k: sent.append("mail")):
        p = _make_pipeline()

        def path(t):  # absent 0-8 s, walks in 8-12 s into the zone, stands until 18 s, gone after
            if t < 8 or t >= 18:
                return None
            return int(100 + min(t - 8, 4) * 100)

        _run_pipeline(p, 32, path)
        p.flush()
        p.events.wait_idle()

    with session_scope() as db:
        ev = db.query(Event).one()
        assert ev.event_type == "zone_violation" and ev.zone_name == "Main Gate"
        assert ev.object_class == "person" and ev.status == "completed"
        assert ev.summary and "Main Gate" in ev.summary and ev.summary_source == "template"
        assert ev.notification_status == "sent"
        sent_channels = {n.channel for n in db.query(Notification).filter(Notification.status == "sent").all()}
        assert sent_channels == {"telegram", "email"}
        meta = ev.metadata_json
        assert meta["pre_event_seconds"] == pytest.approx(7.0, abs=0.3)
        assert meta["video_duration"] == pytest.approx(7 + 10 + 7, abs=1.0)
        assert ev.objects and ev.objects[0].trajectory
        assert (cfg.storage_dir / ev.video_path).exists()
    assert sorted(sent) == ["mail", "tg"]


def test_irrelevant_objects_do_not_create_events():
    settings_service.update({"relevant_objects": ["person", "car"]})
    p = _make_pipeline()

    def dog_path(t):
        return None

    for i in range(int(15 * FPS)):
        t = i / FPS
        img = scene(dog_x=int(50 + t * 20))  # moving dog -> motion + detection, but not relevant
        p.process(Frame(image=img, ts=t, wall=datetime.now(), index=i))
    p.flush()
    p.events.wait_idle()
    with session_scope() as db:
        assert db.query(Event).count() == 0
    assert p.detector.calls > 0  # YOLO did run, the filter rejected it


def test_motion_gate_skips_detection_on_static_scene():
    p = _make_pipeline()
    for i in range(50):
        p.process(Frame(image=scene(), ts=i / FPS, wall=datetime.now(), index=i))
    assert p.detector.calls == 0


def test_pipeline_loitering_event_and_record():
    settings_service.update({"loitering_seconds": 5, "trigger_on_relevant_object": False})
    with session_scope() as db:
        db.add(Zone(name="Door", points=[[0.5, 0.0], [1.0, 0.0], [1.0, 1.0], [0.5, 1.0]], trigger_on_entry=False))
    with patch("app.services.notification_service.notify_event"):
        p = _make_pipeline()
        _run_pipeline(p, 30, lambda t: 400 + int(t % 2) if 5 <= t < 15 else None)
        p.flush()
        p.events.wait_idle()
    with session_scope() as db:
        ev = db.query(Event).one()
        assert ev.event_type == "loitering" and ev.zone_name == "Door"
        rec = db.query(LoiteringRecord).one()
        assert rec.status == "triggered" and rec.event_id == ev.id and rec.duration >= 5
