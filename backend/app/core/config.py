"""Centralised configuration.

Every tunable value lives here. Values come from environment variables / `.env`
and act as *defaults*; runtime-editable settings (thresholds, relevant objects,
etc.) are persisted in the database by `SettingsService` and override these.
Secrets (API keys, tokens, passwords) are only ever read from the environment.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(PROJECT_ROOT / ".env"), str(BACKEND_DIR / ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Application --------------------------------------------------------
    APP_NAME: str = "PreVuCam"
    APP_VERSION: str = "1.0.0"
    LOG_LEVEL: str = "INFO"
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"
    API_KEY: str = ""  # optional; when set, every /api request needs X-API-Key

    # --- Database / storage -------------------------------------------------
    DATABASE_URL: str = ""  # default -> sqlite file inside STORAGE_PATH
    STORAGE_PATH: str = str(PROJECT_ROOT / "storage")
    MODEL_PATH: str = str(PROJECT_ROOT / "models" / "yolov8n.pt")

    # --- Camera -------------------------------------------------------------
    # browser (the webcam of the computer viewing the dashboard) | webcam (server-side) | rtsp | file | picamera
    CAMERA_SOURCE_TYPE: str = "browser"
    CAMERA_SOURCE: str = "0"  # webcam index, RTSP url or video path
    CAMERA_WIDTH: int = 640
    CAMERA_HEIGHT: int = 480
    CAMERA_FPS: int = 15
    CAMERA_AUTOSTART: bool = False
    CAMERA_LOOP_FILE: bool = True
    CAMERA_RECONNECT_SECONDS: float = 3.0

    # --- Motion -------------------------------------------------------------
    MOTION_SENSITIVITY: int = 60  # 1-100, higher = more sensitive
    MOTION_MIN_AREA: int = 800  # px^2 at processing resolution
    MOTION_THRESHOLD: int = 25  # pixel delta threshold (derived from sensitivity if 0)
    MOTION_PROCESS_WIDTH: int = 320

    # --- Detection ----------------------------------------------------------
    YOLO_CONFIDENCE: float = 0.5
    YOLO_IMGSZ: int = 416
    DETECTION_INTERVAL: int = 3  # run YOLO every N frames when motion/tracks exist
    RELEVANT_OBJECTS: str = "person,car,motorcycle,bicycle,bus,truck"

    # --- Events / recording -------------------------------------------------
    PRE_EVENT_SECONDS: float = 7.0
    POST_EVENT_SECONDS: float = 7.0
    MAX_EVENT_SECONDS: float = 120.0
    EVENT_COOLDOWN_SECONDS: float = 2.0
    MIN_TRACK_HITS: int = 2
    BUFFER_JPEG_QUALITY: int = 85  # frames are JPEG-compressed in the ring buffer; 0 = raw

    # --- Recorded video analysis ---------------------------------------------
    MAX_UPLOAD_MB: int = 2048
    ANALYSIS_MAX_WIDTH: int = 1280  # frames wider than this are downscaled for analysis and event clips

    # --- Loitering ----------------------------------------------------------
    LOITERING_SECONDS: float = 20.0
    LOITERING_CLASSES: str = "person"

    # --- Storage policy -----------------------------------------------------
    MAX_STORAGE_GB: float = 10.0
    RETENTION_DAYS: int = 30
    AUTO_DELETE_ENABLED: bool = False

    # --- Gemini -------------------------------------------------------------
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.5-flash"
    GEMINI_TIMEOUT: float = 20.0

    # --- Twilio (SMS / WhatsApp alerts) --------------------------------------
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_FROM_NUMBER: str = ""  # +14155550100, or whatsapp:+14155238886 for WhatsApp
    TWILIO_TO_NUMBER: str = ""
    TWILIO_API_BASE: str = "https://api.twilio.com"

    # --- Telegram -----------------------------------------------------------
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""

    # --- Email --------------------------------------------------------------
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_USE_SSL: bool = False
    SMTP_FROM: str = ""
    ALERT_EMAIL: str = ""

    def model_post_init(self, __context) -> None:
        _apply_api_keys_file(self)
        # relative paths in .env are relative to backend/, independent of the working directory
        for name in ("STORAGE_PATH", "MODEL_PATH"):
            p = Path(getattr(self, name))
            if not p.is_absolute():
                setattr(self, name, str((BACKEND_DIR / p).resolve()))

    # --- Derived helpers ----------------------------------------------------
    @property
    def storage_dir(self) -> Path:
        return Path(self.STORAGE_PATH).resolve()

    @property
    def database_url(self) -> str:
        if self.DATABASE_URL:
            return self.DATABASE_URL
        return f"sqlite:///{self.storage_dir / 'prevucam.db'}"

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    def subdir(self, name: str) -> Path:
        path = self.storage_dir / name
        path.mkdir(parents=True, exist_ok=True)
        return path


API_KEYS_FILE = BACKEND_DIR / "config" / "api_keys.py"
API_KEY_NAMES = ("GEMINI_API_KEY", "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER", "TWILIO_TO_NUMBER")


def _is_placeholder(value: str) -> bool:
    v = value.strip()
    return not v or (v.upper().startswith("PASTE_YOUR") and v.upper().endswith("_HERE"))


def _apply_api_keys_file(s: "Settings") -> None:
    """Credentials typed into backend/config/api_keys.py take precedence over .env / environment.

    Empty strings and the "PASTE_YOUR_..._HERE" placeholders are ignored, so an untouched file
    simply leaves Gemini/Twilio unconfigured. Values are never logged.
    """
    if not API_KEYS_FILE.exists():
        return
    import importlib.util

    try:
        spec = importlib.util.spec_from_file_location("prevucam_api_keys", API_KEYS_FILE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception as exc:  # a typo in the file must not stop the server
        print(f"[PreVuCam] warning: could not read {API_KEYS_FILE.name}: {type(exc).__name__}")
        return
    for name in API_KEY_NAMES:
        value = getattr(module, name, "")
        if isinstance(value, str) and not _is_placeholder(value):
            setattr(s, name, value.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
