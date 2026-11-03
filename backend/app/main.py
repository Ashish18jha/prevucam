"""PreVuCam FastAPI application entry point.

Run from the `backend/` directory:
    uvicorn app.main:app --host 0.0.0.0 --port 8000
"""
import asyncio
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import SQLAlchemyError

from app.api.routes import (analytics, camera, detection, events, live, notifications, reports, settings,
                            timelapse, video_analysis, zones)
from app.core.config import settings as cfg
from app.core.security import require_api_key
from app.database.database import init_db
from app.services import storage_service, video_analysis_service
from app.services.event_bus import event_bus
from app.services.pipeline import get_pipeline
from app.services.settings_service import settings_service
from app.utils.logger import get_logger, setup_logging

setup_logging()
log = get_logger("main")
if sys.version_info < (3, 10):  # pragma: no cover
    raise RuntimeError("PreVuCam needs Python 3.10 or newer")


async def _retention_loop() -> None:
    while True:
        await asyncio.sleep(3600)
        try:
            await asyncio.to_thread(storage_service.apply_retention)
        except Exception as exc:
            log.error("Retention job failed: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    video_analysis_service.recover_interrupted()
    settings_service.load()
    event_bus.bind_loop(asyncio.get_running_loop())
    pipeline = get_pipeline()
    # warm the detector in the background so the first request isn't slow
    asyncio.get_running_loop().run_in_executor(None, lambda: pipeline.detector.available)
    if cfg.CAMERA_AUTOSTART:
        try:
            pipeline.start()
        except Exception as exc:
            log.error("Camera autostart failed: %s", exc)
    retention = asyncio.create_task(_retention_loop())
    log.info("%s %s started (storage=%s)", cfg.APP_NAME, cfg.APP_VERSION, cfg.storage_dir)
    yield
    retention.cancel()
    video_analysis_service.manager.shutdown()
    pipeline.stop()
    pipeline.events.wait_idle(timeout=60)
    log.info("Shutdown complete")


app = FastAPI(
    title="PreVuCam API",
    version=cfg.APP_VERSION,
    description="AI-enhanced event-driven surveillance: motion gating, YOLOv8 detection, tracking, "
                "smart zones, loitering, pre/post-event recording, Gemini summaries and alerts.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware, allow_origins=cfg.cors_origins, allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)


@app.middleware("http")
async def api_key_guard(request: Request, call_next):
    if cfg.API_KEY and request.method != "OPTIONS" and request.url.path.startswith(("/api", "/media")):
        try:
            await require_api_key(request)
        except HTTPException as exc:
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    return await call_next(request)


@app.exception_handler(SQLAlchemyError)
async def db_error(_: Request, exc: SQLAlchemyError):
    log.error("Database error: %s", exc)
    return JSONResponse({"detail": "Database error – please retry"}, status_code=503)


@app.exception_handler(Exception)
async def unhandled(_: Request, exc: Exception):
    log.exception("Unhandled error: %s", exc)
    return JSONResponse({"detail": "Internal server error"}, status_code=500)


for r in (camera, events, detection, zones, settings, reports, notifications, analytics, timelapse, video_analysis):
    app.include_router(r.router, prefix="/api")
app.include_router(live.router)

for sub in ("events", "snapshots", "timelapse"):
    app.mount(f"/media/{sub}", StaticFiles(directory=cfg.subdir(sub)), name=f"media-{sub}")


@app.get("/api/health", tags=["system"], summary="Liveness probe")
def health():
    p = get_pipeline()
    return {"status": "ok", "version": cfg.APP_VERSION, "camera_running": p.camera.running,
            "detector_available": p.detector._model is not None, "ws_clients": event_bus.subscriber_count}
