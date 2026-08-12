import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class FaqEntryBase(BaseModel):
    trigger_keywords: list[str] = Field(max_length=20)
    answer: str = Field(max_length=2000)
    display_order: int = 0
    is_active: bool = True


class FaqEntryCreate(FaqEntryBase):
    pass


class FaqEntryUpdate(BaseModel):
    trigger_keywords: list[str] | None = None
    answer: str | None = None
    display_order: int | None = None
    is_active: bool | None = None


class FaqEntryRead(FaqEntryBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    restaurant_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
