"""Smart zone detection – polygon membership of tracked objects."""
from __future__ import annotations

import threading
from dataclasses import dataclass

import cv2
import numpy as np

from app.services.tracker import Track, anchor


@dataclass
class ZoneTransition:
    track: Track
    zone: dict
    kind: str  # "enter" | "exit"


def point_in_polygon(point: tuple[float, float], polygon_px: np.ndarray) -> bool:
    return cv2.pointPolygonTest(polygon_px, (float(point[0]), float(point[1])), False) >= 0


class ZoneDetector:
    def __init__(self) -> None:
        self._zones: list[dict] = []
        self._lock = threading.Lock()

    def set_zones(self, zones: list[dict]) -> None:
        with self._lock:
            self._zones = [z for z in zones if z.get("active", True)]

    @property
    def zones(self) -> list[dict]:
        with self._lock:
            return list(self._zones)

    def zone_by_id(self, zone_id: int) -> dict | None:
        return next((z for z in self.zones if z["id"] == zone_id), None)

    @staticmethod
    def polygon_px(zone: dict, frame_size: tuple[int, int]) -> np.ndarray:
        w, h = frame_size
        return np.array([[x * w, y * h] for x, y in zone["points"]], np.float32)

    def zones_for_bbox(self, bbox: list[float], frame_size: tuple[int, int]) -> list[dict]:
        pt = anchor(bbox)
        return [z for z in self.zones if point_in_polygon(pt, self.polygon_px(z, frame_size))]

    def update(self, tracks: list[Track], frame_size: tuple[int, int]) -> list[ZoneTransition]:
        """Updates each track's zone membership and returns enter/exit transitions."""
        transitions: list[ZoneTransition] = []
        zones = self.zones
        for t in tracks:
            inside = {z["id"] for z in self.zones_for_bbox(t.bbox, frame_size)}
            for zid in inside - t.zones:
                z = next(z for z in zones if z["id"] == zid)
                transitions.append(ZoneTransition(t, z, "enter"))
            for zid in t.zones - inside:
                z = next((z for z in zones if z["id"] == zid), {"id": zid, "name": f"zone {zid}"})
                transitions.append(ZoneTransition(t, z, "exit"))
            t.zones = inside
        return transitions
