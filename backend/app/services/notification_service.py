"""Dispatches event alerts to every enabled channel independently.

A failure in one channel is logged and recorded but never prevents the other
channels (or the event itself) from completing.
"""
from __future__ import annotations

import html
from pathlib import Path

from app.core.config import settings as cfg
from app.database.database import session_scope
from app.database.models import Event, Notification
from app.services import email_service, telegram_service, twilio_service
from app.services.settings_service import settings_service
from app.services.summarizer import video_clock
from app.utils.logger import get_logger

log = get_logger("notify")

TITLES = {
    "object_detection": "{obj} Detected",
    "zone_violation": "Zone Violation – {zone}",
    "loitering": "Loitering – {zone}",
    "motion": "Motion Detected",
}


def _title(event: Event) -> str:
    obj = (event.object_class or "Object").title()
    return TITLES.get(event.event_type, "Event").format(obj=obj, zone=event.zone_name or "zone")


def _lines(event: Event) -> list[tuple[str, str]]:
    return [
        ("Event ID", str(event.id)),
        ("Type", event.event_type.replace("_", " ").title()),
        ("Object", event.object_class or "-"),
        ("Confidence", f"{event.confidence * 100:.0f}%" if event.confidence else "-"),
        ("Zone", event.zone_name or "-"),
        ("Time", event.start_time.strftime("%Y-%m-%d %H:%M:%S")),
        ("Duration", f"{event.duration:.0f}s"),
    ] + ([("Source", f"Video analysis #{event.analysis_id}"
                     + (f" – {event.analysis.original_name}" if event.analysis else "")),
          ("Video time", video_clock(event.video_offset))] if event.source == "video" else [])


def _channels_enabled(s: dict) -> dict[str, bool]:
    return {"twilio": s["twilio_enabled"], "telegram": s["telegram_enabled"], "email": s["email_enabled"]}


def twilio_body(event: Event) -> str:
    """Plain-text SMS/WhatsApp body (Twilio cannot attach a local snapshot without a public URL)."""
    lines = [
        "PreVuCam Alert", "",
        f"Event: {event.event_type.replace('_', ' ').title()}",
        f"Object: {(event.object_class or '-').title()}",
        f"Zone: {event.zone_name or '-'}",
        f"Confidence: {event.confidence * 100:.0f}%" if event.confidence else "Confidence: -",
        f"Time: {event.start_time.strftime('%I:%M %p').lstrip('0')}",
        f"Duration: {event.duration:.0f}s",
    ]
    if event.source == "video":
        lines.append(f"Source: video #{event.analysis_id} @ {video_clock(event.video_offset)}")
    lines += ["", "Summary:" if event.summary_source == "gemini" else "Summary (Gemini summary unavailable):",
              event.summary or "-", "", f"Event #{event.id}"]
    return "\n".join(lines)


def send_twilio(event: Event, snapshot: Path | None) -> str:
    return twilio_service.send_message(twilio_body(event))


def send_telegram(event: Event, snapshot: Path | None) -> str:
    text = f"🚨 <b>PreVuCam Alert – {html.escape(_title(event))}</b>\n"
    text += "\n".join(f"<b>{k}:</b> {html.escape(v)}" for k, v in _lines(event))
    if event.summary:
        label = "" if event.summary_source == "gemini" else "<i>AI summary unavailable – rule-based description:</i>\n"
        text += f"\n\n{label}{html.escape(event.summary)}"
    return telegram_service.send_alert(text, snapshot)


def send_email(event: Event, snapshot: Path | None) -> str:
    subject = f"PreVuCam Alert - {_title(event)}"
    body = "PreVuCam detected a new event.\n\n"
    body += "\n".join(f"{k:<11}: {v}" for k, v in _lines(event))
    heading = "AI summary" if event.summary_source == "gemini" else "AI summary unavailable. Rule-based description"
    body += f"\n\n{heading}:\n{event.summary or '-'}\n"
    if event.video_path:
        body += f"\nVideo: {event.video_path}\n"
    return email_service.send_alert(subject, body, snapshot)


# resolved at call time so services can be swapped/mocked
SENDERS = {"twilio": (lambda: twilio_service.is_configured(), lambda e, s: send_twilio(e, s)),
           "telegram": (lambda: telegram_service.is_configured(), lambda e, s: send_telegram(e, s)),
           "email": (lambda: email_service.is_configured(), lambda e, s: send_email(e, s))}


def notify_event(event_id: int, force: bool = False, channels: list[str] | None = None) -> list[dict]:
    """Send alerts for an event. `force` ignores the per-type filter and enable toggles."""
    s = settings_service.get()
    with session_scope() as db:
        event = db.get(Event, event_id)
        if event is None:
            raise LookupError(f"Event {event_id} not found")
        if not force and event.event_type not in s["notify_event_types"]:
            event.notification_status = "skipped"
            return []
        snapshot = cfg.storage_dir / event.snapshot_path if event.snapshot_path else None
        enabled = _channels_enabled(s)
        results = []
        for channel, (configured, sender) in SENDERS.items():
            if channels and channel not in channels:
                continue
            if not force and not enabled[channel]:
                status, detail = "skipped", "disabled in settings"
            elif not configured():
                status, detail = "skipped", "not configured"
            else:
                try:
                    sender(event, snapshot)
                    status, detail = "sent", None
                except Exception as exc:
                    status, detail = "failed", str(exc)[:500]
                    log.error("%s notification for event %d failed: %s", channel, event_id, exc)
            db.add(Notification(event_id=event_id, channel=channel, status=status, detail=detail))
            results.append({"channel": channel, "status": status, "detail": detail})

        statuses = {r["status"] for r in results}
        if "sent" in statuses:
            event.notification_status = "partial" if "failed" in statuses else "sent"
        elif "failed" in statuses:
            event.notification_status = "failed"
        else:
            event.notification_status = "skipped"
        return results


def send_test(channel: str) -> list[dict]:
    results = []
    targets = ["twilio", "telegram", "email"] if channel == "all" else [channel]
    for ch in targets:
        try:
            if ch == "twilio":
                twilio_service.send_message("PreVuCam test notification\nTwilio alerts are working.")
            elif ch == "telegram":
                telegram_service.send_alert("✅ <b>PreVuCam test notification</b>\nTelegram alerts are working.")
            else:
                email_service.send_alert("PreVuCam test notification", "Email alerts are working.")
            results.append({"channel": ch, "status": "sent", "detail": None})
        except Exception as exc:
            results.append({"channel": ch, "status": "failed", "detail": str(exc)[:500]})
        with session_scope() as db:
            r = results[-1]
            db.add(Notification(event_id=None, channel=ch, status=r["status"], detail=r["detail"] or "test"))
    return results
