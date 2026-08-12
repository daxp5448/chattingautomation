import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.enums import FulfillmentType, OrderStatus


class DisplayDeviceCreate(BaseModel):
    name: str
    branch_id: uuid.UUID | None = None


class DisplayDeviceCreateResponse(BaseModel):
    """Returned only from the create endpoint -- the one and only place the raw token
    is ever visible. Every other endpoint returns DisplayDeviceRead instead."""

    id: uuid.UUID
    name: str
    token: str


class DisplayDeviceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    branch_id: uuid.UUID | None
    created_at: datetime
    revoked_at: datetime | None


class PosOrderItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name_snapshot: str
    quantity: int


class PosOrderRead(BaseModel):
    """Deliberately minimal, hand-maintained subset of order fields for an
    unauthenticated (token-only) kitchen/counter display -- excludes customer phone,
    customer name, payment/gateway metadata, and anything else not needed to run a
    kitchen screen. Defined independently of OrderRead so a future field added there
    doesn't silently leak through this endpoint."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    order_number: str
    status: OrderStatus
    fulfillment_type: FulfillmentType
    items: list[PosOrderItemRead]
    created_at: datetime
    total: float
