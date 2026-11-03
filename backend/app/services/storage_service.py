"""Storage monitoring and retention policy.

Retention never touches events marked `is_protected`. Automatic deletion only
runs when `auto_delete_enabled` is on; otherwise cleanup is manual via the API.
"""
from __future__ import annotations

import shutil
from datetime import datetime, timedelta
from pathlib import Path

from app.core.config import settings as cfg
from app.database.database import session_scope
from app.database.models import Event, Report
from app.services.settings_service import settings_service
from app.utils.logger import get_logger

log = get_logger("storage")


def dir_size(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def resolve(rel: str | None) -> Path | None:
    if not rel:
        return None
    p = (cfg.storage_dir / rel).resolve()
    if cfg.storage_dir not in p.parents and p != cfg.storage_dir:
        raise ValueError("Path escapes storage directory")
    return p


def storage_info() -> dict:
    s = settings_service.get()
    usage = shutil.disk_usage(cfg.storage_dir)
    sizes = {name: dir_size(cfg.storage_dir / name) for name in ("events", "snapshots", "reports", "timelapse")}
    used_by_app = sum(sizes.values())
    max_bytes = int(s["max_storage_gb"] * 1024 ** 3)
    return {
        "total_bytes": usage.total, "used_bytes": usage.used, "free_bytes": usage.free,
        "event_bytes": sizes["events"], "snapshot_bytes": sizes["snapshots"],
        "report_bytes": sizes["reports"], "timelapse_bytes": sizes["timelapse"],
        "max_storage_bytes": max_bytes,
        "usage_percent": round(100.0 * used_by_app / max_bytes, 2) if max_bytes else 0.0,
        "retention_days": s["retention_days"], "auto_delete_enabled": s["auto_delete_enabled"],
    }


def has_free_space(min_bytes: int = 200 * 1024 * 1024) -> bool:
    return shutil.disk_usage(cfg.storage_dir).free >= min_bytes


def delete_event_files(event: Event) -> int:
    freed = 0
    for rel in (event.video_path, event.snapshot_path):
        try:
            p = resolve(rel)
        except ValueError:
            continue
        if p and p.exists():
            freed += p.stat().st_size
            p.unlink()
    return freed


def delete_event(db, event: Event) -> int:
    freed = delete_event_files(event)
    for report in db.query(Report).filter(Report.event_id == event.id).all():
        p = resolve(report.file_path)
        if p and p.exists():
            freed += p.stat().st_size
            p.unlink()
        db.delete(report)
    db.delete(event)
    return freed


def apply_retention(force: bool = False) -> dict:
    """Delete unprotected events older than the retention period, then oldest-first while over quota."""
    s = settings_service.get()
    if not (force or s["auto_delete_enabled"]):
        return {"deleted_events": 0, "freed_bytes": 0, "reason": "auto-delete disabled"}
    cutoff = datetime.now() - timedelta(days=s["retention_days"])
    deleted, freed = 0, 0
    with session_scope() as db:
        old = db.query(Event).filter(Event.is_protected.is_(False), Event.start_time < cutoff,
                                     Event.status.in_(["completed", "failed"])).all()
        for ev in old:
            freed += delete_event(db, ev)
            deleted += 1
    max_bytes = s["max_storage_gb"] * 1024 ** 3
    app_bytes = dir_size(cfg.storage_dir / "events") + dir_size(cfg.storage_dir / "snapshots")
    if app_bytes > max_bytes:
        with session_scope() as db:
            for ev in (db.query(Event).filter(Event.is_protected.is_(False),
                                              Event.status.in_(["completed", "failed"]))
                       .order_by(Event.start_time.asc()).all()):
                if app_bytes <= max_bytes * 0.9:
                    break
                f = delete_event(db, ev)
                app_bytes -= f
                freed += f
                deleted += 1
    if deleted:
        log.info("Retention removed %d events (%.1f MB)", deleted, freed / 1e6)
    return {"deleted_events": deleted, "freed_bytes": freed,
            "reason": f"retention {s['retention_days']} days / quota {s['max_storage_gb']} GB"}
