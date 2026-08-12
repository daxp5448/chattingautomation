import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ImageVariant(BaseModel):
    key: str
    format: str
    width: int
    height: int
    size_bytes: int


class ImageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    restaurant_id: uuid.UUID
    image_type: str
    catalog_item_id: uuid.UUID | None
    original_width: int
    original_height: int
    original_size_bytes: int
    status: str
    failure_reason: str | None
    crop_box: dict[str, int] | None
    resolution_warning: bool
    low_quality_reason: str | None
    replaced_by_image_id: uuid.UUID | None
    variants: dict[str, ImageVariant]
    created_at: datetime
    updated_at: datetime
    # Populated by the router (not a model column) -- presigned URLs for the original and
    # each ready variant, since the frontend never talks to S3/MinIO directly.
    urls: dict[str, str] = Field(default_factory=dict)


class ImageCropRequest(BaseModel):
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class ImageTypeProfileBase(BaseModel):
    code: str
    label: str
    variant_specs: list[dict[str, Any]]
    max_upload_size_bytes: int = 10 * 1024 * 1024


class ImageTypeProfileCreate(ImageTypeProfileBase):
    pass


class ImageTypeProfileUpdate(BaseModel):
    label: str | None = None
    variant_specs: list[dict[str, Any]] | None = None
    max_upload_size_bytes: int | None = None


class ImageTypeProfileRead(ImageTypeProfileBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
