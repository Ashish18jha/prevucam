from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import pipeline_dep
from app.api.routes.events import to_out
from app.database.database import get_db
from app.database.models import Event
from app.database.schemas import AnalyticsCharts, AnalyticsSummary, CleanupResult, StorageInfo
from app.services import analytics_service, storage_service
from app.services.pipeline import SurveillancePipeline

router = APIRouter(tags=["analytics"])


@router.get("/analytics/summary", response_model=AnalyticsSummary, summary="Dashboard counters + recent events")
def summary(db: Session = Depends(get_db), p: SurveillancePipeline = Depends(pipeline_dep)):
    recent = db.query(Event).order_by(Event.start_time.desc()).limit(8).all()
    return AnalyticsSummary(**analytics_service.summary_counts(db), camera_running=p.camera.running,
                            storage=StorageInfo(**storage_service.storage_info()),
                            recent_events=[to_out(e) for e in recent])


@router.get("/analytics/charts", response_model=AnalyticsCharts, summary="Chart data for the last N days")
def charts(days: int = Query(7, ge=1, le=90), db: Session = Depends(get_db)):
    return analytics_service.charts(db, days)


@router.get("/storage", response_model=StorageInfo, summary="Disk and event storage usage")
def storage():
    return storage_service.storage_info()


@router.post("/storage/cleanup", response_model=CleanupResult,
             summary="Apply the retention policy now (never deletes protected events)")
def cleanup():
    return storage_service.apply_retention(force=True)
