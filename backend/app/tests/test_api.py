"""REST API, database, PDF report, summary and notification-failure tests."""
from datetime import datetime, timedelta
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app.database.database import session_scope
from app.database.models import Event, EventObject, Notification
from app.main import app
from app.services import notification_service
from app.services.summarizer import summarize


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def make_event(**kw) -> int:
    base = dict(event_type="object_detection", status="completed", start_time=datetime(2026, 11, 1, 21, 34),
                timestamp=datetime(2026, 11, 1, 21, 34), end_time=datetime(2026, 11, 1, 21, 34, 18),
                duration=18.0, object_class="person", confidence=0.93, zone_name="Main Gate",
                metadata_json={"object_counts": {"person": 1}, "video_duration": 32.0, "pre_event_seconds": 7.0})
    base.update(kw)
    with session_scope() as db:
        ev = Event(**base)
        db.add(ev)
        db.flush()
        db.add(EventObject(event_id=ev.id, track_id=3, object_class=base["object_class"] or "person",
                           max_confidence=0.93, first_seen=base["start_time"],
                           last_seen=base["start_time"] + timedelta(seconds=18), zones=["Main Gate"],
                           trajectory=[[0, 0.1, 0.5], [18, 0.8, 0.5]]))
        return ev.id


# ------------------------------------------------------------------ system --
def test_health_and_docs(client):
    assert client.get("/api/health").json()["status"] == "ok"
    assert client.get("/docs").status_code == 200
    spec = client.get("/openapi.json").json()
    assert "/api/events" in spec["paths"] and "/api/zones/{zone_id}" in spec["paths"]


# ------------------------------------------------------------------- zones --
def test_zone_crud(client):
    body = {"name": "Main Gate", "points": [[0.1, 0.1], [0.4, 0.1], [0.4, 0.6], [0.1, 0.6]], "zone_type": "restricted"}
    r = client.post("/api/zones", json=body)
    assert r.status_code == 201
    zid = r.json()["id"]
    assert client.post("/api/zones", json=body).status_code == 409
    r = client.put(f"/api/zones/{zid}", json={"name": "Front Gate", "loitering_seconds": 30})
    assert r.json()["name"] == "Front Gate" and r.json()["loitering_seconds"] == 30
    assert len(client.get("/api/zones").json()) == 1
    assert client.delete(f"/api/zones/{zid}").status_code == 200
    assert client.get(f"/api/zones/{zid}").status_code == 404


@pytest.mark.parametrize("points", [[[0.1, 0.1], [0.2, 0.2]], [[0.1, 0.1], [1.5, 0.2], [0.3, 0.3]]])
def test_invalid_zone_rejected(client, points):
    assert client.post("/api/zones", json={"name": "Bad", "points": points}).status_code == 422


# ---------------------------------------------------------------- settings --
def test_settings_get_update_validate(client):
    s = client.get("/api/settings").json()
    assert s["pre_event_seconds"] == 7 and s["post_event_seconds"] == 7
    r = client.put("/api/settings", json={"yolo_confidence": 0.6, "motion_sensitivity": 80})
    assert r.status_code == 200 and r.json()["yolo_confidence"] == 0.6
    assert client.put("/api/settings", json={"yolo_confidence": 5}).status_code == 422
    assert client.put("/api/settings", json={"pre_event_seconds": -1}).status_code == 422


def test_relevant_objects_api(client):
    r = client.put("/api/settings/relevant-objects", json={"relevant_objects": ["Person", "car", "motorcycle"]})
    assert r.status_code == 200 and r.json()["relevant_objects"] == ["car", "motorcycle", "person"]
    assert "dog" in client.get("/api/settings/relevant-objects").json()["available_classes"]
    assert client.put("/api/settings/relevant-objects", json={"relevant_objects": ["dragon"]}).status_code == 422


def test_loitering_settings_api(client):
    r = client.put("/api/loitering/settings", json={"loitering_seconds": 25, "loitering_classes": ["person"]})
    assert r.json()["loitering_seconds"] == 25
    assert client.get("/api/loitering/settings").json()["loitering_seconds"] == 25


# ------------------------------------------------------------------ events --
def test_event_search_filters(client):
    a = make_event()
    make_event(event_type="loitering", object_class="person", zone_name="Parking", duration=40,
               start_time=datetime(2026, 11, 1, 8, 0), summary="A person lingered near the bikes")
    make_event(object_class="car", zone_name=None, start_time=datetime(2026, 10, 30, 12, 0), duration=5)

    def ids(**params):
        return {e["id"] for e in client.get("/api/events", params=params).json()["items"]}

    assert len(ids()) == 3
    assert ids(date="2026-11-01", object_class="person", zone="Main Gate") == {a}
    assert len(ids(object_class="car")) == 1
    assert len(ids(event_type="loitering")) == 1
    assert len(ids(min_duration=10, max_duration=20)) == 1
    assert len(ids(keyword="bikes")) == 1
    assert len(ids(date="2026-11-01", start_time="21:00", end_time="22:00")) == 1
    assert len(ids(date_from="2026-10-31")) == 2


def test_event_detail_update_delete(client):
    eid = make_event()
    d = client.get(f"/api/events/{eid}").json()
    assert d["objects"][0]["track_id"] == 3
    assert client.patch(f"/api/events/{eid}", json={"is_protected": True}).json()["is_protected"] is True
    assert client.delete(f"/api/events/{eid}").status_code == 200
    assert client.get(f"/api/events/{eid}").status_code == 404
    assert client.get(f"/api/events/{eid}/video").status_code == 404


def test_regenerate_summary(client):
    eid = make_event(event_type="zone_violation")
    r = client.post(f"/api/events/{eid}/summary").json()
    assert r["summary"].startswith("At 9:34 PM, a person entered the Main Gate area and remained there for 18 seconds")
    assert r["summary_source"] == "template"


def test_analytics_endpoints(client):
    make_event(start_time=datetime.now())
    make_event(event_type="loitering", start_time=datetime.now())
    s = client.get("/api/analytics/summary").json()
    assert s["events_today"] == 2 and s["loitering_events"] == 1 and s["person_detections"] == 2
    c = client.get("/api/analytics/charts").json()
    assert sum(i["count"] for i in c["by_type"]) == 2 and len(c["by_hour"]) == 24
    assert client.get("/api/storage").json()["total_bytes"] > 0


# ----------------------------------------------------------------- reports --
def test_pdf_report_generation(client):
    eid = make_event(summary="A person entered the main gate area at approximately 9:34 PM.")
    r = client.post(f"/api/reports/events/{eid}")
    assert r.status_code == 201
    pdf = client.get(f"/api/reports/{r.json()['id']}")
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF" and len(pdf.content) > 1500
    assert client.post("/api/reports/events/99999").status_code == 404


def test_camera_endpoints_and_errors(client):
    assert client.get("/api/camera/status").json()["running"] is False
    assert client.get("/api/camera/snapshot").status_code in (200, 404)
    r = client.post("/api/camera/start", json={"source_type": "file", "source": "missing.mp4"})
    assert r.status_code == 200  # source errors are reported in status, camera keeps retrying
    st = client.get("/api/camera/status").json()
    client.post("/api/camera/stop")
    bad = client.post("/api/camera/upload", files={"file": ("x.mp4", b"not a video", "video/mp4")})
    assert bad.status_code == 400
    assert client.post("/api/camera/upload", files={"file": ("x.txt", b"x", "text/plain")}).status_code == 400
    assert st["source_type"] == "file"


def test_timelapse_no_events_fails_cleanly(client):
    r = client.post("/api/timelapse/generate", json={"date": "2020-01-01"})
    assert r.status_code == 202
    t = client.get(f"/api/timelapse/{r.json()['id']}").json()
    assert t["status"] == "failed" and "No recorded events" in t["error"]


# ----------------------------------------------- AI + notification failures --
def test_gemini_failure_falls_back_to_template():
    eid = make_event()
    with session_scope() as db:
        ev = db.get(Event, eid)
        with patch("app.services.summarizer.cfg.GEMINI_API_KEY", "fake-key"), \
             patch("app.services.summarizer.httpx.post", side_effect=httpx.ConnectError("offline")):
            text, source, err = summarize(ev)
    assert source == "template" and "9:34 PM" in text and "offline" in err


def test_gemini_success_path():
    eid = make_event()
    resp = httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "A person entered the gate."}]}}]})
    with session_scope() as db:
        ev = db.get(Event, eid)
        with patch("app.services.summarizer.cfg.GEMINI_API_KEY", "fake-key"), \
             patch("app.services.summarizer.httpx.post", return_value=resp) as post:
            text, source, err = summarize(ev)
    assert (text, source, err) == ("A person entered the gate.", "gemini", None)
    sent = post.call_args.kwargs["json"]["contents"][0]["parts"][0]["text"]
    assert '"zone": "Main Gate"' in sent and "fake-key" not in sent


def test_telegram_failure_does_not_block_email():
    eid = make_event()
    with patch("app.services.telegram_service.is_configured", return_value=True), \
         patch("app.services.email_service.is_configured", return_value=True), \
         patch("app.services.telegram_service.send_alert", side_effect=RuntimeError("telegram down")), \
         patch("app.services.email_service.send_alert", return_value="sent") as mail:
        results = notification_service.notify_event(eid)
    assert {r["channel"]: r["status"] for r in results} == {"twilio": "skipped", "telegram": "failed", "email": "sent"}
    mail.assert_called_once()
    with session_scope() as db:
        assert db.get(Event, eid).notification_status == "partial"
        assert db.query(Notification).filter_by(status="failed").count() == 1


def test_unconfigured_channels_are_skipped(client):
    eid = make_event()
    r = client.post(f"/api/events/{eid}/notify").json()
    assert {x["status"] for x in r} == {"skipped"}
    st = client.get("/api/notifications/status").json()
    assert st["telegram_configured"] is False and st["gemini_configured"] is False
