from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import ValidationError

from app.api.deps import pipeline_dep
from app.database.schemas import RelevantObjects, RuntimeSettings, RuntimeSettingsUpdate
from app.services.pipeline import SurveillancePipeline
from app.services.settings_service import settings_service

router = APIRouter(prefix="/settings", tags=["settings"])


def _update(changes: dict) -> dict:
    try:
        return settings_service.update(changes)
    except ValidationError as exc:
        raise HTTPException(422, exc.errors(include_url=False)) from exc


@router.get("", response_model=RuntimeSettings, summary="All runtime settings")
def get_settings():
    return settings_service.get()


@router.put("", response_model=RuntimeSettings, summary="Update runtime settings (partial)")
def put_settings(body: RuntimeSettingsUpdate):
    return _update(body.model_dump(exclude_none=True))


@router.post("/reset", response_model=RuntimeSettings, summary="Reset all runtime settings to .env defaults")
def reset_settings():
    return settings_service.reset()


@router.get("/relevant-objects", response_model=RelevantObjects)
def get_relevant(p: SurveillancePipeline = Depends(pipeline_dep)):
    return RelevantObjects(relevant_objects=settings_service.value("relevant_objects"),
                           available_classes=p.detector.class_names)


@router.put("/relevant-objects", response_model=RelevantObjects,
            responses={422: {"description": "Unknown class"}})
def put_relevant(body: RelevantObjects, p: SurveillancePipeline = Depends(pipeline_dep)):
    known = set(p.detector.class_names)
    unknown = [c for c in body.relevant_objects if c.lower() not in known]
    if unknown:
        raise HTTPException(422, f"Unknown classes: {', '.join(unknown)}")
    s = _update({"relevant_objects": body.relevant_objects})
    return RelevantObjects(relevant_objects=s["relevant_objects"], available_classes=p.detector.class_names)
