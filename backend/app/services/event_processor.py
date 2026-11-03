"""Post-recording steps for a finished event: summary, then notifications."""
from app.database.database import session_scope
from app.database.models import Event
from app.services import notification_service
from app.services.settings_service import settings_service
from app.services.summarizer import summarize
from app.utils.logger import get_logger

log = get_logger("processor")


def regenerate_summary(event_id: int, use_gemini: bool | None = None) -> Event:
    s = settings_service.get()
    with session_scope() as db:
        event = db.get(Event, event_id)
        if event is None:
            raise LookupError(f"Event {event_id} not found")
        text, source, ai_error = summarize(event, use_gemini=s["gemini_enabled"] if use_gemini is None else use_gemini)
        event.summary, event.summary_source, event.summary_error = text, source, ai_error
        log.info("Summary for event %d generated (%s)", event_id, source)
        return event


def process_event(event_id: int) -> None:
    try:
        regenerate_summary(event_id)
    except Exception as exc:
        log.exception("Summary for event %d failed: %s", event_id, exc)
    try:
        notification_service.notify_event(event_id)
    except Exception as exc:
        log.exception("Notifications for event %d failed: %s", event_id, exc)
