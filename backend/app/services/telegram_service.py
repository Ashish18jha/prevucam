from pathlib import Path

import httpx

from app.core.config import settings as cfg
from app.utils.logger import get_logger

log = get_logger("telegram")

API = "https://api.telegram.org/bot{token}/{method}"


def is_configured() -> bool:
    return bool(cfg.TELEGRAM_BOT_TOKEN and cfg.TELEGRAM_CHAT_ID)


def send_alert(text: str, photo: Path | None = None, timeout: float = 15.0) -> str:
    """Send a message (with the snapshot when available). Raises on failure."""
    if not is_configured():
        raise RuntimeError("Telegram is not configured (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID)")
    caption = text[:1024]
    if photo and photo.exists():
        with photo.open("rb") as fh:
            resp = httpx.post(
                API.format(token=cfg.TELEGRAM_BOT_TOKEN, method="sendPhoto"),
                data={"chat_id": cfg.TELEGRAM_CHAT_ID, "caption": caption, "parse_mode": "HTML"},
                files={"photo": (photo.name, fh, "image/jpeg")}, timeout=timeout,
            )
    else:
        resp = httpx.post(
            API.format(token=cfg.TELEGRAM_BOT_TOKEN, method="sendMessage"),
            data={"chat_id": cfg.TELEGRAM_CHAT_ID, "text": text[:4096], "parse_mode": "HTML"}, timeout=timeout,
        )
    body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
    if resp.status_code != 200 or not body.get("ok"):
        raise RuntimeError(f"Telegram API error {resp.status_code}: {body.get('description', resp.text[:200])}")
    log.info("Telegram notification sent")
    return "sent"
