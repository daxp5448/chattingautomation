import re
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import TemplateCategory, TemplateStatus

# Meta's own naming rule: lowercase letters, digits, underscores only.
_NAME_PATTERN = re.compile(r"^[a-z0-9_]+$")


class WhatsAppTemplateBase(BaseModel):
    name: str = Field(min_length=1, max_length=512)
    category: TemplateCategory
    language: str = Field(min_length=2, max_length=10)
    body_text: str = Field(min_length=1, max_length=1024)
    variable_examples: list[str] = []

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        if not _NAME_PATTERN.match(value):
            raise ValueError("name must be lowercase letters, digits, and underscores only")
        return value


class WhatsAppTemplateCreate(WhatsAppTemplateBase):
    pass


class WhatsAppTemplateUpdate(BaseModel):
    """Only ever applied to a DRAFT/REJECTED template -- see the router's lifecycle
    guard (app/api/v1/routers/whatsapp_templates.py)."""

    name: str | None = Field(default=None, min_length=1, max_length=512)
    category: TemplateCategory | None = None
    language: str | None = Field(default=None, min_length=2, max_length=10)
    body_text: str | None = Field(default=None, min_length=1, max_length=1024)
    variable_examples: list[str] | None = None

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str | None) -> str | None:
        if value is not None and not _NAME_PATTERN.match(value):
            raise ValueError("name must be lowercase letters, digits, and underscores only")
        return value


class WhatsAppTemplateRead(WhatsAppTemplateBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    restaurant_id: uuid.UUID
    meta_template_id: str | None
    status: TemplateStatus
    rejection_reason: str | None
    submitted_at: datetime | None
    last_synced_at: datetime | None
    created_at: datetime
    updated_at: datetime


class WhatsAppTemplateTestSend(BaseModel):
    to_phone: str = Field(min_length=6, max_length=30)
    # Positional values for the template's {{1}}, {{2}}, ... placeholders, in order.
    variable_values: list[str] = []
