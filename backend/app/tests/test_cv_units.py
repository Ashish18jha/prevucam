"""Unit tests: motion detection, circular buffer, tracker, zones, loitering, relevant-object filter."""
from datetime import datetime
from pathlib import Path

import numpy as np

from app.services.circular_buffer import CircularFrameBuffer
from app.services.loitering_detector import LoiteringDetector
from app.services.motion_detector import MotionDetector
from app.services.object_detector import Detection, ObjectDetector, filter_relevant
from app.services.tracker import ObjectTracker
from app.services.zone_detector import ZoneDetector
from app.tests.conftest import H, W, scene


# ------------------------------------------------------------------ motion --
def test_motion_static_scene_has_no_motion():
    md = MotionDetector(sensitivity=60, min_area=500)
    for _ in range(10):
        r = md.detect(scene())
    assert r.motion is False


def test_motion_detects_moving_object():
    md = MotionDetector(sensitivity=60, min_area=500)
    for _ in range(5):
        md.detect(scene())
    r = md.detect(scene(person_x=300))
    assert r.motion is True and r.boxes
    x1, y1, x2, y2 = r.boxes[0]
    assert x1 <= 310 and x2 >= 340 and y1 <= 210


def test_motion_min_area_filters_small_changes():
    md = MotionDetector(sensitivity=60, min_area=50000)
    for _ in range(5):
        md.detect(scene())
    assert md.detect(scene(person_x=300)).motion is False


def test_motion_sensitivity_maps_to_threshold():
    md = MotionDetector()
    md.configure(100, 500)
    low = md.threshold
    md.configure(1, 500)
    assert md.threshold > low


# --------------------------------------------------------- circular buffer --
def test_buffer_keeps_only_last_n_seconds():
    buf = CircularFrameBuffer(seconds=7, fps=10, jpeg_quality=80)
    for i in range(200):  # 20 s of frames
        buf.push(i / 10.0, scene())
    frames = buf.get_frames()
    assert 69 <= len(frames) <= 71
    assert frames[-1][0] - frames[0][0] <= 7.0
    assert frames[0][0] >= 19.9 - 7.0
    assert [t for t, _ in frames] == sorted(t for t, _ in frames)


def test_buffer_has_hard_capacity_and_bounded_memory():
    buf = CircularFrameBuffer(seconds=7, fps=10, jpeg_quality=80)
    for _ in range(500):  # identical timestamps would defeat time-based eviction
        buf.push(1.0, scene())
    assert len(buf) <= buf._frames.maxlen
    assert buf.memory_bytes < 15 * 1024 * 1024


def test_buffer_before_ts_and_raw_mode():
    buf = CircularFrameBuffer(seconds=7, fps=10, jpeg_quality=0)
    img = scene(person_x=100)
    for i in range(30):
        buf.push(i / 10.0, img)
    pre = buf.get_frames(before_ts=2.0)
    assert all(t < 2.0 for t, _ in pre) and len(pre) == 20
    assert np.array_equal(pre[0][1], img)  # raw frames are stored losslessly


def test_buffer_resize():
    buf = CircularFrameBuffer(seconds=7, fps=10)
    for i in range(100):
        buf.push(i / 10.0, scene())
    buf.resize(3)
    buf.push(10.0, scene())
    assert buf.duration <= 3.0


# ----------------------------------------------------------------- tracker --
def _det(cls, x, y=200, w=50, h=200, conf=0.9):
    return Detection(cls, conf, [x, y, x + w, y + h], datetime.now())


def test_tracker_keeps_consistent_ids():
    tr = ObjectTracker()
    ids = []
    for i in range(10):
        active, _ = tr.update([_det("person", 100 + i * 8)], i * 0.2, (W, H))
        ids.append(active[0].track_id)
    assert len(set(ids)) == 1
    assert tr.tracks[ids[0]].hits == 10


def test_tracker_separates_objects_and_classes():
    tr = ObjectTracker()
    active, _ = tr.update([_det("person", 50), _det("person", 400), _det("dog", 52)], 0.0, (W, H))
    assert len({t.track_id for t in active}) == 3
    active, _ = tr.update([_det("person", 58), _det("person", 392), _det("dog", 60)], 0.2, (W, H))
    assert len(tr.tracks) == 3


def test_tracker_expires_lost_tracks():
    tr = ObjectTracker(max_age=1.0)
    tr.update([_det("person", 100)], 0.0, (W, H))
    _, removed = tr.update([], 2.0, (W, H))
    assert len(removed) == 1 and not tr.tracks


# --------------------------------------------------------- relevant filter --
def test_relevant_object_filter():
    dets = [_det("person", 0), _det("dog", 100), _det("car", 200)]
    kept = filter_relevant(dets, ["person", "car"])
    assert [d.cls for d in kept] == ["person", "car"]
    assert filter_relevant(dets, ["cat"]) == []


def test_detector_missing_weights_degrades_gracefully():
    det = ObjectDetector(model_path=str(Path("/nonexistent/yolo.pt")))
    assert det.available is False
    assert det.detect(scene()) == []
    assert "not found" in (det.error or "")
    assert "person" in det.class_names


# ------------------------------------------------------------------- zones --
ZONE = {"id": 1, "name": "Restricted Area", "points": [[0.5, 0.3], [1.0, 0.3], [1.0, 1.0], [0.5, 1.0]],
        "active": True, "trigger_on_entry": True, "loitering_enabled": True, "loitering_seconds": None}


def test_zone_entry_and_exit_transitions():
    zd = ZoneDetector()
    zd.set_zones([ZONE])
    tr = ObjectTracker()
    active, _ = tr.update([_det("person", 100)], 0.0, (W, H))
    assert zd.update(active, (W, H)) == []
    active, _ = tr.update([_det("person", 360)], 0.2, (W, H))  # anchor x=385 > 320 -> inside
    trans = zd.update(active, (W, H))
    assert [(t.kind, t.zone["name"]) for t in trans] == [("enter", "Restricted Area")]
    active, _ = tr.update([_det("person", 250)], 0.4, (W, H))  # same track, anchor now outside
    assert [t.kind for t in zd.update(active, (W, H))] == ["exit"]


def test_inactive_zone_ignored():
    zd = ZoneDetector()
    zd.set_zones([{**ZONE, "active": False}])
    assert zd.zones_for_bbox([400, 200, 450, 400], (W, H)) == []


# --------------------------------------------------------------- loitering --
def _loiter_run(threshold, zone=ZONE, seconds=30, step=1.0):
    zd, tr, ld = ZoneDetector(), ObjectTracker(max_age=3), LoiteringDetector(threshold, ["person"])
    zd.set_zones([zone])
    triggered_at = []
    t = 0.0
    while t <= seconds:
        active, removed = tr.update([_det("person", 400)], t, (W, H))
        zd.update(active, (W, H))
        res = ld.update(active, {zone["id"]: zone}, t, removed)
        if res.triggered:
            triggered_at.append(t)
        t += step
    return triggered_at, ld


def test_loitering_triggers_once_after_threshold():
    triggered_at, ld = _loiter_run(20)
    assert triggered_at == [21.0]  # strictly greater than 20 s
    assert ld.is_loitering(1)


def test_loitering_below_threshold_no_trigger():
    triggered_at, _ = _loiter_run(20, seconds=15)
    assert triggered_at == []


def test_zone_specific_loitering_threshold():
    triggered_at, _ = _loiter_run(20, zone={**ZONE, "loitering_seconds": 5})
    assert triggered_at == [6.0]


def test_loitering_stay_ends_when_person_leaves():
    zd, tr, ld = ZoneDetector(), ObjectTracker(max_age=3), LoiteringDetector(5, ["person"])
    zd.set_zones([ZONE])
    zones = {1: ZONE}
    for t in range(10):
        a, r = tr.update([_det("person", 400)], float(t), (W, H))
        zd.update(a, (W, H))
        ld.update(a, zones, float(t), r)
    a, r = tr.update([_det("person", 380 - 300)], 10.0, (W, H))  # far jump -> new track, old stays
    a, r = tr.update([], 20.0, (W, H))
    res = ld.update(a, zones, 20.0, r)
    assert len(res.ended) == 1 and res.ended[0].triggered and res.ended[0].duration == 9.0


def test_loitering_ignores_other_classes():
    zd, tr, ld = ZoneDetector(), ObjectTracker(), LoiteringDetector(2, ["person"])
    zd.set_zones([ZONE])
    for t in range(10):
        a, r = tr.update([_det("dog", 400)], float(t), (W, H))
        zd.update(a, (W, H))
        assert ld.update(a, {1: ZONE}, float(t), r).triggered == []
