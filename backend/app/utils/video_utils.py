import shutil
import subprocess
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import cv2

from app.utils.logger import get_logger

log = get_logger("video")


@dataclass
class VideoInfo:
    frames: int
    fps: float
    width: int
    height: int
    codec: str = ""

    @property
    def duration(self) -> float:
        return self.frames / self.fps if self.fps else 0.0


class VideoError(ValueError):
    """A video could not be used; the message is meant for end users."""


@lru_cache
def ffmpeg_exe() -> str | None:
    """System FFmpeg, else the binary bundled with the `imageio-ffmpeg` pip package (Windows-friendly)."""
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def ffmpeg_available() -> bool:
    return ffmpeg_exe() is not None


def _fourcc(cap: cv2.VideoCapture) -> str:
    code = int(cap.get(cv2.CAP_PROP_FOURCC) or 0)
    return "".join(chr((code >> 8 * i) & 0xFF) for i in range(4)).strip("\x00 ").lower() if code else ""


def probe_video(path: str | Path, count_if_unknown: bool = True) -> VideoInfo:
    """Read basic metadata with OpenCV. Raises VideoError with a user-facing message."""
    path = Path(path)
    if not path.exists():
        raise VideoError("The video file could not be found.")
    if path.stat().st_size == 0:
        raise VideoError("The uploaded file is empty.")
    cap = cv2.VideoCapture(str(path))
    try:
        if not cap.isOpened():
            raise VideoError("Unable to process this video because the file is corrupted or not a supported video.")
        ok, frame = cap.read()
        if not ok or frame is None:
            raise VideoError("Unable to process this video because the file is corrupted or contains no frames.")
        fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
        if fps <= 0 or fps > 240:
            fps = 15.0
        frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        h, w = frame.shape[:2]
        codec = _fourcc(cap)
        if frames <= 0 and count_if_unknown:  # some containers (webm/mkv) don't store a frame count
            frames = 1
            while cap.grab():
                frames += 1
        return VideoInfo(frames=frames, fps=float(fps), width=w, height=h, codec=codec)
    finally:
        cap.release()


def open_writer(path: Path, fps: float, size: tuple[int, int]) -> cv2.VideoWriter:
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, size)
    if not writer.isOpened():
        raise RuntimeError(f"Could not open video writer for {path}")
    return writer


def transcode_to_h264(src: Path, dst: Path, timeout: int = 900, max_width: int | None = None) -> bool:
    """Re-encode to browser-playable H.264 MP4 (faststart). Returns True on success."""
    exe = ffmpeg_exe()
    if not exe:
        return False
    cmd = [exe, "-y", "-loglevel", "error", "-i", str(src)]
    if max_width:
        cmd += ["-vf", f"scale='min({max_width},iw)':-2"]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an", str(dst)]
    flags = {"creationflags": 0x08000000} if sys.platform == "win32" else {}  # no console window on Windows
    try:
        subprocess.run(cmd, check=True, timeout=timeout, capture_output=True, **flags)
        return dst.exists() and dst.stat().st_size > 0
    except (subprocess.SubprocessError, OSError) as exc:
        stderr = getattr(exc, "stderr", b"") or b""
        log.warning("ffmpeg transcode failed for %s: %s %s", src.name, exc, stderr.decode(errors="ignore")[:300])
        dst.unlink(missing_ok=True)
        return False


def finalize_mp4(raw_path: Path, final_path: Path) -> Path:
    """Transcode raw mp4v output to H.264; fall back to the raw file if ffmpeg is missing/fails."""
    if transcode_to_h264(raw_path, final_path):
        raw_path.unlink(missing_ok=True)
        return final_path
    if raw_path != final_path:
        raw_path.replace(final_path)
    return final_path


BROWSER_SAFE = {("mp4", "avc1"), ("mp4", "h264"), ("mov", "avc1"), ("mov", "h264"), ("webm", "vp80"),
                ("webm", "vp90"), ("webm", "vp8"), ("webm", "vp9")}


def is_browser_playable(path: Path, codec: str) -> bool:
    return (path.suffix.lower().lstrip("."), codec) in BROWSER_SAFE
