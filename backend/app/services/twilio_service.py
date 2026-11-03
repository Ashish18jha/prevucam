"""Twilio SMS / WhatsApp alerts via the Twilio REST API (no SDK needed).

Credentials come from backend/config/api_keys.py or .env and are only ever used here,
on the backend. They are never logged and never returned by the API.
"""
from __future__ import annotations

import httpx

from app.core.config import settings as cfg
from app.utils.logger import get_logger

log = get_logger("twilio")

MAX_BODY = 1500  # Twilio concatenates up to 1600 chars


def is_configured() -> bool:
    return bool(cfg.TWILIO_ACCOUNT_SID and cfg.TWILIO_AUTH_TOKEN and cfg.TWILIO_FROM_NUMBER and cfg.TWILIO_TO_NUMBER)


def masked_to() -> str | None:
    n = cfg.TWILIO_TO_NUMBER
    if not n:
        return None
    digits = n.split(":")[-1]
    return f"{n.split(':')[0] + ':' if ':' in n else ''}{digits[:3]}•••{digits[-2:]}"


def send_message(body: str, timeout: float = 15.0) -> str:
    """Send one SMS/WhatsApp message. Returns the Twilio message SID. Raises on failure."""
    if not is_configured():
        raise RuntimeError("Twilio is not configured (TWILIO_ACCOUNT_SID / AUTH_TOKEN / FROM_NUMBER / TO_NUMBER)")
    url = f"{cfg.TWILIO_API_BASE.rstrip('/')}/2010-04-01/Accounts/{cfg.TWILIO_ACCOUNT_SID}/Messages.json"
    try:
        resp = httpx.post(url, auth=(cfg.TWILIO_ACCOUNT_SID, cfg.TWILIO_AUTH_TOKEN), timeout=timeout,
                          data={"From": cfg.TWILIO_FROM_NUMBER, "To": cfg.TWILIO_TO_NUMBER, "Body": body[:MAX_BODY]})
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Twilio request failed: {type(exc).__name__}") from None  # no URL/credentials in messages
    try:
        data = resp.json()
    except ValueError:
        data = {}
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Twilio error {resp.status_code}: {data.get('message') or resp.reason_phrase}"
                           + (f" (code {data['code']})" if data.get("code") else ""))
    sid = data.get("sid", "")
    log.info("Twilio notification sent (%s)", sid or "no sid")
    return sid
