"""Event search and CRUD helpers (used by the API layer)."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.database.models import Event, EventObject, VideoAnalysis, Zone


def search_events(
    db: Session, *, day: date | None = None, start_time: time | None = None, end_time: time | None = None,
    date_from: date | None = None, date_to: date | None = None, object_class: str | None = None,
    keyword: str | None = None, zone: str | None = None, event_type: str | None = None,
    min_duration: float | None = None, max_duration: float | None = None, status: str | None = None,
    protected: bool | None = None, analysis_id: int | None = None, source: str | None = None, page: int = 1, page_size: int = 25, sort: str = "desc",
) -> tuple[list[Event], int]:
    q = db.query(Event)
    if day:
        start = datetime.combine(day, time.min)
        q = q.filter(Event.start_time >= start, Event.start_time < start + timedelta(days=1))
        if start_time:
            q = q.filter(Event.start_time >= datetime.combine(day, start_time))
        if end_time:
            q = q.filter(Event.start_time <= datetime.combine(day, end_time))
    else:
        if date_from:
            q = q.filter(Event.start_time >= datetime.combine(date_from, time.min))
        if date_to:
            q = q.filter(Event.start_time < datetime.combine(date_to + timedelta(days=1), time.min))
    if object_class:
        cls = object_class.lower()
        sub = db.query(EventObject.event_id).filter(EventObject.object_class == cls)
        q = q.filter(or_(Event.object_class == cls, Event.id.in_(sub)))
    if zone:
        if zone.isdigit():
            q = q.filter(Event.zone_id == int(zone))
        else:
            q = q.filter(Event.zone_name.ilike(zone))
    if event_type:
        q = q.filter(Event.event_type == event_type)
    if min_duration is not None:
        q = q.filter(Event.duration >= min_duration)
    if max_duration is not None:
        q = q.filter(Event.duration <= max_duration)
    if status:
        q = q.filter(Event.status == status)
    if protected is not None:
        q = q.filter(Event.is_protected.is_(protected))
    if analysis_id is not None:
        q = q.filter(Event.analysis_id == analysis_id)
    if source:
        q = q.filter(Event.source == source)
    if keyword:
        like = f"%{keyword.strip()}%"
        names = db.query(VideoAnalysis.id).filter(VideoAnalysis.original_name.ilike(like))
        q = q.filter(or_(Event.summary.ilike(like), Event.object_class.ilike(like),
                         Event.zone_name.ilike(like), Event.event_type.ilike(like), Event.analysis_id.in_(names)))
    total = q.count()
    order = Event.start_time.asc() if sort == "asc" else Event.start_time.desc()
    items = q.order_by(order).offset((page - 1) * page_size).limit(page_size).all()
    return items, total


def zone_lookup(db: Session) -> dict[int, Zone]:
    return {z.id: z for z in db.query(Zone).all()}
