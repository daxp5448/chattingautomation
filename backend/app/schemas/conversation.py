import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import MessageDirection, MessageSender


class MessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    customer_id: uuid.UUID
    direction: MessageDirection
    sent_by: MessageSender
    staff_user_id: uuid.UUID | None
    body: str
    created_at: datetime


class StaffReplyCreate(BaseModel):
    body: str = Field(min_length=1, max_length=4096)


class ConversationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    customer_id: uuid.UUID
    customer_name: str | None
    customer_phone: str
    last_message_at: datetime | None
    last_message_preview: str | None
