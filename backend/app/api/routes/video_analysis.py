"""Recorded video analysis REST API. Business logic lives in services/video_analysis_service.py."""
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from app.api.routes.events import to_out
from app.database.database import get_db
from app.database.models import Event, VideoAnalysis
from app.database.schemas import (AnalysisStartResponse, EventOut, MessageResponse, VideoAnalysisOut,
                                  VideoAnalysisStatus)
from app.services import storage_service
from app.services import video_analysis_service as svc
from app.utils.video_utils import VideoError

router = APIRouter(prefix="/video-analysis", tags=["video analysis"])

ERRORS = {400: {"description": "Invalid / unsupported / corrupted video"}, 404: {"description": "Not found"},
          409: {"description": "Not allowed in the current state"}, 413: {"description": "File too large"}}


def status_dict(va: VideoAnalysis) -> dict:
    return {
        "analysis_id": va.id, "status": va.status, "stage": va.stage, "progress": va.progress,
        "frames_processed": va.frames_processed, "total_frames": va.total_frames, "current_time": va.current_time,
        "duration": va.duration, "events_detected": va.events_detected, "objects_detected": va.objects_detected,
        **svc.summary_counts(va), "zone_violations": va.zone_violations, "loitering_events": va.loitering_events,
        "object_counts": va.object_counts or {}, "detections_run": va.detections_run,
        "processing_seconds": va.processing_seconds, "error": va.error, "warning": va.warning,
    }


def to_analysis_out(va: VideoAnalysis) -> VideoAnalysisOut:
    return VideoAnalysisOut(
        **status_dict(va), filename=va.filename, original_name=va.original_name, size_bytes=va.size_bytes,
        width=va.width, height=va.height, fps=va.fps, codec=va.codec, recorded_at=va.recorded_at,
        created_at=va.created_at, started_at=va.started_at, completed_at=va.completed_at,
        video_url=f"/api/video-analysis/{va.id}/video", preview_ready=bool(va.preview_path),
    )


def _get(db: Session, analysis_id: int) -> VideoAnalysis:
    va = db.get(VideoAnalysis, analysis_id)
    if va is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Analysis {analysis_id} not found")
    return va


@router.post("/upload", response_model=VideoAnalysisOut, status_code=201, responses=ERRORS,
             summary="Upload a prerecorded video (multipart/form-data)",
             description="Validates type and size, stores the file under storage/uploads with a safe unique name, "
                         "extracts duration, resolution, FPS and frame count, and returns the analysis id.")
async def upload(file: UploadFile = File(..., description=".mp4 .avi .mov .mkv .webm"),
                 recorded_at: datetime | None = Form(None, description="Optional real-world time of the first frame")):
    try:
        va = await run_in_threadpool(svc.save_upload, file.file, file.filename or "", recorded_at)
    except VideoError as exc:
        code = 413 if "larger than" in str(exc) else 507 if "disk space" in str(exc) else 400
        raise HTTPException(code, str(exc)) from exc
    finally:
        await file.close()
    return to_analysis_out(va)


@router.get("", response_model=list[VideoAnalysisOut], summary="List uploaded videos and their analyses")
def list_analyses(limit: int = Query(50, ge=1, le=500), db: Session = Depends(get_db)):
    return [to_analysis_out(v) for v in db.query(VideoAnalysis).order_by(VideoAnalysis.created_at.desc()).limit(limit)]


@router.get("/{analysis_id}", response_model=VideoAnalysisOut, responses=ERRORS)
def get_analysis(analysis_id: int, db: Session = Depends(get_db)):
    return to_analysis_out(_get(db, analysis_id))


@router.get("/{analysis_id}/status", response_model=VideoAnalysisStatus, responses=ERRORS,
            summary="Progress of an analysis (poll while processing)")
def get_status(analysis_id: int, db: Session = Depends(get_db)):
    return status_dict(_get(db, analysis_id))


@router.post("/{analysis_id}/start", response_model=AnalysisStartResponse, status_code=202, responses=ERRORS,
             summary="Run the PreVuCam pipeline on the uploaded video (background)",
             description="`force=true` re-analyses a completed video, replacing its previous events.")
def start(analysis_id: int, force: bool = False):
    try:
        va = svc.manager.start(analysis_id, force=force)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return AnalysisStartResponse(analysis_id=va.id, status=va.status)


@router.post("/{analysis_id}/cancel", response_model=VideoAnalysisStatus, responses=ERRORS,
             summary="Stop a queued or running analysis safely")
def cancel(analysis_id: int):
    try:
        va = svc.manager.cancel(analysis_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return status_dict(va)


@router.get("/{analysis_id}/events", response_model=list[EventOut], responses=ERRORS,
            summary="Events generated from this video, in video order")
def analysis_events(analysis_id: int, db: Session = Depends(get_db)):
    _get(db, analysis_id)
    rows = db.query(Event).filter(Event.analysis_id == analysis_id).order_by(Event.video_offset.asc(), Event.id).all()
    return [to_out(e) for e in rows]


@router.get("/{analysis_id}/video", response_class=FileResponse, responses=ERRORS,
            summary="Stream the uploaded video (browser-playable preview when available; supports seeking)")
def video(analysis_id: int, original: bool = False, db: Session = Depends(get_db)):
    va = _get(db, analysis_id)
    rel = va.file_path if original or not va.preview_path else va.preview_path
    path = storage_service.resolve(rel)
    if not path or not path.exists():
        raise HTTPException(404, "Video file not available")
    media = "video/mp4" if path.suffix.lower() in (".mp4", ".m4v") else f"video/{path.suffix.lstrip('.').lower()}"
    return FileResponse(path, media_type=media, filename=va.original_name if original else None)


@router.get("/{analysis_id}/frame", response_class=Response, responses=ERRORS,
            summary="A still frame (JPEG) from the uploaded video – used as background when drawing zones")
def frame(analysis_id: int, t: float | None = Query(None, ge=0, description="Seconds into the video")):
    try:
        jpg = svc.frame_at(analysis_id, t)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except VideoError as exc:
        raise HTTPException(400, str(exc)) from exc
    return Response(jpg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@router.delete("/{analysis_id}", response_model=MessageResponse, responses=ERRORS,
               summary="Delete the uploaded video (and optionally its events)")
def delete(analysis_id: int, delete_events: bool = False):
    try:
        freed = svc.delete_analysis(analysis_id, delete_events)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return MessageResponse(message=f"Analysis {analysis_id} deleted ({freed / 1e6:.1f} MB freed)")
