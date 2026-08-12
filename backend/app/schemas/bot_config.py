import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class BotMessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    restaurant_id: uuid.UUID
    key: str
    content: str
    created_at: datetime
    updated_at: datetime


class BotMessageUpsert(BaseModel):
    key: str = Field(max_length=100)
    content: str = Field(max_length=2000)


class BotButtonBase(BaseModel):
    title: str = Field(max_length=100)
    emoji: str | None = None
    action: str = Field(max_length=100)
    next_flow: str | None = None
    visible: bool = True
    display_order: int = 0


class BotButtonCreate(BotButtonBase):
    pass


class BotButtonUpdate(BaseModel):
    title: str | None = None
    emoji: str | None = None
    action: str | None = None
    next_flow: str | None = None
    visible: bool | None = None
    display_order: int | None = None


class BotButtonRead(BotButtonBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    restaurant_id: uuid.UUID
