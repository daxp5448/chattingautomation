import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import BranchStatus


class BranchBase(BaseModel):
    name: str
    address: str | None = None
    google_map_link: str | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    phone: str | None = None
    delivery_radius_km: float | None = Field(default=None, ge=0)
    opening_hours: dict[str, Any] = {}
    manager_name: str | None = None
    status: BranchStatus = BranchStatus.OPEN
    estimated_delivery_time_minutes: int | None = None
    kitchen_name: str | None = None
    printer_name: str | None = None


class BranchCreate(BranchBase):
    pass


class BranchUpdate(BaseModel):
    name: str | None = None
    address: str | None = None
    google_map_link: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    phone: str | None = None
    delivery_radius_km: float | None = None
    opening_hours: dict[str, Any] | None = None
    manager_name: str | None = None
    status: BranchStatus | None = None
    estimated_delivery_time_minutes: int | None = None
    kitchen_name: str | None = None
    printer_name: str | None = None


class BranchRead(BranchBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    restaurant_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
