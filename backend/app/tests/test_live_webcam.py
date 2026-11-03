"""Live Monitoring with the browser webcam: frames pushed over /ws/webcam run through the
shared engine; Twilio alerts; api_keys.py credentials; no simulated camera."""
import time
from datetime import datetime
from unittest.mock import patch

import cv2
import httpx
import pytest
from fastapi.testclient import TestClient

from app.core import config as config_module
from app.core.config import settings as cfg
from app.database.database import session_scope
from app.database.models import Event, Notification, Zone
from app.main import app
from app.services import notification_service, twilio_service
from app.services.camera_service import build_source
from app.services.pipeline import get_pipeline
from app.services.settings_service import settings_service
from app.tests.conftest import FakeDetector, scene


def jpeg(img) -> bytes:
    return cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 90])[1].tobytes()


# ----------------------------------------------------------- no simulation --
def test_simulated_camera_is_gone():
    with pytest.raises(ValueError, match="Unknown source type"):
        build_source("simulated", "", True)
    assert cfg.CAMERA_SOURCE_TYPE == "browser"


def test_start_rejects_simulated_source():
    with TestClient(app) as c:
        assert c.post("/api/camera/start", json={"source_type": "simulated"}).status_code == 422


# ---------------------------------------------------- browser webcam e2e ---
def test_browser_webcam_frames_drive_the_pipeline():
    """Person walks into a restricted zone in front of the 'webcam' -> zone violation event with
    pre-event context, tracking IDs and live results returned to the browser for every frame."""
    settings_service.update({"post_event_seconds": 2, "pre_event_seconds": 2})
    with session_scope() as db:
        db.add(Zone(name="Restricted Area", zone_type="restricted",
                    points=[[0.5, 0.0], [1.0, 0.0], [1.0, 1.0], [0.5, 1.0]]))
    p = get_pipeline()
    old_detector = p.detector
    p.detector = FakeDetector()
    p.reload_zones()
    results = []
    try:
        with TestClient(app) as c, patch("app.services.notification_service.notify_event"):
            r = c.post("/api/camera/start", json={"source_type": "browser"})
            assert r.status_code == 200 and r.json()["source_type"] == "browser"
            with c.websocket_connect("/ws/webcam?label=Test%20Cam") as ws:
                # empty scene, then a person walking from left into the zone, then empty again
                for i in range(140):
                    x = None if i < 30 or i >= 100 else min(80 + (i - 30) * 8, 420)
                    ws.send_bytes(jpeg(scene(person_x=x)))
                    msg = ws.receive_json()
                    assert msg["type"] == "result"
                    results.append(msg)
                    time.sleep(1 / 30)
                assert c.get("/api/camera/status").json()["webcam_connected"] is True
            c.post("/api/camera/stop")
            for _ in range(100):
                with session_scope() as db:
                    evs = db.query(Event).all()
                    if evs and all(e.status == "completed" for e in evs):
                        break
                time.sleep(0.1)
    finally:
        p.detector = old_detector
    assert any(m["motion"] for m in results)
    tracked = [t for m in results for t in m["tracks"]]
    assert tracked and {t["class"] for t in tracked} == {"person"}
    assert len({t["track_id"] for t in tracked}) == 1  # one person keeps one tracking ID
    assert any(t["state"] == "zone" and t["zones"] == ["Restricted Area"] for t in tracked)
    with session_scope() as db:
        ev = db.query(Event).one()  # continuous presence merged into ONE event
        assert ev.source == "live" and ev.event_type == "zone_violation" and ev.zone_name == "Restricted Area"
        assert ev.metadata_json["track_id"] == tracked[0]["track_id"]
        assert ev.metadata_json["pre_event_seconds"] > 1.0  # frames from before the trigger are in the clip
        assert (cfg.storage_dir / ev.video_path).exists() and (cfg.storage_dir / ev.snapshot_path).exists()


def test_webcam_socket_requires_started_monitoring():
    with TestClient(app) as c:
        c.post("/api/camera/stop")
        with c.websocket_connect("/ws/webcam") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "error" and "not started" in msg["detail"]


# ------------------------------------------------------------------ Twilio --
def make_event(**kw) -> int:
    base = dict(event_type="zone_violation", status="completed", start_time=datetime(2026, 11, 3, 13, 25, 30),
                timestamp=datetime(2026, 11, 3, 13, 25, 30), duration=14.0, object_class="person",
                confidence=0.94, zone_name="Restricted Area", source="live",
                summary="A person entered the restricted area and remained there for approximately 14 seconds.",
                summary_source="gemini", metadata_json={})
    base.update(kw)
    with session_scope() as db:
        ev = Event(**base)
        db.add(ev)
        db.flush()
        return ev.id


@pytest.fixture
def twilio_creds():
    with patch.multiple(cfg, TWILIO_ACCOUNT_SID="ACtest", TWILIO_AUTH_TOKEN="secret-token",
                        TWILIO_FROM_NUMBER="+15005550006", TWILIO_TO_NUMBER="+919800000000"):
        yield


def test_twilio_sends_one_message_per_event(twilio_creds):
    eid = make_event()
    calls = []

    def fake_post(url, auth, data, timeout):
        calls.append((url, auth, data))
        return httpx.Response(201, json={"sid": "SM123"})

    with patch("app.services.twilio_service.httpx.post", side_effect=fake_post):
        results = notification_service.notify_event(eid)
    assert {r["channel"]: r["status"] for r in results}["twilio"] == "sent"
    assert len(calls) == 1
    url, auth, data = calls[0]
    assert url.endswith("/Accounts/ACtest/Messages.json") and auth == ("ACtest", "secret-token")
    body = data["Body"]
    for part in ("PreVuCam Alert", "Event: Zone Violation", "Object: Person", "Zone: Restricted Area",
                 "Confidence: 94%", "Time: 1:25 PM", "Summary:", "approximately 14 seconds"):
        assert part in body
    assert data["To"] == "+919800000000" and data["From"] == "+15005550006"


def test_twilio_failure_keeps_event_and_hides_secrets(twilio_creds):
    eid = make_event(summary_source="template")
    resp = httpx.Response(401, json={"code": 20003, "message": "Authenticate"})
    with patch("app.services.twilio_service.httpx.post", return_value=resp):
        results = notification_service.notify_event(eid)
    r = {x["channel"]: x for x in results}["twilio"]
    assert r["status"] == "failed" and "20003" in r["detail"] and "secret-token" not in r["detail"]
    with session_scope() as db:
        assert db.get(Event, eid).status == "completed"
    assert "Gemini summary unavailable" in notification_service.twilio_body(Event(
        id=1, event_type="loitering", start_time=datetime.now(), duration=3, confidence=0.5, summary="x",
        summary_source="template", source="live"))


def test_twilio_unconfigured_is_skipped():
    eid = make_event()
    with patch("app.services.twilio_service.httpx.post") as post:
        results = notification_service.notify_event(eid)
    post.assert_not_called()
    assert {r["channel"]: r for r in results}["twilio"]["detail"] == "not configured"
    with session_scope() as db:
        assert db.query(Notification).filter_by(channel="twilio", status="skipped").count() == 1


# ----------------------------------------------------- api_keys.py file ---
def test_api_keys_file_overrides_and_ignores_placeholders(tmp_path, monkeypatch):
    f = tmp_path / "api_keys.py"
    f.write_text('GEMINI_API_KEY = "AIza-real"\nTWILIO_ACCOUNT_SID = "PASTE_YOUR_TWILIO_ACCOUNT_SID_HERE"\n'
                 'TWILIO_AUTH_TOKEN = ""\nTWILIO_FROM_NUMBER = "+1500"\nTWILIO_TO_NUMBER = "  "\n')
    monkeypatch.setattr(config_module, "API_KEYS_FILE", f)
    s = config_module.Settings(TWILIO_ACCOUNT_SID="from-env")
    assert s.GEMINI_API_KEY == "AIza-real" and s.TWILIO_FROM_NUMBER == "+1500"
    assert s.TWILIO_ACCOUNT_SID == "from-env"  # placeholder ignored -> env value kept
    assert s.TWILIO_TO_NUMBER == ""


def test_broken_api_keys_file_does_not_crash(tmp_path, monkeypatch):
    f = tmp_path / "api_keys.py"
    f.write_text('GEMINI_API_KEY = "unterminated\n')
    monkeypatch.setattr(config_module, "API_KEYS_FILE", f)
    assert config_module.Settings().GEMINI_API_KEY == ""


def test_shipped_api_keys_file_has_only_placeholders():
    text = config_module.API_KEYS_FILE.read_text()
    assert all(f'{n} = "PASTE_YOUR_{n}_HERE"' in text for n in config_module.API_KEY_NAMES)
    assert config_module.Settings().GEMINI_API_KEY != "PASTE_YOUR_GEMINI_API_KEY_HERE"  # placeholders ignored


def test_status_never_exposes_credentials(twilio_creds):
    with TestClient(app) as c:
        body = c.get("/api/notifications/status").text + c.get("/api/settings").text
    assert "secret-token" not in body and "ACtest" not in body and "+919800000000" not in body
