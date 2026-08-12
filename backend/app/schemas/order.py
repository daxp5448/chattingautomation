import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models.enums import FulfillmentType, OrderStatus, PaymentMethod, PaymentStatus


class OrderItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    product_id: uuid.UUID
    name_snapshot: str
    price_snapshot: float
    quantity: int
    addons_snapshot: list[dict[str, Any]]


class OrderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    restaurant_id: uuid.UUID
    branch_id: uuid.UUID
    customer_id: uuid.UUID
    coupon_id: uuid.UUID | None
    order_number: str
    status: OrderStatus
    payment_status: PaymentStatus
    payment_method: PaymentMethod
    fulfillment_type: FulfillmentType
    gateway_metadata: dict[str, Any]
    delivery_address: dict[str, Any]
    subtotal: float
    tax: float
    delivery_charge: float
    discount: float
    total: float
    notes: str | None
    invoice_number: str | None
    invoice_url: str | None
    items: list[OrderItemRead]
    created_at: datetime
    updated_at: datetime
    # Not columns on Order itself -- populated from the eager-loaded Customer relationship
    # by the router (see app/api/v1/routers/orders.py::_to_order_read). Defaulted so plain
    # `OrderRead.model_validate(order, from_attributes=True)` doesn't blow up on an Order
    # object that has no same-named attribute, before the router overwrites them.
    customer_name: str | None = None
    customer_phone: str = ""


class OrderStatusUpdate(BaseModel):
    status: OrderStatus
