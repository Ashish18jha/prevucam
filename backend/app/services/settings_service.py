"""Runtime settings persisted in the `settings` table.

Defaults come from `core.config`; anything the user changes through the API is
stored in the database and survives restarts. Readers get a cached, thread-safe
snapshot so the hot CV loop never touches the database.
"""
from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from app.core.config import settings as cfg
from app.database.database import session_scope
from app.database.models import SettingEntry
from app.database.schemas import RuntimeSettings
from app.utils.logger import get_logger

log = get_logger("settings")


def _csv(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def default_settings() -> dict[str, Any]:
    return {
        "motion_sensitivity": cfg.MOTION_SENSITIVITY,
        "motion_min_area": cfg.MOTION_MIN_AREA,
        "detection_interval": cfg.DETECTION_INTERVAL,
        "yolo_confidence": cfg.YOLO_CONFIDENCE,
        "relevant_objects": _csv(cfg.RELEVANT_OBJECTS),
        "pre_event_seconds": cfg.PRE_EVENT_SECONDS,
        "post_event_seconds": cfg.POST_EVENT_SECONDS,
        "max_event_seconds": cfg.MAX_EVENT_SECONDS,
        "event_cooldown_seconds": cfg.EVENT_COOLDOWN_SECONDS,
        "trigger_on_relevant_object": True,
        "trigger_on_zone_entry": True,
        "trigger_on_loitering": True,
        "trigger_on_motion": False,
        "loitering_seconds": cfg.LOITERING_SECONDS,
        "loitering_classes": _csv(cfg.LOITERING_CLASSES),
        "twilio_enabled": True,
        "telegram_enabled": True,
        "email_enabled": True,
        "gemini_enabled": True,
        "notify_event_types": ["object_detection", "zone_violation", "loitering"],
        "max_storage_gb": cfg.MAX_STORAGE_GB,
        "retention_days": cfg.RETENTION_DAYS,
        "auto_delete_enabled": cfg.AUTO_DELETE_ENABLED,
    }


class SettingsService:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._cache: dict[str, Any] | None = None
        self._listeners: list[Callable[[dict[str, Any]], None]] = []

    def load(self) -> dict[str, Any]:
        merged = default_settings()
        try:
            with session_scope() as db:
                for row in db.query(SettingEntry).all():
                    if row.key in merged:
                        merged[row.key] = row.value
        except Exception as exc:  # database unavailable -> keep defaults, keep running
            log.error("Could not load settings from database, using defaults: %s", exc)
        validated = RuntimeSettings(**merged).model_dump()
        with self._lock:
            self._cache = validated
        return dict(validated)

    def get(self) -> dict[str, Any]:
        with self._lock:
            if self._cache is None:
                return self.load()
            return dict(self._cache)

    def value(self, key: str) -> Any:
        return self.get()[key]

    def update(self, changes: dict[str, Any]) -> dict[str, Any]:
        changes = {k: v for k, v in changes.items() if v is not None}
        if "relevant_objects" in changes:
            changes["relevant_objects"] = sorted({c.strip().lower() for c in changes["relevant_objects"] if c.strip()})
        if "loitering_classes" in changes:
            changes["loitering_classes"] = sorted({c.strip().lower() for c in changes["loitering_classes"] if c.strip()})
        current = self.get()
        current.update(changes)
        validated = RuntimeSettings(**current).model_dump()  # raises ValidationError on bad config
        with session_scope() as db:
            for key in changes:
                row = db.get(SettingEntry, key)
                if row is None:
                    db.add(SettingEntry(key=key, value=validated[key]))
                else:
                    row.value = validated[key]
        with self._lock:
            self._cache = validated
        log.info("Settings updated: %s", ", ".join(sorted(changes)))
        for listener in list(self._listeners):
            try:
                listener(dict(validated))
            except Exception as exc:
                log.warning("Settings listener failed: %s", exc)
        return dict(validated)

    def reset(self) -> dict[str, Any]:
        with session_scope() as db:
            db.query(SettingEntry).delete()
        with self._lock:
            self._cache = None
        values = self.load()
        for listener in list(self._listeners):
            listener(dict(values))
        return values

    def subscribe(self, listener: Callable[[dict[str, Any]], None]) -> None:
        self._listeners.append(listener)

    def unsubscribe(self, listener: Callable[[dict[str, Any]], None]) -> None:
        try:
            self._listeners.remove(listener)
        except ValueError:
            pass


settings_service = SettingsService()
