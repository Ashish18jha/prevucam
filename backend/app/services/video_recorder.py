"""Single-file event recorder.

Pre-event frames (from the circular buffer), live event frames and post-event
frames are all written through the *same* writer, so the output is one
continuous MP4. Frames are placed on a constant-frame-rate timeline using
their source timestamps (duplicating or dropping as needed), which keeps the
video's playback duration equal to real elapsed time even when the capture
rate fluctuates.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from app.utils.logger import get_logger
from app.utils.video_utils import finalize_mp4, open_writer

log = get_logger("recorder")

MAX_GAP_SECONDS = 2.0  # never pad more than this when the source stalls


class EventRecorder:
    def __init__(self, raw_path: Path, fps: float, size: tuple[int, int]) -> None:
        self.raw_path = raw_path
        self.fps = float(fps)
        self.size = size
        self._writer = None
        self._last: np.ndarray | None = None
        self._next_ts: float | None = None
        self.first_ts: float | None = None
        self._slot_base = 0.0
        self._slot = 0
        self.last_ts: float | None = None
        self.frames_written = 0
        self.pre_frames = 0
        self.closed = False

    def start(self, pre_frames: list[tuple[float, np.ndarray]]) -> None:
        self._writer = open_writer(self.raw_path, self.fps, self.size)
        for ts, frame in pre_frames:
            self.write(ts, frame)
        self.pre_frames = len(pre_frames)
        log.info("Recording started: %s (%d pre-event frames, %.1fs)", self.raw_path.name,
                 len(pre_frames), (pre_frames[-1][0] - pre_frames[0][0]) if len(pre_frames) > 1 else 0.0)

    def write(self, ts: float, frame: np.ndarray) -> None:
        if self.closed or self._writer is None:
            return
        if self.last_ts is not None and ts <= self.last_ts:
            return  # out-of-order / duplicate timestamp
        if self._last is None:
            self.first_ts, self._next_ts, self._slot_base, self._slot = ts, ts, ts, 0
        else:
            # emit the held frame for every output slot before `ts` (integer slot math – no float drift)
            limit = ts if ts - self._next_ts <= MAX_GAP_SECONDS else self._next_ts + MAX_GAP_SECONDS
            while self._next_ts < limit - 1e-6:
                self._writer.write(self._last)
                self.frames_written += 1
                self._slot += 1
                self._next_ts = self._slot_base + self._slot / self.fps
            if self._next_ts < ts - 1e-6:  # stall was clipped – resync the output clock
                self._slot_base, self._slot, self._next_ts = ts, 0, ts
        self._last = frame
        self.last_ts = ts

    @property
    def duration(self) -> float:
        return self.frames_written / self.fps if self.fps else 0.0

    def close(self, final_path: Path) -> Path:
        """Flush, release and convert to browser-playable H.264. Returns the final path."""
        if self.closed:
            return final_path
        self.closed = True
        if self._writer is not None:
            if self._last is not None:
                self._writer.write(self._last)
                self.frames_written += 1
            self._writer.release()
        out = finalize_mp4(self.raw_path, final_path)
        log.info("Recording completed: %s (%d frames, %.1fs)", out.name, self.frames_written, self.duration)
        return out

    def abort(self) -> None:
        self.closed = True
        if self._writer is not None:
            self._writer.release()
        self.raw_path.unlink(missing_ok=True)
