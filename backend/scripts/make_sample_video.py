"""Generate a deterministic test video for PreVuCam's test mode.

A real person (cropped from a public sample photo, or an image you supply)
walks into the right half of a synthetic scene, stands still long enough to
trigger loitering, then leaves. Use it with:

    python scripts/make_sample_video.py                    # -> storage/uploads/sample_walkin.mp4
    python scripts/make_sample_video.py --person me.jpg    # use your own full-body photo

Then start the camera with source_type=file, source=sample_walkin.mp4.
Suggested zone covering the stop position: [[0.5,0.3],[0.98,0.3],[0.98,0.98],[0.5,0.98]].
"""
from __future__ import annotations

import argparse
import sys
import urllib.request
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.config import settings as cfg  # noqa: E402

SAMPLE_URL = "https://raw.githubusercontent.com/ultralytics/assets/main/im/bus.jpg"


def load_person(path: str | None) -> np.ndarray:
    if path:
        img = cv2.imread(path)
        if img is None:
            raise SystemExit(f"Cannot read {path}")
    else:
        cache = cfg.subdir("uploads") / "_sample_person_src.jpg"
        if not cache.exists():
            print(f"Downloading sample image {SAMPLE_URL}")
            urllib.request.urlretrieve(SAMPLE_URL, cache)
        img = cv2.imread(str(cache))
    try:
        from ultralytics import YOLO
        model = YOLO(cfg.MODEL_PATH)
        r = model(img, verbose=False)[0]
        people = [b for b, c, s in zip(r.boxes.xyxy.tolist(), r.boxes.cls.tolist(), r.boxes.conf.tolist())
                  if int(c) == 0 and s > 0.6]
        if people:
            # the most clearly separated full-body pedestrian: tall, narrow box
            x1, y1, x2, y2 = (int(v) for v in max(people, key=lambda b: (b[3] - b[1]) / (b[2] - b[0])))
            pad = 4
            img = img[max(0, y1 - pad):y2 + pad, max(0, x1 - pad):x2 + pad]
    except Exception as exc:  # fall back to the whole image
        print(f"Person crop skipped: {exc}")
    return img


def background(w: int, h: int) -> np.ndarray:
    bg = np.zeros((h, w, 3), np.uint8)
    for y in range(h):
        bg[y, :] = (55 + y * 50 // h, 60 + y * 40 // h, 64)
    cv2.rectangle(bg, (0, int(h * 0.72)), (w, h), (85, 90, 88), -1)
    for i, x in enumerate(range(20, w, 150)):
        cv2.rectangle(bg, (x, int(h * 0.30)), (x + 90, int(h * 0.72)), (70 + i * 6, 78, 92), -1)
        cv2.rectangle(bg, (x + 30, int(h * 0.50)), (x + 60, int(h * 0.72)), (40, 45, 55), -1)
    return bg


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--person", help="Optional image of a person")
    ap.add_argument("--out", default=str(cfg.subdir("uploads") / "sample_walkin.mp4"))
    ap.add_argument("--fps", type=int, default=15)
    ap.add_argument("--stand", type=float, default=26.0, help="Seconds the person stands still")
    args = ap.parse_args()

    w, h, fps = cfg.CAMERA_WIDTH, cfg.CAMERA_HEIGHT, args.fps
    person = load_person(args.person)
    ph = int(h * 0.62)
    pw = int(person.shape[1] * ph / person.shape[0])
    person = cv2.resize(person, (pw, ph))
    bg = background(w, h)

    # timeline (seconds): empty, walk in, stand, walk out, empty
    segments = [("empty", 6.0), ("in", 6.0), ("stand", args.stand), ("out", 5.0), ("empty", 12.0)]
    x_start, x_stop, x_end = -pw, int(w * 0.68) - pw // 2, w + 10
    y = h - ph - 20
    writer = cv2.VideoWriter(args.out, cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    rng = np.random.default_rng(1)
    n = 0
    for kind, secs in segments:
        frames = int(secs * fps)
        for i in range(frames):
            frame = bg.copy()
            frame = cv2.add(frame, rng.integers(0, 4, frame.shape, dtype=np.uint8))  # sensor noise
            if kind != "empty":
                if kind == "in":
                    x = int(x_start + (x_stop - x_start) * i / frames)
                elif kind == "stand":
                    x = x_stop + int(3 * np.sin(i / 7.0))  # slight sway
                else:
                    x = int(x_stop + (x_end - x_stop) * i / frames)
                x0, x1 = max(0, x), min(w, x + pw)
                if x1 > x0:
                    frame[y:y + ph, x0:x1] = person[:, x0 - x:x1 - x]
            cv2.putText(frame, f"TEST  t={n / fps:05.1f}s", (10, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                        (230, 230, 230), 1, cv2.LINE_AA)
            writer.write(frame)
            n += 1
    writer.release()
    print(f"Wrote {args.out}: {n} frames, {n / fps:.1f}s @ {fps} fps")


if __name__ == "__main__":
    main()
