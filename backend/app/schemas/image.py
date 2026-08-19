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
    catalog_category_id: uuid.UUID | None
    flow_definition_id: uuid.UUID | None
    flow_step_id: str | None
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
    caption: str | None
    alt_text: str | None
    display_order: int
    is_active: bool
    created_at: datetime
    updated_at: datetime
    # Populated by the router (not a model column) -- presigned URLs for the original and
    # each ready variant, since the frontend never talks to S3/MinIO directly.
    urls: dict[str, str] = Field(default_factory=dict)


class CatalogItemRef(BaseModel):
    """The small slice of the owning CatalogItem a Media Library row needs to show
    "used by: <item name>" and link back to it -- not the full CatalogItem schema."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    category_id: uuid.UUID


class ImageLibraryEntry(ImageRead):
    """ImageRead plus the owning catalog item's identity -- used only by
    GET /restaurants/{restaurant_id}/images/library (the restaurant-wide browse/search
    endpoint). None when the image has no resolvable owner (shouldn't happen today, since
    catalog_item_id is currently the only, required owner column, but the outer join this
    is sourced from doesn't assume that)."""

    catalog_item: CatalogItemRef | None = None


class ImageMetadataUpdate(BaseModel):
    """Body for PATCH /restaurants/{id}/images/{image_id} -- metadata-only edit (no
    re-upload, no reprocessing). See app/models/image.py for what each field controls."""

    caption: str | None = None
    alt_text: str | None = None
    display_order: int | None = None
    is_active: bool | None = None


class ImageAttachRequest(BaseModel):
    """Body for POST /restaurants/{id}/images/{image_id}/attach -- the 'Choose From Media
    Library' reuse path: attaches an already-uploaded, already-processed image to a
    (possibly different) owner without re-uploading or reprocessing. Exactly one of the
    three owner shapes must be set -- validated at the router (same rule as the DB's
    ck_image_has_owner constraint).
    """

    catalog_item_id: uuid.UUID | None = None
    catalog_category_id: uuid.UUID | None = None
    flow_definition_id: uuid.UUID | None = None
    flow_step_id: str | None = None
    caption: str | None = None
    alt_text: str | None = None
    display_order: int = 0


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
