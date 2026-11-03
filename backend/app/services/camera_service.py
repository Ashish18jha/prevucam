"""Camera / video input.

Supported sources
-----------------
webcam     USB / built-in camera via OpenCV (source = device index)
rtsp       IP camera stream (source = rtsp://... or http://... URL)
file       video file, optionally looped – used for test mode / uploaded clips
picamera   Raspberry Pi camera via picamera2 (Pi only; isolated in PiCameraSource)
browser    the user's real webcam, captured in the web UI (getUserMedia) and streamed over /ws/webcam

Every frame is delivered as a `Frame` carrying a *source clock* timestamp
(`ts`, seconds). For live sources that is wall-clock monotonic time; for video
files it is media time, so pre/post-event windows are exact even if the host
cannot process the file in real time.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from app.core.config import settings as cfg
from app.utils.image_utils import resize_to
from app.utils.logger import get_logger

log = get_logger("camera")


@dataclass
class Frame:
    image: np.ndarray
    ts: float
    wall: datetime = field(default_factory=datetime.now)
    index: int = 0


class SourceEnded(Exception):
    """Raised by a source when a non-looping video file is exhausted."""


class SourceStopped(Exception):
    """Raised by a blocking source when the camera is being stopped (normal shutdown, not an error)."""


class FrameSource:
    realtime: bool = True

    def open(self) -> None: ...
    def read(self) -> tuple[np.ndarray, float]: ...
    def close(self) -> None: ...
    def describe(self) -> str: return self.__class__.__name__


class OpenCVSource(FrameSource):
    def __init__(self, source: str | int, is_file: bool = False, loop: bool = True, pace: bool = True):
        self.source = source
        self.is_file = is_file
        self.loop = loop
        self.realtime = pace
        self.cap: cv2.VideoCapture | None = None
        self.fps = float(cfg.CAMERA_FPS)
        self._idx = 0
        self._time_base = 0.0
        self._pace_start = 0.0

    def open(self) -> None:
        if self.is_file and not Path(str(self.source)).exists():
            raise FileNotFoundError(f"Video file not found: {self.source}")
        src = int(self.source) if isinstance(self.source, str) and self.source.isdigit() else self.source
        self.cap = cv2.VideoCapture(src)
        if not self.cap.isOpened():
            raise ConnectionError(f"Unable to open video source: {self.source}")
        if not self.is_file:
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, cfg.CAMERA_WIDTH)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, cfg.CAMERA_HEIGHT)
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        fps = self.cap.get(cv2.CAP_PROP_FPS)
        if self.is_file and fps and 0 < fps <= 240:
            self.fps = float(fps)
        self._idx = 0
        self._pace_start = time.monotonic()

    def read(self) -> tuple[np.ndarray, float]:
        assert self.cap is not None
        ok, frame = self.cap.read()
        if not ok or frame is None:
            if self.is_file:
                if not self.loop:
                    raise SourceEnded("End of video file")
                self._time_base += self._idx / self.fps + 1.0 / self.fps
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                self._idx = 0
                self._pace_start = time.monotonic()
                ok, frame = self.cap.read()
                if not ok:
                    raise ConnectionError("Video file could not be rewound")
            else:
                raise ConnectionError("Camera stopped delivering frames")
        if not self.is_file:
            return frame, time.monotonic()
        ts = self._time_base + self._idx / self.fps
        if self.realtime:
            delay = (self._pace_start + self._idx / self.fps) - time.monotonic()
            if delay > 0:
                time.sleep(delay)
        self._idx += 1
        return frame, ts

    def close(self) -> None:
        if self.cap is not None:
            self.cap.release()
            self.cap = None

    def describe(self) -> str:
        return f"{'file' if self.is_file else 'stream'}:{self.source}"


class PiCameraSource(FrameSource):
    """Raspberry Pi camera (CSI) through picamera2. Only usable on a Pi."""

    def __init__(self) -> None:
        self.cam = None

    def open(self) -> None:
        try:
            from picamera2 import Picamera2  # type: ignore
        except ImportError as exc:
            raise ConnectionError("picamera2 is not installed – Raspberry Pi camera unavailable") from exc
        self.cam = Picamera2()
        config = self.cam.create_video_configuration(
            main={"size": (cfg.CAMERA_WIDTH, cfg.CAMERA_HEIGHT), "format": "RGB888"}
        )
        self.cam.configure(config)
        self.cam.start()
        self._interval = 1.0 / cfg.CAMERA_FPS
        self._last = 0.0

    def read(self) -> tuple[np.ndarray, float]:
        wait = self._last + self._interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        frame = self.cam.capture_array()  # RGB888 in picamera2 is BGR byte order
        self._last = time.monotonic()
        return frame, self._last

    def close(self) -> None:
        if self.cam is not None:
            try:
                self.cam.stop()
                self.cam.close()
            finally:
                self.cam = None


class BrowserFrameInbox:
    """Hand-off point between the browser webcam WebSocket and the capture thread.

    The browser grabs frames with getUserMedia, encodes them as JPEG and sends them over
    /ws/webcam. Only the newest frame is kept (a slot of size 1), so memory stays bounded and
    a slow pipeline never builds up latency: older frames are simply replaced.
    """

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._frame: tuple[int, np.ndarray, float] | None = None
        self._seq = 0
        self.connected = False
        self.label = ""
        self.last_push = 0.0
        self.session = 0  # increments for every browser connection (used to ignore stale disconnects)

    def push(self, image: np.ndarray) -> int:
        with self._cond:
            self._seq += 1
            self._frame = (self._seq, image, time.monotonic())
            self.last_push = time.monotonic()
            self._cond.notify_all()
            return self._seq

    def take(self, timeout: float) -> tuple[int, np.ndarray, float] | None:
        with self._cond:
            if self._frame is None:
                self._cond.wait(timeout)
            frame, self._frame = self._frame, None
            return frame

    def clear(self) -> None:
        with self._cond:
            self._frame = None


browser_inbox = BrowserFrameInbox()


class BrowserSource(FrameSource):
    """The user's real webcam, captured in the browser and streamed to the backend frame by frame."""

    STALL_SECONDS = 5.0

    def __init__(self) -> None:
        self._waiting_since = 0.0
        self.stop_event: threading.Event | None = None  # set by CameraService so stop() is never delayed

    def open(self) -> None:
        browser_inbox.clear()
        self._waiting_since = time.monotonic()

    def read(self) -> tuple[np.ndarray, float]:
        while True:
            item = browser_inbox.take(timeout=0.5)
            if item is not None:
                _, image, ts = item
                self._waiting_since = time.monotonic()
                return image, ts
            if time.monotonic() - self._waiting_since > self.STALL_SECONDS:
                self._waiting_since = time.monotonic()
                raise ConnectionError("Waiting for webcam frames from the browser")
            if self.stop_event is not None and self.stop_event.is_set():
                raise SourceStopped()

    def describe(self) -> str:
        return f"browser webcam{f' ({browser_inbox.label})' if browser_inbox.label else ''}"


def build_source(source_type: str, source: str, loop: bool, pace: bool = True) -> FrameSource:
    if source_type == "webcam":
        return OpenCVSource(source or "0")
    if source_type == "rtsp":
        if not source:
            raise ValueError("RTSP source requires a URL")
        return OpenCVSource(source)
    if source_type == "file":
        path = Path(source)
        if not path.is_absolute() and not path.exists():
            path = cfg.subdir("uploads") / source
        return OpenCVSource(str(path), is_file=True, loop=loop, pace=pace)
    if source_type == "picamera":
        return PiCameraSource()
    if source_type == "browser":
        return BrowserSource()
    raise ValueError(f"Unknown source type: {source_type}")


class CameraService:
    def __init__(self) -> None:
        # "simulated" was the old default in .env files; there is no simulated camera any more
        self.source_type = "browser" if cfg.CAMERA_SOURCE_TYPE == "simulated" else cfg.CAMERA_SOURCE_TYPE
        self.source = cfg.CAMERA_SOURCE
        self.loop = cfg.CAMERA_LOOP_FILE
        self.pace = True
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._latest: Frame | None = None
        self._frame_cond = threading.Condition()
        self.running = False
        self.connected = False
        self.error: str | None = None
        self.frames = 0
        self.fps = 0.0
        self.last_frame_at: datetime | None = None
        self.on_frame: Callable[[Frame], None] | None = None
        self.on_status: Callable[[dict], None] | None = None
        self.on_stopped: Callable[[], None] | None = None

    # ------------------------------------------------------------ control --
    def start(self, source_type: str | None = None, source: str | None = None, loop: bool | None = None) -> None:
        with self._lock:
            if self.running:
                raise RuntimeError("Camera already running")
            if source_type:
                self.source_type = source_type
            if source is not None:
                self.source = source
            if loop is not None:
                self.loop = loop
            build_source(self.source_type, self.source, self.loop)  # validate config early
            self._stop.clear()
            self.error = None
            self.frames = 0
            self.running = True
            self._thread = threading.Thread(target=self._run, name="camera-loop", daemon=True)
            self._thread.start()
        log.info("Camera started (%s: %s)", self.source_type, self.source)
        self._emit_status()

    def stop(self) -> None:
        with self._lock:
            if not self.running:
                return
            self._stop.set()
            thread = self._thread
        if thread:
            thread.join(timeout=10)
        with self._lock:
            self.running = False
            self.connected = False
            self._thread = None
        log.info("Camera stopped")
        self._emit_status()

    def restart(self) -> None:
        self.stop()
        self.start()

    # ------------------------------------------------------------- frames --
    def latest(self) -> Frame | None:
        return self._latest

    def wait_for_frame(self, last_index: int, timeout: float = 1.0) -> Frame | None:
        with self._frame_cond:
            self._frame_cond.wait_for(
                lambda: self._latest is not None and self._latest.index != last_index, timeout=timeout
            )
            return self._latest

    # -------------------------------------------------------------- loop ---
    def _run(self) -> None:
        source: FrameSource | None = None
        fps_window_start, fps_count = time.monotonic(), 0
        while not self._stop.is_set():
            try:
                if source is None:
                    source = build_source(self.source_type, self.source, self.loop, self.pace)
                    if isinstance(source, BrowserSource):
                        source.stop_event = self._stop
                    source.open()
                    self.connected, self.error = True, None
                    log.info("Camera connected: %s", source.describe())
                    self._emit_status()
                image, ts = source.read()
                image = resize_to(image, cfg.CAMERA_WIDTH, cfg.CAMERA_HEIGHT)
                self.frames += 1
                frame = Frame(image=image, ts=ts, wall=datetime.now(), index=self.frames)
                self.last_frame_at = frame.wall
                fps_count += 1
                elapsed = time.monotonic() - fps_window_start
                if elapsed >= 2.0:
                    self.fps = round(fps_count / elapsed, 1)
                    fps_window_start, fps_count = time.monotonic(), 0
                if self.on_frame:
                    try:
                        self.on_frame(frame)
                    except Exception as exc:  # a pipeline bug must not kill capture
                        log.exception("Frame processing error: %s", exc)
                with self._frame_cond:
                    self._latest = frame
                    self._frame_cond.notify_all()
            except SourceStopped:
                break
            except SourceEnded as exc:
                log.info("%s – stopping camera", exc)
                self.error = str(exc)
                break
            except Exception as exc:
                was_connected = self.connected
                self.connected, self.error = False, str(exc)
                if was_connected or source is None:
                    log.error("Camera error: %s (retrying in %.0fs)", exc, cfg.CAMERA_RECONNECT_SECONDS)
                    self._emit_status()
                if source is not None:
                    source.close()
                    source = None
                self._stop.wait(cfg.CAMERA_RECONNECT_SECONDS)
        if source is not None:
            source.close()
        self.connected = False
        self.running = False
        if self.on_stopped:
            try:
                self.on_stopped()
            except Exception as exc:
                log.exception("Stop handler failed: %s", exc)
        self._emit_status()

    def _emit_status(self) -> None:
        if self.on_status:
            try:
                self.on_status({"running": self.running, "connected": self.connected, "error": self.error})
            except Exception:
                pass
