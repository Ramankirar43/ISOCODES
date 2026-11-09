from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import ShipmentStatus


class ShipmentCreate(BaseModel):
    shipment_number: str = Field(min_length=3, max_length=40, pattern=r"^[A-Za-z0-9-]+$")
    importer_id: str
    supplier_name: str | None = Field(default=None, max_length=255)


class ShipmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    shipment_number: str
    importer_id: str
    supplier_name: str | None
    status: ShipmentStatus
    created_by: str
    created_at: datetime
    updated_at: datetime

