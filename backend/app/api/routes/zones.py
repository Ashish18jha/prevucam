from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.database.models import Zone
from app.database.schemas import MessageResponse, ZoneCreate, ZoneOut, ZoneUpdate
from app.services.pipeline import get_pipeline
from app.utils.logger import get_logger

router = APIRouter(prefix="/zones", tags=["zones"])
log = get_logger("api.zones")


def _get(db: Session, zone_id: int) -> Zone:
    z = db.get(Zone, zone_id)
    if z is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Zone {zone_id} not found")
    return z


def _commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "A zone with this name already exists") from exc
    get_pipeline().reload_zones()


@router.get("", response_model=list[ZoneOut])
def list_zones(db: Session = Depends(get_db)):
    return db.query(Zone).order_by(Zone.id).all()


@router.get("/{zone_id}", response_model=ZoneOut)
def get_zone(zone_id: int, db: Session = Depends(get_db)):
    return _get(db, zone_id)


@router.post("", response_model=ZoneOut, status_code=201,
             responses={409: {"description": "Duplicate name"}, 422: {"description": "Invalid polygon"}})
def create_zone(body: ZoneCreate, db: Session = Depends(get_db)):
    z = Zone(**body.model_dump())
    db.add(z)
    _commit(db)
    db.refresh(z)
    log.info("Zone created: %s", z.name)
    return z


@router.put("/{zone_id}", response_model=ZoneOut)
def update_zone(zone_id: int, body: ZoneUpdate, db: Session = Depends(get_db)):
    z = _get(db, zone_id)
    changes = body.model_dump(exclude_unset=True)
    for k, v in changes.items():
        if v is None and k != "loitering_seconds":
            continue
        setattr(z, k, v)
    _commit(db)
    db.refresh(z)
    return z


@router.delete("/{zone_id}", response_model=MessageResponse)
def delete_zone(zone_id: int, db: Session = Depends(get_db)):
    z = _get(db, zone_id)
    db.delete(z)
    _commit(db)
    return MessageResponse(message=f"Zone {zone_id} deleted")
