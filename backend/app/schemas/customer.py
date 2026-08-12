import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class CustomerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    restaurant_id: uuid.UUID
    phone: str
    name: str | None
    email: str | None
    address: dict[str, Any]
    tags: list[str]
    is_blocked: bool
    marketing_opt_in: bool
    loyalty_points: int
    created_at: datetime
    updated_at: datetime


class CustomerReadLimited(BaseModel):
    """Same as CustomerRead but with direct PII (phone/email/address) stripped out --
    served to the `kitchen` role, which needs to see order/prep-relevant customer info
    (name, loyalty status) but has no operational need for contact details. See
    app/api/v1/routers/customers.py::list_customers."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    restaurant_id: uuid.UUID
    name: str | None
    tags: list[str]
    is_blocked: bool
    loyalty_points: int
    created_at: datetime
    updated_at: datetime


class CustomerUpdate(BaseModel):
    name: str | None = None
    email: str | None = None
    address: dict[str, Any] | None = None
    tags: list[str] | None = None
    is_blocked: bool | None = None
    marketing_opt_in: bool | None = None
