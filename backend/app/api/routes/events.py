from datetime import date, time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import media_url
from app.database.database import get_db
from app.database.models import Event
from app.database.schemas import ChannelResult, EventDetail, EventOut, EventPage, EventUpdate, MessageResponse
from app.services import notification_service, storage_service
from app.services.event_processor import regenerate_summary
from app.services.event_service import search_events
from app.services.pipeline import get_pipeline

router = APIRouter(prefix="/events", tags=["events"])


def to_out(ev: Event, detail: bool = False):
    model = EventDetail if detail else EventOut
    out = model.model_validate(ev)
    out.video_url = media_url(ev.video_path)
    out.snapshot_url = media_url(ev.snapshot_path)
    out.analysis_name = ev.analysis.original_name if ev.analysis else None
    return out


def _get(db: Session, event_id: int) -> Event:
    ev = db.get(Event, event_id)
    if ev is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Event {event_id} not found")
    return ev


@router.get("", response_model=EventPage, summary="Search / filter events")
def list_events(
    date_: date | None = Query(None, alias="date", description="Single day (YYYY-MM-DD)"),
    start_time: time | None = Query(None, description="HH:MM, with `date`"),
    end_time: time | None = Query(None, description="HH:MM, with `date`"),
    date_from: date | None = None, date_to: date | None = None,
    object_class: str | None = None, keyword: str | None = None,
    zone: str | None = Query(None, description="Zone name or id"),
    event_type: Literal["object_detection", "zone_violation", "loitering", "motion"] | None = None,
    min_duration: float | None = Query(None, ge=0), max_duration: float | None = Query(None, ge=0),
    status_: str | None = Query(None, alias="status"), protected: bool | None = None,
    analysis_id: int | None = Query(None, description="Only events from this uploaded video"),
    source: Literal["live", "video"] | None = Query(None, description="live camera or uploaded video"),
    page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=200),
    sort: Literal["asc", "desc"] = "desc",
    db: Session = Depends(get_db),
):
    items, total = search_events(
        db, day=date_, start_time=start_time, end_time=end_time, date_from=date_from, date_to=date_to,
        object_class=object_class, keyword=keyword, zone=zone, event_type=event_type,
        min_duration=min_duration, max_duration=max_duration, status=status_, protected=protected,
        analysis_id=analysis_id, source=source, page=page, page_size=page_size, sort=sort,
    )
    return EventPage(items=[to_out(e) for e in items], total=total, page=page, page_size=page_size)


@router.get("/{event_id}", response_model=EventDetail, responses={404: {"description": "Not found"}})
def get_event(event_id: int, db: Session = Depends(get_db)):
    return to_out(_get(db, event_id), detail=True)


@router.patch("/{event_id}", response_model=EventDetail, summary="Update event flags (e.g. protect from retention)")
def update_event(event_id: int, body: EventUpdate, db: Session = Depends(get_db)):
    ev = _get(db, event_id)
    if body.is_protected is not None:
        ev.is_protected = body.is_protected
    db.commit()
    db.refresh(ev)
    return to_out(ev, detail=True)


@router.delete("/{event_id}", response_model=MessageResponse, responses={409: {"description": "Still recording"}})
def delete_event(event_id: int, db: Session = Depends(get_db)):
    ev = _get(db, event_id)
    if get_pipeline().events.active_event_id == event_id or ev.status in ("recording", "processing"):
        raise HTTPException(status.HTTP_409_CONFLICT, "Event is still being recorded/processed")
    freed = storage_service.delete_event(db, ev)
    db.commit()
    return MessageResponse(message=f"Event {event_id} deleted ({freed / 1e6:.1f} MB freed)")


@router.get("/{event_id}/video", summary="Download the event MP4", response_class=FileResponse)
def download_video(event_id: int, db: Session = Depends(get_db)):
    ev = _get(db, event_id)
    path = storage_service.resolve(ev.video_path)
    if not path or not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Video not available")
    return FileResponse(path, media_type="video/mp4", filename=f"prevucam_event_{event_id}.mp4")


@router.get("/{event_id}/snapshot", summary="Event snapshot JPEG", response_class=FileResponse)
def get_snapshot(event_id: int, db: Session = Depends(get_db)):
    ev = _get(db, event_id)
    path = storage_service.resolve(ev.snapshot_path)
    if not path or not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Snapshot not available")
    return FileResponse(path, media_type="image/jpeg")


@router.post("/{event_id}/summary", response_model=EventDetail, summary="(Re)generate the AI summary")
def regenerate(event_id: int, use_gemini: bool | None = Query(None), db: Session = Depends(get_db)):
    _get(db, event_id)
    regenerate_summary(event_id, use_gemini)
    db.expire_all()
    return to_out(_get(db, event_id), detail=True)


@router.post("/{event_id}/notify", response_model=list[ChannelResult], summary="Send alerts for this event now")
def notify(event_id: int, db: Session = Depends(get_db)):
    _get(db, event_id)
    return notification_service.notify_event(event_id, force=True)
