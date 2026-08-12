import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import BroadcastRecipientStatus, BroadcastStatus


class BroadcastCampaignCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    template_id: uuid.UUID
    segment_tags: list[str] = []
    variable_template: list[str] = []
    scheduled_at: datetime | None = None


class BroadcastCampaignUpdate(BaseModel):
    """Only ever applied to a DRAFT campaign -- see the router's lifecycle guard
    (app/api/v1/routers/broadcasts.py)."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    template_id: uuid.UUID | None = None
    segment_tags: list[str] | None = None
    variable_template: list[str] | None = None
    scheduled_at: datetime | None = None


class BroadcastCampaignRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    restaurant_id: uuid.UUID
    template_id: uuid.UUID
    name: str
    segment_tags: list[str]
    variable_template: list[str]
    status: BroadcastStatus
    scheduled_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    total_recipients: int
    sent_count: int
    failed_count: int
    failure_reason: str | None
    created_at: datetime
    updated_at: datetime


class BroadcastRecipientRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    campaign_id: uuid.UUID
    customer_id: uuid.UUID
    status: BroadcastRecipientStatus
    error_reason: str | None
    sent_at: datetime | None


class SegmentPreview(BaseModel):
    matching_customers: int
