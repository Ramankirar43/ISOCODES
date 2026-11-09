from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.db.models import Importer, Shipment, ShipmentStatus, UserRole
from app.schemas.shipments import ShipmentCreate, ShipmentResponse

router = APIRouter()


class ImporterResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    legal_name: str


def can_access_shipment(user, shipment: Shipment) -> bool:
    return user.role in {UserRole.EXECUTIVE, UserRole.MANAGER} or user.importer_id == shipment.importer_id


@router.get("/importers", response_model=list[ImporterResponse])
def list_importers(db: DbSession, user: CurrentUser) -> list[Importer]:
    if user.role not in {UserRole.EXECUTIVE, UserRole.MANAGER}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only staff can list importers")
    return list(db.scalars(select(Importer).order_by(Importer.legal_name)))


@router.get("", response_model=list[ShipmentResponse])
def list_shipments(db: DbSession, user: CurrentUser) -> list[Shipment]:
    query = select(Shipment).order_by(Shipment.created_at.desc())
    if user.role == UserRole.IMPORTER:
        query = query.where(Shipment.importer_id == user.importer_id)
    return list(db.scalars(query))


@router.post("", response_model=ShipmentResponse, status_code=status.HTTP_201_CREATED)
def create_shipment(payload: ShipmentCreate, db: DbSession, user: CurrentUser) -> Shipment:
    if user.role not in {UserRole.EXECUTIVE, UserRole.MANAGER}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only staff can create shipments")
    if db.get(Importer, payload.importer_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Importer not found")
    existing = db.scalar(select(Shipment).where(Shipment.shipment_number == payload.shipment_number))
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Shipment number already exists")
    shipment = Shipment(**payload.model_dump(), created_by=user.id, status=ShipmentStatus.DRAFT)
    db.add(shipment)
    db.commit()
    db.refresh(shipment)
    return shipment


@router.get("/{shipment_id}", response_model=ShipmentResponse)
def get_shipment(shipment_id: str, db: DbSession, user: CurrentUser) -> Shipment:
    shipment = db.get(Shipment, shipment_id)
    if shipment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shipment not found")
    if not can_access_shipment(user, shipment):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Shipment access denied")
    return shipment
