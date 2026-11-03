from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.database.models import Report
from app.database.schemas import MessageResponse, ReportOut
from app.services import report_service, storage_service

router = APIRouter(prefix="/reports", tags=["reports"])


def _out(r: Report) -> ReportOut:
    out = ReportOut.model_validate(r)
    out.download_url = f"/api/reports/{r.id}"
    return out


@router.post("/events/{event_id}", response_model=ReportOut, status_code=201,
             summary="Generate a PDF incident report for an event",
             responses={404: {"description": "Event not found"}, 409: {"description": "Event still recording"}})
def generate(event_id: int):
    try:
        report = report_service.generate_event_report(event_id)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return _out(report)


@router.get("", response_model=list[ReportOut], summary="List generated reports")
def list_reports(event_id: int | None = None, limit: int = Query(100, ge=1, le=1000), db: Session = Depends(get_db)):
    q = db.query(Report)
    if event_id is not None:
        q = q.filter(Report.event_id == event_id)
    return [_out(r) for r in q.order_by(Report.created_at.desc()).limit(limit).all()]


@router.get("/{report_id}", summary="Download a report PDF", response_class=FileResponse,
            responses={404: {"description": "Not found"}})
def download(report_id: int, inline: bool = False, db: Session = Depends(get_db)):
    r = db.get(Report, report_id)
    path = storage_service.resolve(r.file_path) if r else None
    if not path or not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Report not found")
    return FileResponse(path, media_type="application/pdf", filename=path.name,
                        content_disposition_type="inline" if inline else "attachment")


@router.delete("/{report_id}", response_model=MessageResponse)
def delete(report_id: int, db: Session = Depends(get_db)):
    r = db.get(Report, report_id)
    if r is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Report not found")
    path = storage_service.resolve(r.file_path)
    if path and path.exists():
        path.unlink()
    db.delete(r)
    db.commit()
    return MessageResponse(message=f"Report {report_id} deleted")

