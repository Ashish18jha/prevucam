"""YOLOv8 object detection wrapper (Ultralytics).

The model is loaded lazily on first use. If the weights or the library are
missing the detector reports itself unavailable instead of crashing the app:
the camera, motion detection and (motion-triggered) recording keep working.
"""
from __future__ import annotations

import threading
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

from app.core.config import settings as cfg
from app.utils.logger import get_logger

log = get_logger("detector")

COCO_FALLBACK = [
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck", "boat",
    "traffic light", "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat", "dog",
    "horse", "sheep", "cow", "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella",
    "handbag", "tie", "suitcase", "frisbee", "skis", "snowboard", "sports ball", "kite",
    "baseball bat", "baseball glove", "skateboard", "surfboard", "tennis racket", "bottle",
    "wine glass", "cup", "fork", "knife", "spoon", "bowl", "banana", "apple", "sandwich", "orange",
    "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair", "couch", "potted plant",
    "bed", "dining table", "toilet", "tv", "laptop", "mouse", "remote", "keyboard", "cell phone",
    "microwave", "oven", "toaster", "sink", "refrigerator", "book", "clock", "vase", "scissors",
    "teddy bear", "hair drier", "toothbrush",
]
VEHICLE_CLASSES = {"car", "motorcycle", "bus", "truck", "bicycle"}


@dataclass
class Detection:
    cls: str
    confidence: float
    bbox: list[float]  # x1, y1, x2, y2 (pixels)
    timestamp: datetime
    frame: int | None = None  # source frame number (recorded-video mode)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["class"] = d.pop("cls")
        d["timestamp"] = self.timestamp.isoformat()
        return d


class ObjectDetector:
    def __init__(self, model_path: str | None = None, imgsz: int | None = None) -> None:
        self.model_path = model_path or cfg.MODEL_PATH
        self.imgsz = imgsz or cfg.YOLO_IMGSZ
        self.confidence = cfg.YOLO_CONFIDENCE
        self._model = None
        self._lock = threading.Lock()
        self.error: str | None = None
        self._load_attempted = False

    @property
    def available(self) -> bool:
        self._ensure_loaded()
        return self._model is not None

    @property
    def class_names(self) -> list[str]:
        if self._model is not None:
            return [self._model.names[i] for i in sorted(self._model.names)]
        return list(COCO_FALLBACK)

    def _ensure_loaded(self) -> None:
        if self._model is not None or self._load_attempted:
            return
        with self._lock:
            if self._model is not None or self._load_attempted:
                return
            self._load_attempted = True
            try:
                from ultralytics import YOLO

                path = Path(self.model_path)
                if not path.exists():
                    if not path.name.startswith("yolo") or not path.parent.exists():
                        raise FileNotFoundError(f"YOLO weights not found at {path}")
                    # official weights (e.g. yolov8n.pt): let Ultralytics download them, then keep a copy in models/
                    log.info("Weights missing at %s – downloading %s", path, path.name)
                    model = YOLO(path.name)
                    downloaded = Path(getattr(model, "ckpt_path", "") or path.name)
                    if downloaded.exists() and downloaded.resolve() != path.resolve():
                        downloaded.replace(path)
                self._model = YOLO(str(path))
                self._model(np.zeros((self.imgsz, self.imgsz, 3), np.uint8), imgsz=self.imgsz, verbose=False)
                self.error = None
                log.info("YOLO model loaded: %s (imgsz=%d)", path.name, self.imgsz)
            except Exception as exc:
                self.error = f"YOLO unavailable: {exc}"
                log.error(self.error)

    def reload(self) -> bool:
        with self._lock:
            self._model, self._load_attempted = None, False
        return self.available

    def detect(self, frame: np.ndarray, confidence: float | None = None, frame_index: int | None = None,
               timestamp: datetime | None = None) -> list[Detection]:
        self._ensure_loaded()
        if self._model is None:
            return []
        conf = confidence if confidence is not None else self.confidence
        with self._lock:
            results = self._model(frame, imgsz=self.imgsz, conf=conf, verbose=False)
        now = timestamp or datetime.now()
        out: list[Detection] = []
        for r in results:
            if r.boxes is None:
                continue
            for box, score, cls_id in zip(r.boxes.xyxy.tolist(), r.boxes.conf.tolist(), r.boxes.cls.tolist()):
                out.append(Detection(
                    cls=self._model.names[int(cls_id)],
                    confidence=round(float(score), 3),
                    bbox=[round(v, 1) for v in box],
                    timestamp=now, frame=frame_index,
                ))
        return out


def filter_relevant(detections: list[Detection], relevant: list[str] | set[str]) -> list[Detection]:
    wanted = {r.lower() for r in relevant}
    return [d for d in detections if d.cls.lower() in wanted]
