"""PreVuCam backend launcher (Windows / macOS / Linux).

    cd backend
    python run.py              # http://127.0.0.1:8000  (docs at /docs)
    python run.py --host 0.0.0.0 --port 8000 --reload

Checks the environment first and prints a plain-language error instead of a
stack trace when something is missing, then starts Uvicorn.
"""
from __future__ import annotations

import argparse
import importlib
import os
import sys
from pathlib import Path

REQUIRED = [  # (import name, pip name)
    ("fastapi", "fastapi"), ("uvicorn", "uvicorn[standard]"), ("pydantic_settings", "pydantic-settings"),
    ("sqlalchemy", "SQLAlchemy"), ("multipart", "python-multipart"), ("cv2", "opencv-python-headless"),
    ("numpy", "numpy"), ("reportlab", "reportlab"), ("httpx", "httpx"),
]
OPTIONAL = [("ultralytics", "ultralytics", "YOLO detection will be unavailable"),
            ("imageio_ffmpeg", "imageio-ffmpeg", "event clips may not play in the browser unless FFmpeg is installed")]


def fail(msg: str) -> None:
    print(f"\n[PreVuCam] ERROR: {msg}\n", file=sys.stderr)
    sys.exit(1)


def check() -> None:
    if sys.version_info < (3, 10):
        fail(f"Python 3.10 or newer is required (found {sys.version.split()[0]}).\n"
             "Install Python 3.11/3.12 from python.org and recreate the virtual environment.")
    missing = []
    for mod, pip_name in REQUIRED:
        try:
            importlib.import_module(mod)
        except Exception:
            missing.append(pip_name)
    if missing:
        fail("Missing packages: " + ", ".join(missing) + "\nRun:  pip install -r requirements.txt")
    for mod, pip_name, effect in OPTIONAL:
        try:
            importlib.import_module(mod)
        except Exception:
            print(f"[PreVuCam] warning: '{pip_name}' not installed – {effect}.")


def main() -> None:
    here = Path(__file__).resolve().parent
    os.chdir(here)  # so `app` is importable whatever directory you start from
    sys.path.insert(0, str(here))
    ap = argparse.ArgumentParser(description="Start the PreVuCam API")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--reload", action="store_true")
    args = ap.parse_args()
    check()
    try:
        from app.main import app  # noqa: F401  (import errors surface here, before the server starts)
    except Exception as exc:
        import traceback
        traceback.print_exc()
        fail(f"The backend failed to import: {exc}")
    import uvicorn
    print(f"[PreVuCam] API on http://{args.host}:{args.port}  ·  docs: http://{args.host}:{args.port}/docs")
    uvicorn.run("app.main:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
