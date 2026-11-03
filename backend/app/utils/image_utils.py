from pathlib import Path

import cv2
import numpy as np

# BGR colours for overlay states
COLORS = {
    "normal": (180, 160, 120),     # non-relevant detection (muted blue-grey)
    "relevant": (94, 197, 34),     # relevant object (green)
    "zone": (11, 158, 245),        # zone violation (amber)
    "loitering": (68, 68, 239),    # loitering (red)
}


def hex_to_bgr(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return b, g, r


def encode_jpeg(frame: np.ndarray, quality: int = 80) -> bytes:
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, int(quality)])
    if not ok:
        raise ValueError("JPEG encode failed")
    return buf.tobytes()


def decode_jpeg(data: bytes) -> np.ndarray:
    frame = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError("JPEG decode failed")
    return frame


def save_jpeg(frame: np.ndarray, path: Path, quality: int = 88) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return path


def resize_to(frame: np.ndarray, width: int, height: int) -> np.ndarray:
    if frame.shape[1] == width and frame.shape[0] == height:
        return frame
    return cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)


def draw_label(img: np.ndarray, text: str, x: int, y: int, color: tuple[int, int, int]) -> None:
    font, scale, thick = cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1
    (tw, th), base = cv2.getTextSize(text, font, scale, thick)
    y_top = max(0, y - th - base - 4)
    cv2.rectangle(img, (x, y_top), (x + tw + 6, y_top + th + base + 4), color, -1)
    cv2.putText(img, text, (x + 3, y_top + th + 2), font, scale, (15, 15, 15), thick, cv2.LINE_AA)


def draw_zones(img: np.ndarray, zones: list[dict]) -> None:
    h, w = img.shape[:2]
    overlay = img.copy()
    for z in zones:
        pts = np.array([[int(x * w), int(y * h)] for x, y in z["points"]], np.int32)
        color = hex_to_bgr(z.get("color", "#f59e0b"))
        cv2.fillPoly(overlay, [pts], color)
        cv2.polylines(img, [pts], True, color, 2, cv2.LINE_AA)
        draw_label(img, z["name"], int(pts[:, 0].min()), int(pts[:, 1].min()) + 16, color)
    cv2.addWeighted(overlay, 0.15, img, 0.85, 0, img)


def draw_tracks(img: np.ndarray, tracks: list[dict]) -> None:
    for t in tracks:
        x1, y1, x2, y2 = (int(v) for v in t["bbox"])
        color = COLORS.get(t.get("state", "normal"), COLORS["normal"])
        cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
        label = f"#{t['track_id']} {t['class']} {int(t['confidence'] * 100)}%"
        if t.get("dwell"):
            label += f" {t['dwell']:.0f}s"
        draw_label(img, label, x1, y1, color)


def draw_hud(img: np.ndarray, text: str, recording: bool) -> None:
    cv2.putText(img, text, (10, img.shape[0] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (240, 240, 240), 1, cv2.LINE_AA)
    if recording:
        cv2.circle(img, (img.shape[1] - 50, 18), 6, (40, 40, 230), -1)
        cv2.putText(img, "REC", (img.shape[1] - 40, 23), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (40, 40, 230), 1, cv2.LINE_AA)
