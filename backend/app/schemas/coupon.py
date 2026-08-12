import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import CouponType


class CouponBase(BaseModel):
    code: str
    type: CouponType
    value: float = Field(ge=0)
    min_order_amount: float = Field(default=0, ge=0)
    max_discount_amount: float | None = Field(default=None, ge=0)
    starts_at: datetime | None = None
    expires_at: datetime | None = None
    usage_limit: int | None = Field(default=None, ge=1)
    usage_limit_per_customer: int | None = Field(default=None, ge=1)
    first_order_only: bool = False
    auto_apply: bool = False
    is_active: bool = True

    @model_validator(mode="after")
    def _validate_percentage_value(self) -> "CouponBase":
        if self.type == CouponType.PERCENTAGE and self.value > 100:
            raise ValueError("value must be <= 100 for a percentage coupon")
        return self


class CouponCreate(CouponBase):
    pass


class CouponUpdate(BaseModel):
    code: str | None = None
    type: CouponType | None = None
    value: float | None = None
    min_order_amount: float | None = None
    max_discount_amount: float | None = None
    starts_at: datetime | None = None
    expires_at: datetime | None = None
    usage_limit: int | None = None
    usage_limit_per_customer: int | None = None
    first_order_only: bool | None = None
    auto_apply: bool | None = None
    is_active: bool | None = None


class CouponRead(CouponBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    restaurant_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class CouponApplyResult(BaseModel):
    valid: bool
    discount_amount: float = 0
    reason: str | None = None
