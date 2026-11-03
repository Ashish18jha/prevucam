from collections import Counter
from datetime import datetime, time, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database.models import Event
from app.services.object_detector import VEHICLE_CLASSES


def summary_counts(db: Session) -> dict:
    now = datetime.now()
    today = datetime.combine(now.date(), time.min)
    week = today - timedelta(days=today.weekday())
    q = db.query(Event)
    return {
        "events_today": q.filter(Event.start_time >= today).count(),
        "events_week": q.filter(Event.start_time >= week).count(),
        "events_total": q.count(),
        "person_detections": q.filter(Event.object_class == "person").count(),
        "vehicle_detections": q.filter(Event.object_class.in_(VEHICLE_CLASSES)).count(),
        "zone_violations": q.filter(Event.event_type == "zone_violation").count(),
        "loitering_events": q.filter(Event.event_type == "loitering").count(),
        "avg_duration": round(db.query(func.avg(Event.duration)).scalar() or 0.0, 1),
    }


def charts(db: Session, days: int = 7) -> dict:
    since = datetime.combine(datetime.now().date(), time.min) - timedelta(days=days - 1)
    rows = (db.query(Event.start_time, Event.object_class, Event.event_type, Event.zone_name)
            .filter(Event.start_time >= since).all())
    by_hour = Counter(r.start_time.hour for r in rows)
    by_day = Counter(r.start_time.strftime("%Y-%m-%d") for r in rows)
    day_labels = [(since + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days)]
    return {
        "by_hour": [{"label": f"{h:02d}:00", "count": by_hour.get(h, 0)} for h in range(24)],
        "by_object": [{"label": k, "count": v} for k, v in Counter(r.object_class or "unknown" for r in rows).most_common()],
        "by_type": [{"label": k, "count": v} for k, v in Counter(r.event_type for r in rows).most_common()],
        "by_zone": [{"label": k, "count": v} for k, v in Counter(r.zone_name or "No zone" for r in rows).most_common()],
        "by_day": [{"label": d, "count": by_day.get(d, 0)} for d in day_labels],
    }
