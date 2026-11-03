from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import media_url
from app.database.database import get_db
from app.database.models import Timelapse
from app.database.schemas import MessageResponse, TimelapseOut, TimelapseRequest
from app.services import storage_service, timelapse_service

router = APIRouter(prefix="/timelapse", tags=["timelapse"])


def _out(t: Timelapse) -> TimelapseOut:
    out = TimelapseOut.model_validate(t)
    out.video_url = media_url(t.file_path)
    return out


@router.post("/generate", response_model=TimelapseOut, status_code=202,
             summary="Generate the daily timelapse for a date (runs in the background)")
def generate(body: TimelapseRequest, background: BackgroundTasks, db: Session = Depends(get_db)):
    running = db.query(Timelapse).filter(Timelapse.date == body.date, Timelapse.status == "processing").first()
    if running:
        raise HTTPException(status.HTTP_409_CONFLICT, f"A timelapse for {body.date} is already being generated")
    tl_id = timelapse_service.create_job(body.date)
    background.add_task(timelapse_service.generate, tl_id, body.date, body.speed)
    return _out(db.get(Timelapse, tl_id))


@router.get("", response_model=list[TimelapseOut])
def list_timelapses(db: Session = Depends(get_db)):
    return [_out(t) for t in db.query(Timelapse).order_by(Timelapse.created_at.desc()).all()]


@router.get("/{timelapse_id}", response_model=TimelapseOut)
def get_timelapse(timelapse_id: int, db: Session = Depends(get_db)):
    t = db.get(Timelapse, timelapse_id)
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Timelapse not found")
    return _out(t)


@router.get("/{timelapse_id}/download", response_class=FileResponse)
def download(timelapse_id: int, db: Session = Depends(get_db)):
    t = db.get(Timelapse, timelapse_id)
    path = storage_service.resolve(t.file_path) if t else None
    if not path or not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Timelapse video not available")
    return FileResponse(path, media_type="video/mp4", filename=path.name)


@router.delete("/{timelapse_id}", response_model=MessageResponse)
def delete(timelapse_id: int, db: Session = Depends(get_db)):
    t = db.get(Timelapse, timelapse_id)
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Timelapse not found")
    path = storage_service.resolve(t.file_path)
    if path and path.exists():
        path.unlink()
    db.delete(t)
    db.commit()
    return MessageResponse(message=f"Timelapse {timelapse_id} deleted")
