"""Test configuration: isolated storage/DB, no real secrets, and a deterministic fake detector."""
import os
import tempfile
from datetime import datetime

_TMP = tempfile.mkdtemp(prefix="prevucam_test_")
os.environ["STORAGE_PATH"] = _TMP
os.environ["DATABASE_URL"] = ""
os.environ["CAMERA_AUTOSTART"] = "false"
os.environ["API_KEY"] = ""
for secret in ("GEMINI_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "SMTP_HOST", "SMTP_USERNAME",
               "SMTP_PASSWORD", "ALERT_EMAIL"):
    os.environ[secret] = ""

import cv2  # noqa: E402
import numpy as np  # noqa: E402
import pytest  # noqa: E402

from app.database.database import Base, engine, init_db  # noqa: E402
from app.services.object_detector import COCO_FALLBACK, Detection  # noqa: E402
from app.services.settings_service import settings_service  # noqa: E402

init_db()

W, H = 640, 480


class FakeDetector:
    """Finds pure-white rectangles (person) and pure-blue rectangles (dog) in a frame."""

    def __init__(self) -> None:
        self.confidence = 0.5
        self.error = None
        self._model = object()
        self._load_attempted = True
        self.model_path = "fake"
        self.imgsz = 416
        self.calls = 0

    available = True
    class_names = list(COCO_FALLBACK)

    def reload(self) -> bool:
        return True

    def detect(self, frame, confidence=None, frame_index=None, timestamp=None):
        self.calls += 1
        out = []
        for cls, color in (("person", (255, 255, 255)), ("dog", (255, 0, 0))):
            c = np.array(color, dtype=int)  # tolerant: frames may have been through video compression
            mask = cv2.inRange(frame, np.clip(c - 45, 0, 255).astype(np.uint8), np.clip(c + 45, 0, 255).astype(np.uint8))
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for c in contours:
                x, y, w, h = cv2.boundingRect(c)
                if w * h > 200:
                    out.append(Detection(cls, 0.9, [float(x), float(y), float(x + w), float(y + h)],
                                         timestamp or datetime.now(), frame_index))
        return out


def scene(person_x: int | None = None, dog_x: int | None = None, noise_seed: int = 0) -> np.ndarray:
    img = np.full((H, W, 3), 60, np.uint8)
    cv2.rectangle(img, (0, 340), (W, H), (80, 80, 80), -1)
    if person_x is not None:
        cv2.rectangle(img, (person_x, 200), (person_x + 50, 430), (255, 255, 255), -1)
    if dog_x is not None:
        cv2.rectangle(img, (dog_x, 380), (dog_x + 70, 430), (255, 0, 0), -1)
    return img


@pytest.fixture(autouse=True)
def clean_state():
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())
    settings_service.reset()
    settings_service.update({"pre_event_seconds": 7, "post_event_seconds": 7, "event_cooldown_seconds": 0,
                             "detection_interval": 1, "loitering_seconds": 20})
    yield


@pytest.fixture
def fake_detector():
    return FakeDetector()


@pytest.fixture
def storage_dir():
    from app.core.config import settings
    return settings.storage_dir
