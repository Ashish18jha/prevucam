from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.config import settings as cfg
from app.database.database import get_db
from app.database.models import Notification
from app.database.schemas import ChannelResult, NotificationConfigStatus, NotificationOut, NotificationTestRequest
from app.services import email_service, notification_service, telegram_service, twilio_service
from app.services.settings_service import settings_service

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _mask(email: str) -> str | None:
    if not email or "@" not in email:
        return email or None
    name, domain = email.split("@", 1)
    return f"{name[:2]}***@{domain}"


@router.get("/status", response_model=NotificationConfigStatus,
            summary="Which channels are configured (via .env) and enabled (via settings)")
def config_status():
    s = settings_service.get()
    return NotificationConfigStatus(
        twilio_configured=twilio_service.is_configured(), twilio_enabled=s["twilio_enabled"],
        twilio_to=twilio_service.masked_to(),
        telegram_configured=telegram_service.is_configured(), telegram_enabled=s["telegram_enabled"],
        email_configured=email_service.is_configured(), email_enabled=s["email_enabled"],
        gemini_configured=bool(cfg.GEMINI_API_KEY), gemini_enabled=s["gemini_enabled"],
        gemini_model=cfg.GEMINI_MODEL, alert_email=_mask(cfg.ALERT_EMAIL),
        notify_event_types=s["notify_event_types"],
    )


@router.post("/test", response_model=list[ChannelResult], summary="Send a test notification")
def test(body: NotificationTestRequest):
    return notification_service.send_test(body.channel)


@router.get("", response_model=list[NotificationOut], summary="Notification history")
def history(limit: int = Query(100, ge=1, le=1000), channel: str | None = None, db: Session = Depends(get_db)):
    q = db.query(Notification)
    if channel:
        q = q.filter(Notification.channel == channel)
    return q.order_by(Notification.created_at.desc()).limit(limit).all()
