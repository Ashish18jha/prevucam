"""Loitering detection: a tracked object stays inside a zone longer than a threshold.

Dwell time is measured on the source clock (`ts`) from the moment the track's
ground-anchor enters the zone. Each (track, zone) stay is persisted as a
LoiteringRecord when it ends so stays below the threshold are auditable too.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.services.tracker import Track


@dataclass
class Stay:
    track_id: int
    object_class: str
    zone_id: int
    zone_name: str
    enter_ts: float
    enter_wall: datetime
    threshold: float
    last_ts: float = 0.0
    triggered: bool = False
    event_id: int | None = None

    @property
    def duration(self) -> float:
        return max(0.0, self.last_ts - self.enter_ts)


@dataclass
class LoiteringUpdate:
    triggered: list[Stay] = field(default_factory=list)  # crossed the threshold this cycle
    ended: list[Stay] = field(default_factory=list)  # stay finished (exit or track lost)


class LoiteringDetector:
    def __init__(self, threshold: float = 20.0, classes: list[str] | None = None) -> None:
        self.threshold = threshold
        self.classes = set(classes or ["person"])
        self.stays: dict[tuple[int, int], Stay] = {}

    def configure(self, threshold: float, classes: list[str]) -> None:
        self.threshold = float(threshold)
        self.classes = {c.lower() for c in classes}

    def reset(self) -> list[Stay]:
        ended = list(self.stays.values())
        self.stays.clear()
        return ended

    def update(self, tracks: list[Track], zones: dict[int, dict], ts: float,
               removed: list[Track] | None = None, wall: datetime | None = None) -> LoiteringUpdate:
        result = LoiteringUpdate()
        seen: set[tuple[int, int]] = set()
        for t in tracks:
            if t.cls.lower() not in self.classes:
                continue
            for zid in t.zones:
                zone = zones.get(zid)
                if zone is None or not zone.get("loitering_enabled", True):
                    continue
                key = (t.track_id, zid)
                seen.add(key)
                stay = self.stays.get(key)
                if stay is None:
                    threshold = zone.get("loitering_seconds") or self.threshold
                    stay = Stay(t.track_id, t.cls, zid, zone["name"], ts,
                                wall or datetime.now(), float(threshold), last_ts=ts)
                    self.stays[key] = stay
                stay.last_ts = ts
                if not stay.triggered and stay.duration > stay.threshold:
                    stay.triggered = True
                    result.triggered.append(stay)

        removed_ids = {t.track_id for t in (removed or [])}
        active_ids = {t.track_id for t in tracks}
        for key, stay in list(self.stays.items()):
            if key in seen:
                continue
            track_gone = stay.track_id in removed_ids
            left_zone = stay.track_id in active_ids  # track still visible, just not in this zone
            if track_gone or left_zone:
                result.ended.append(self.stays.pop(key))
        return result

    def dwell(self, track_id: int) -> float:
        durations = [s.duration for (tid, _), s in self.stays.items() if tid == track_id]
        return max(durations) if durations else 0.0

    def is_loitering(self, track_id: int) -> bool:
        return any(s.triggered for (tid, _), s in self.stays.items() if tid == track_id)

    @staticmethod
    def exit_wall(stay: Stay) -> datetime:
        return stay.enter_wall + timedelta(seconds=stay.duration)
