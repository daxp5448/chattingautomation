import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ApiEndpointBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    url: str = Field(min_length=1, max_length=2000)
    method: str = "POST"
    allowed_headers: dict[str, str] = {}
    capturable_context_keys: list[str] = []
    timeout_seconds: float = Field(default=5.0, gt=0, le=5.0)
    response_size_cap_bytes: int = Field(default=65536, gt=0, le=1_000_000)
    is_active: bool = True


class ApiEndpointCreate(ApiEndpointBase):
    pass


class ApiEndpointUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    url: str | None = Field(default=None, min_length=1, max_length=2000)
    method: str | None = None
    allowed_headers: dict[str, str] | None = None
    capturable_context_keys: list[str] | None = None
    timeout_seconds: float | None = Field(default=None, gt=0, le=5.0)
    response_size_cap_bytes: int | None = Field(default=None, gt=0, le=1_000_000)
    is_active: bool | None = None


class ApiEndpointRead(ApiEndpointBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
