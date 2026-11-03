from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.api.deps import pipeline_dep
from app.database.database import get_db
from app.database.models import LoiteringRecord
from app.database.schemas import LoiteringRecordOut, LoiteringSettings
from app.services.pipeline import SurveillancePipeline
from app.services.settings_service import settings_service

router = APIRouter(tags=["detection"])


@router.get("/detection/live", summary="Latest tracked detections from the pipeline")
def live_detections(p: SurveillancePipeline = Depends(pipeline_dep)):
    return {"at": p.last_detection_at, "tracks": p.last_detections,
            "active_event_id": p.events.active_event_id, "motion": p.status()["motion"]}


@router.get("/detection/classes", summary="Object classes the model can detect")
def classes(p: SurveillancePipeline = Depends(pipeline_dep)):
    return {"classes": p.detector.class_names, "relevant": settings_service.value("relevant_objects")}


@router.get("/detection/model", summary="Detector status")
def model_status(p: SurveillancePipeline = Depends(pipeline_dep)):
    return {"available": p.detector.available, "model_path": p.detector.model_path,
            "imgsz": p.detector.imgsz, "confidence": p.detector.confidence, "error": p.detector.error}


@router.post("/detection/model/reload", summary="Retry loading the YOLO model")
def reload_model(p: SurveillancePipeline = Depends(pipeline_dep)):
    ok = p.detector.reload()
    return {"available": ok, "error": p.detector.error}


@router.get("/loitering/settings", response_model=LoiteringSettings)
def get_loitering_settings():
    s = settings_service.get()
    return LoiteringSettings(loitering_seconds=s["loitering_seconds"], loitering_classes=s["loitering_classes"],
                             trigger_on_loitering=s["trigger_on_loitering"])


@router.put("/loitering/settings", response_model=LoiteringSettings)
def put_loitering_settings(body: LoiteringSettings):
    try:
        s = settings_service.update(body.model_dump())
    except ValidationError as exc:
        raise HTTPException(422, exc.errors(include_url=False)) from exc
    return LoiteringSettings(loitering_seconds=s["loitering_seconds"], loitering_classes=s["loitering_classes"],
                             trigger_on_loitering=s["trigger_on_loitering"])


@router.get("/loitering/active", summary="People currently inside zones with their dwell time")
def active_loitering(p: SurveillancePipeline = Depends(pipeline_dep)):
    return p.active_stays()


@router.get("/loitering/records", response_model=list[LoiteringRecordOut], summary="Completed zone stays")
def loitering_records(limit: int = Query(100, ge=1, le=1000), triggered_only: bool = False,
                      db: Session = Depends(get_db)):
    q = db.query(LoiteringRecord)
    if triggered_only:
        q = q.filter(LoiteringRecord.status == "triggered")
    return q.order_by(LoiteringRecord.enter_time.desc()).limit(limit).all()
