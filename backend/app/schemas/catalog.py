import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict


class CatalogCategoryCreate(BaseModel):
    name: str
    display_order: int = 0
    image_url: str | None = None


class CatalogCategoryUpdate(BaseModel):
    name: str | None = None
    display_order: int | None = None
    visible: bool | None = None
    image_url: str | None = None


class CatalogCategoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    display_order: int
    visible: bool
    image_url: str | None


class CatalogItemCreate(BaseModel):
    category_id: uuid.UUID
    name: str
    description: str | None = None
    price: float | None = None
    price_type: str = "fixed"
    images: list[str] = []
    attributes: dict[str, Any] = {}


class CatalogItemUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    price: float | None = None
    price_type: str | None = None
    images: list[str] | None = None
    available: bool | None = None
    is_featured: bool | None = None
    stock_quantity: int | None = None
    attributes: dict[str, Any] | None = None


class CatalogItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    category_id: uuid.UUID
    name: str
    description: str | None
    price: float | None
    price_type: str
    images: list[str]
    available: bool
    is_featured: bool
    display_order: int
    stock_quantity: int | None
    attributes: dict[str, Any]
