import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models.enums import EngagementStatus, EngagementType


class EngagementItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    catalog_item_id: uuid.UUID
    name_snapshot: str
    price_snapshot: float
    quantity: int


class EngagementRead(BaseModel):
    """The generic-engine counterpart of OrderRead -- one shape covers all 4
    EngagementType values (order/inquiry/appointment/booking); `items` is only
    populated for type="order", `details` carries the type-specific structured data
    for the other three (see app/models/engagement.py's class docstring)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    restaurant_id: uuid.UUID
    branch_id: uuid.UUID | None
    reference_number: str
    type: EngagementType
    status: EngagementStatus
    customer_name: str | None = None
    customer_phone: str = ""
    requires_payment: bool
    payment_status: str
    payment_method: str | None
    subtotal: float
    tax: float
    discount: float
    total: float
    details: dict[str, Any]
    items: list[EngagementItemRead]
    created_at: datetime
    updated_at: datetime


class EngagementStatusUpdate(BaseModel):
    status: EngagementStatus
