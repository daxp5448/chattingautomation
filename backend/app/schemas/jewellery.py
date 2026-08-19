import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class JewelleryDesignRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    restaurant_id: uuid.UUID
    material: str
    category: str
    name: str
    design_code: str | None
    image_key: str
    thumbnail_key: str | None
    source: str
    display_order: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class JewelleryDesignPage(BaseModel):
    total: int
    offset: int
    limit: int
    items: list[JewelleryDesignRead]
