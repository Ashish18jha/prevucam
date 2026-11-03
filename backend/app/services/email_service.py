import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path

from app.core.config import settings as cfg
from app.utils.logger import get_logger

log = get_logger("email")


def is_configured() -> bool:
    return bool(cfg.SMTP_HOST and cfg.ALERT_EMAIL)


def send_alert(subject: str, body: str, attachment: Path | None = None, timeout: float = 20.0) -> str:
    """Send an alert email with an optional JPEG attachment. Raises on failure."""
    if not is_configured():
        raise RuntimeError("Email is not configured (SMTP_HOST / ALERT_EMAIL)")
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg.SMTP_FROM or cfg.SMTP_USERNAME or f"prevucam@{cfg.SMTP_HOST}"
    msg["To"] = cfg.ALERT_EMAIL
    msg.set_content(body)
    if attachment and attachment.exists():
        msg.add_attachment(attachment.read_bytes(), maintype="image", subtype="jpeg", filename=attachment.name)

    context = ssl.create_default_context()
    if cfg.SMTP_USE_SSL or cfg.SMTP_PORT == 465:
        server: smtplib.SMTP = smtplib.SMTP_SSL(cfg.SMTP_HOST, cfg.SMTP_PORT, timeout=timeout, context=context)
    else:
        server = smtplib.SMTP(cfg.SMTP_HOST, cfg.SMTP_PORT, timeout=timeout)
    try:
        server.ehlo()
        if not (cfg.SMTP_USE_SSL or cfg.SMTP_PORT == 465) and server.has_extn("starttls"):
            server.starttls(context=context)
            server.ehlo()
        if cfg.SMTP_USERNAME and cfg.SMTP_PASSWORD:
            server.login(cfg.SMTP_USERNAME, cfg.SMTP_PASSWORD)
        server.send_message(msg)
    finally:
        try:
            server.quit()
        except Exception:
            pass
    log.info("Email notification sent to %s", cfg.ALERT_EMAIL)
    return "sent"
