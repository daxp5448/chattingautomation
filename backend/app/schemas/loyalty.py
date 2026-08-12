import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import LoyaltyReason


class LoyaltyTransactionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    customer_id: uuid.UUID
    order_id: uuid.UUID | None
    points_delta: int
    reason: LoyaltyReason
    created_at: datetime


class LoyaltySettings(BaseModel):
    points_per_currency_unit: float = Field(default=0.1, ge=0)
    redemption_value_per_point: float = Field(default=1.0, ge=0)


class LoyaltyRedeemRequest(BaseModel):
    points: int = Field(gt=0)
