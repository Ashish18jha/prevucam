import logging
import logging.handlers
import sys

from app.core.config import settings

_configured = False


def setup_logging() -> None:
    global _configured
    if _configured:
        return
    log_dir = settings.subdir("logs")
    fmt = logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)s | %(message)s")

    root = logging.getLogger("prevucam")
    root.setLevel(settings.LOG_LEVEL.upper())
    root.propagate = False

    if hasattr(sys.stderr, "reconfigure"):  # Windows consoles: never fail on e.g. non-Latin file names
        try:
            sys.stderr.reconfigure(errors="replace")
        except Exception:
            pass
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)

    file_handler = logging.handlers.RotatingFileHandler(
        log_dir / "prevucam.log", maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)
    _configured = True


def get_logger(name: str) -> logging.Logger:
    setup_logging()
    return logging.getLogger(f"prevucam.{name}")
