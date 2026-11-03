"""Generate `security_test.mp4` – a deterministic recorded-video test for Video Analysis.

1280x720 @ 30 fps, 92 s. Real people and a real bus (cut from a public Ultralytics sample
photo) move over a synthetic street so YOLO sees genuine objects:

    07–17 s  person A walks in from the left, turns round, leaves      -> object detection event
    24–38 s  a bus drives across the frame through the right-hand zone   -> zone violation event
    48–80 s  person B walks into the right-hand zone and stands ~22 s    -> loitering event

Draw a zone over the right part of the frame, e.g. "Restricted Area":
    [[0.55,0.35],[0.99,0.35],[0.99,0.99],[0.55,0.99]]

    python scripts/make_security_test_video.py [--out path]      # default: samples/security_test.mp4
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

SRC_URL = "https://raw.githubusercontent.com/ultralytics/assets/main/im/bus.jpg"
W, H, FPS = 1280, 720, 30


def source_image() -> np.ndarray:
    cache = cfg.subdir("uploads") / "_bus_src.jpg"
    if not cache.exists():
        print(f"Downloading {SRC_URL}")
        urllib.request.urlretrieve(SRC_URL, cache)
    return cv2.imread(str(cache))


def crops(img: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    from ultralytics import YOLO

    r = YOLO(cfg.MODEL_PATH)(img, verbose=False)[0]
    boxes = [(int(c), s, [int(v) for v in b]) for b, c, s in
             zip(r.boxes.xyxy.tolist(), r.boxes.cls.tolist(), r.boxes.conf.tolist())]
    iw = img.shape[1]
    # whole people only (not cut off by the photo edge), most confident first
    people = sorted([(s, b) for c, s, b in boxes if c == 0 and s > 0.5 and b[0] > 5 and b[2] < iw - 5],
                    key=lambda x: -x[0])
    bus = max((b for c, s, b in boxes if c == 5), key=lambda b: (b[2] - b[0]) * (b[3] - b[1]))
    if len(people) < 2:
        raise SystemExit("Could not find two people in the source image")
    # the stretch of bus between the pedestrians in front of it, so the sprite contains no people
    everyone = [b for c, s, b in boxes if c == 0 and s > 0.5]
    left_edge = max([bus[0]] + [p[2] + 6 for p in everyone if p[2] < (bus[0] + bus[2]) / 2 + 60])
    right_edge = min([bus[2]] + [p[0] - 6 for p in everyone if p[0] > left_edge])
    front = img[bus[1]:bus[3], bus[0]:max(bus[0] + 1, min(p[0] for p in everyone if p[0] > bus[0]) - 2)]
    side = img[bus[1]:bus[3], left_edge:right_edge]
    bus_sprite = np.hstack([front, side, side[:, : side.shape[1] // 2]])  # long enough to read as a bus
    people = [people[0][1], people[1][1]]
    cut = lambda b, p=4: img[max(0, b[1] - p):b[3] + p, max(0, b[0] - p):b[2] + p]  # noqa: E731
    return cut(people[0]), cut(people[1]), bus_sprite


def fit(sprite: np.ndarray, height: int) -> np.ndarray:
    return cv2.resize(sprite, (int(sprite.shape[1] * height / sprite.shape[0]), height))


def paste(frame: np.ndarray, sprite: np.ndarray, x: int, y: int) -> None:
    h, w = sprite.shape[:2]
    x0, x1 = max(0, x), min(W, x + w)
    y0, y1 = max(0, y), min(H, y + h)
    if x1 > x0 and y1 > y0:
        frame[y0:y1, x0:x1] = sprite[y0 - y:y1 - y, x0 - x:x1 - x]


def background() -> np.ndarray:
    bg = np.zeros((H, W, 3), np.uint8)
    for y in range(H):
        bg[y, :] = (58 + y * 45 // H, 62 + y * 38 // H, 66)
    cv2.rectangle(bg, (0, int(H * 0.74)), (W, H), (84, 88, 86), -1)
    for i, x in enumerate(range(30, W, 210)):
        cv2.rectangle(bg, (x, int(H * 0.26)), (x + 130, int(H * 0.74)), (72 + i * 5, 80, 94), -1)
        cv2.rectangle(bg, (x + 45, int(H * 0.50)), (x + 85, int(H * 0.74)), (40, 45, 55), -1)
    return bg


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * max(0.0, min(1.0, t))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[2] / "samples" / "security_test.mp4"))
    args = ap.parse_args()

    src = source_image()
    person_a, person_b, bus = crops(src)
    person_a, person_b, bus = fit(person_a, int(H * 0.52)), fit(person_b, int(H * 0.56)), fit(bus, int(H * 0.50))
    bg = background()
    ground = int(H * 0.96)
    rng = np.random.default_rng(3)
    writer = cv2.VideoWriter(args.out, cv2.VideoWriter_fourcc(*"mp4v"), FPS, (W, H))
    duration = 92.0
    for n in range(int(duration * FPS)):
        t = n / FPS
        frame = cv2.add(bg, rng.integers(0, 4, bg.shape, dtype=np.uint8))
        if 24 <= t < 38:  # bus: left -> right through the zone
            x = int(lerp(-bus.shape[1], W + 10, (t - 24) / 14))
            paste(frame, bus, x, int(H * 0.92) - bus.shape[0])
        if 7 <= t < 17:  # person A: in from the left to ~30 %, then back out
            k = (t - 7) / 10
            x = int(lerp(-person_a.shape[1], W * 0.30, k * 2) if k < 0.5 else lerp(W * 0.30, -person_a.shape[1], (k - 0.5) * 2))
            paste(frame, person_a, x, ground - person_a.shape[0])
        if 48 <= t < 80:  # person B: in from the right, stands in the zone, leaves right
            stop = int(W * 0.74)
            if t < 53:
                x = int(lerp(W + 5, stop, (t - 48) / 5))
            elif t < 75:
                x = stop + int(4 * np.sin(t * 2.0))  # standing, slight sway
            else:
                x = int(lerp(stop, W + 5, (t - 75) / 5))
            paste(frame, person_b, x, ground - person_b.shape[0])
        cv2.putText(frame, f"CAM-02  SECURITY TEST  t={t:05.1f}s", (16, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.8,
                    (235, 235, 235), 2, cv2.LINE_AA)
        writer.write(frame)
    writer.release()
    print(f"Wrote {args.out}: {int(duration * FPS)} frames, {duration:.0f}s @ {FPS} fps, {W}x{H}")


if __name__ == "__main__":
    main()
