"""Lightweight multi-object tracker (IoU + centroid distance, greedy assignment).

Keeps a stable integer ID per object across detection cycles so that zone
entry/exit, loitering and trajectories refer to the same physical object.
Dependency-free and cheap enough for a Raspberry Pi.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from app.services.object_detector import Detection


def iou(a: list[float], b: list[float]) -> float:
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    if inter <= 0:
        return 0.0
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    return inter / (area_a + area_b - inter + 1e-9)


def center(b: list[float]) -> tuple[float, float]:
    return (b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0


def anchor(b: list[float]) -> tuple[float, float]:
    """Bottom-centre point – where a person/vehicle touches the ground."""
    return (b[0] + b[2]) / 2.0, b[3]


@dataclass
class Track:
    track_id: int
    cls: str
    bbox: list[float]
    confidence: float
    first_ts: float
    last_ts: float
    hits: int = 1
    max_confidence: float = 0.0
    trajectory: deque = field(default_factory=lambda: deque(maxlen=300))
    zones: set[int] = field(default_factory=set)
    state: str = "normal"
    relevant: bool = False
    announced: bool = False

    def update(self, det: Detection, ts: float) -> None:
        self.bbox = det.bbox
        self.confidence = det.confidence
        self.max_confidence = max(self.max_confidence, det.confidence)
        self.last_ts = ts
        self.hits += 1
        cx, cy = center(det.bbox)
        self.trajectory.append((round(ts, 2), round(cx, 1), round(cy, 1)))


class ObjectTracker:
    def __init__(self, iou_threshold: float = 0.25, max_age: float = 2.0, max_center_dist: float = 0.15) -> None:
        self.iou_threshold = iou_threshold
        self.max_age = max_age  # seconds without a match before a track is dropped
        self.max_center_dist = max_center_dist  # fraction of frame diagonal
        self.tracks: dict[int, Track] = {}
        self._next_id = 1

    def reset(self) -> None:
        self.tracks.clear()
        self._next_id = 1

    def update(self, detections: list[Detection], ts: float, frame_size: tuple[int, int]) -> tuple[list[Track], list[Track]]:
        """Returns (active_tracks, removed_tracks)."""
        w, h = frame_size
        diag = (w * w + h * h) ** 0.5
        candidates = []
        for tid, t in self.tracks.items():
            for di, d in enumerate(detections):
                if d.cls != t.cls:
                    continue
                score = iou(t.bbox, d.bbox)
                if score < self.iou_threshold:
                    (tx, ty), (dx, dy) = center(t.bbox), center(d.bbox)
                    dist = ((tx - dx) ** 2 + (ty - dy) ** 2) ** 0.5 / diag
                    if dist > self.max_center_dist:
                        continue
                    score = 0.01 + (self.max_center_dist - dist) * 0.1  # weak match, below any IoU match
                candidates.append((score, tid, di))
        candidates.sort(reverse=True)

        used_tracks, used_dets = set(), set()
        for _, tid, di in candidates:
            if tid in used_tracks or di in used_dets:
                continue
            self.tracks[tid].update(detections[di], ts)
            used_tracks.add(tid)
            used_dets.add(di)

        for di, d in enumerate(detections):
            if di in used_dets:
                continue
            t = Track(track_id=self._next_id, cls=d.cls, bbox=d.bbox, confidence=d.confidence,
                      first_ts=ts, last_ts=ts, max_confidence=d.confidence)
            cx, cy = center(d.bbox)
            t.trajectory.append((round(ts, 2), round(cx, 1), round(cy, 1)))
            self.tracks[t.track_id] = t
            self._next_id += 1

        removed = [t for t in self.tracks.values() if ts - t.last_ts > self.max_age]
        for t in removed:
            del self.tracks[t.track_id]
        active = [t for t in self.tracks.values() if t.last_ts == ts]
        return active, removed

    def expire(self, ts: float) -> list[Track]:
        removed = [t for t in self.tracks.values() if ts - t.last_ts > self.max_age]
        for t in removed:
            del self.tracks[t.track_id]
        return removed
