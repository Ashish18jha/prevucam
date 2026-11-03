"""Background-subtraction motion detector used as a cheap gate before YOLO."""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np


@dataclass
class MotionResult:
    motion: bool
    area: int = 0
    boxes: list[list[int]] = field(default_factory=list)  # in full-frame pixel coordinates


class MotionDetector:
    def __init__(self, sensitivity: int = 60, min_area: int = 800, process_width: int = 320,
                 threshold: int | None = None) -> None:
        self.process_width = process_width
        self._avg: np.ndarray | None = None
        self.configure(sensitivity, min_area, threshold)

    def configure(self, sensitivity: int, min_area: int, threshold: int | None = None) -> None:
        self.sensitivity = int(np.clip(sensitivity, 1, 100))
        self.min_area = int(min_area)
        # sensitivity 100 -> delta 5, sensitivity 1 -> delta ~60
        self.threshold = threshold if threshold else int(round(60 - 0.55 * self.sensitivity))

    def reset(self) -> None:
        self._avg = None

    def detect(self, frame: np.ndarray) -> MotionResult:
        h, w = frame.shape[:2]
        scale = self.process_width / float(w) if w > self.process_width else 1.0
        small = cv2.resize(frame, (int(w * scale), int(h * scale))) if scale != 1.0 else frame
        gray = cv2.GaussianBlur(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY), (21, 21), 0)

        if self._avg is None:
            self._avg = gray.astype("float32")
            return MotionResult(False)

        cv2.accumulateWeighted(gray, self._avg, 0.05)
        delta = cv2.absdiff(gray, cv2.convertScaleAbs(self._avg))
        mask = cv2.threshold(delta, self.threshold, 255, cv2.THRESH_BINARY)[1]
        mask = cv2.dilate(mask, None, iterations=2)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        # min_area is defined at full resolution; convert to processing scale
        min_area_scaled = self.min_area * scale * scale
        boxes, total = [], 0
        for c in contours:
            area = cv2.contourArea(c)
            if area < min_area_scaled:
                continue
            x, y, bw, bh = cv2.boundingRect(c)
            inv = 1.0 / scale
            boxes.append([int(x * inv), int(y * inv), int((x + bw) * inv), int((y + bh) * inv)])
            total += int(area * inv * inv)
        return MotionResult(motion=bool(boxes), area=total, boxes=boxes)
