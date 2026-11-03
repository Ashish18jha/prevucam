import asyncio
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import Response, StreamingResponse

from app.api.deps import pipeline_dep
from app.core.config import settings as cfg
from app.database.schemas import CameraStartRequest, CameraStatus, MessageResponse, VideoUploadResponse
from app.services.pipeline import SurveillancePipeline
from app.services.storage_service import has_free_space
from app.utils.image_utils import encode_jpeg
from app.utils.logger import get_logger
from app.utils.video_utils import probe_video

router = APIRouter(prefix="/camera", tags=["camera"])
log = get_logger("api.camera")

ALLOWED_VIDEO = {".mp4", ".avi", ".mov", ".mkv", ".webm", ".m4v"}


@router.get("/status", response_model=CameraStatus, summary="Camera and pipeline status")
def camera_status(p: SurveillancePipeline = Depends(pipeline_dep)):
    return p.status()


@router.post("/start", response_model=CameraStatus, summary="Start the camera / video source",
             responses={409: {"description": "Already running"}, 400: {"description": "Invalid source"}})
def start_camera(body: CameraStartRequest | None = None, p: SurveillancePipeline = Depends(pipeline_dep)):
    body = body or CameraStartRequest()
    if p.camera.running:
        raise HTTPException(status.HTTP_409_CONFLICT, "Camera is already running")
    try:
        p.start(source_type=body.source_type, source=body.source, loop=body.loop)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return p.status()


@router.post("/stop", response_model=CameraStatus, summary="Stop the camera (finishes any active event)")
def stop_camera(p: SurveillancePipeline = Depends(pipeline_dep)):
    p.stop()
    return p.status()


@router.post("/restart", response_model=CameraStatus, summary="Restart the camera with its current source")
def restart_camera(p: SurveillancePipeline = Depends(pipeline_dep)):
    p.stop()
    try:
        p.start()
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return p.status()


@router.get("/stream", summary="Live MJPEG stream",
            description="multipart/x-mixed-replace JPEG stream. `overlay=true` draws boxes, tracking IDs and zones.")
async def stream(overlay: bool = Query(True), fps: int = Query(12, ge=1, le=30),
                 p: SurveillancePipeline = Depends(pipeline_dep)):
    boundary = "frame"
    interval = 1.0 / fps

    async def gen():
        last_id = None
        while True:
            img = p.annotated_frame() if overlay else p.raw_frame()
            if img is None:
                await asyncio.sleep(0.3)
                continue
            if id(img) != last_id:
                last_id = id(img)
                jpg = await asyncio.to_thread(encode_jpeg, img, 75)
                yield (f"--{boundary}\r\nContent-Type: image/jpeg\r\nContent-Length: {len(jpg)}\r\n\r\n").encode() + jpg + b"\r\n"
            await asyncio.sleep(interval)

    return StreamingResponse(gen(), media_type=f"multipart/x-mixed-replace; boundary={boundary}",
                             headers={"Cache-Control": "no-store"})


@router.get("/snapshot", summary="Current frame as JPEG", responses={404: {"description": "No frame available"}},
            response_class=Response)
def snapshot(overlay: bool = Query(False), p: SurveillancePipeline = Depends(pipeline_dep)):
    img = p.annotated_frame() if overlay else p.raw_frame()
    if img is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No frame available – start the camera first")
    return Response(encode_jpeg(img, 85), media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@router.post("/upload", response_model=VideoUploadResponse, status_code=201,
             summary="Upload a test video (use it with source_type=file)",
             responses={400: {"description": "Invalid video"}, 507: {"description": "Storage full"}})
async def upload_video(file: UploadFile = File(...)):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_VIDEO:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unsupported file type '{ext}'")
    if not has_free_space():
        raise HTTPException(status.HTTP_507_INSUFFICIENT_STORAGE, "Not enough free disk space")
    safe = "".join(c for c in Path(file.filename).stem if c.isalnum() or c in "-_")[:50] or "video"
    dest = cfg.subdir("uploads") / f"{safe}_{uuid.uuid4().hex[:6]}{ext}"
    with dest.open("wb") as fh:
        shutil.copyfileobj(file.file, fh)
    try:
        info = probe_video(dest)
    except ValueError as exc:
        dest.unlink(missing_ok=True)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Invalid video: {exc}") from exc
    log.info("Uploaded test video %s (%d frames)", dest.name, info.frames)
    return VideoUploadResponse(filename=dest.name, path=str(dest), size_bytes=dest.stat().st_size,
                               frames=info.frames, fps=info.fps, width=info.width, height=info.height)


@router.get("/uploads", response_model=list[VideoUploadResponse], summary="List uploaded test videos")
def list_uploads():
    out = []
    for f in sorted(cfg.subdir("uploads").iterdir()):
        if f.suffix.lower() not in ALLOWED_VIDEO:
            continue
        try:
            info = probe_video(f)
        except ValueError:
            continue
        out.append(VideoUploadResponse(filename=f.name, path=str(f), size_bytes=f.stat().st_size,
                                       frames=info.frames, fps=info.fps, width=info.width, height=info.height))
    return out


@router.delete("/uploads/{filename}", response_model=MessageResponse, summary="Delete an uploaded video")
def delete_upload(filename: str):
    path = cfg.subdir("uploads") / Path(filename).name
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    path.unlink()
    return MessageResponse(message=f"Deleted {path.name}")
