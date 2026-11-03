"""Time-bounded ring buffer holding the most recent N seconds of frames.

Frames are optionally JPEG-compressed so the memory footprint stays small on
edge devices (7 s @ 15 fps @ 640x480 ≈ 3 MB compressed vs ≈ 97 MB raw). The
deque has a hard `maxlen`, so memory is bounded even if timestamps misbehave.
"""
from __future__ import annotations

import threading
from collections import deque

import numpy as np

from app.utils.image_utils import decode_jpeg, encode_jpeg


class CircularFrameBuffer:
    def __init__(self, seconds: float = 7.0, fps: float = 15.0, jpeg_quality: int = 85, slack: float = 1.5) -> None:
        self.seconds = float(seconds)
        self.fps = float(fps)
        self.jpeg_quality = jpeg_quality
        self._frames: deque[tuple[float, object]] = deque(maxlen=self._capacity(slack))
        self._slack = slack
        self._lock = threading.Lock()

    def _capacity(self, slack: float) -> int:
        return max(1, int(self.seconds * self.fps * slack) + 1)

    def resize(self, seconds: float, fps: float | None = None) -> None:
        with self._lock:
            self.seconds = float(seconds)
            if fps:
                self.fps = float(fps)
            self._frames = deque(self._frames, maxlen=self._capacity(self._slack))

    def push(self, ts: float, frame: np.ndarray) -> None:
        payload = encode_jpeg(frame, self.jpeg_quality) if self.jpeg_quality else frame.copy()
        with self._lock:
            self._frames.append((ts, payload))
            # time-based eviction: keep only frames inside the window ending at `ts`
            while self._frames and ts - self._frames[0][0] > self.seconds:
                self._frames.popleft()

    def get_frames(self, before_ts: float | None = None) -> list[tuple[float, np.ndarray]]:
        """Decoded (ts, frame) pairs in chronological order, optionally only those with ts < before_ts."""
        with self._lock:
            items = list(self._frames)
        out = []
        for ts, payload in items:
            if before_ts is not None and ts >= before_ts:
                continue
            out.append((ts, decode_jpeg(payload) if isinstance(payload, bytes) else payload))
        return out

    def clear(self) -> None:
        with self._lock:
            self._frames.clear()

    def __len__(self) -> int:
        return len(self._frames)

    @property
    def duration(self) -> float:
        with self._lock:
            if len(self._frames) < 2:
                return 0.0
            return self._frames[-1][0] - self._frames[0][0]

    @property
    def memory_bytes(self) -> int:
        with self._lock:
            return sum(len(p) if isinstance(p, bytes) else p.nbytes for _, p in self._frames)
