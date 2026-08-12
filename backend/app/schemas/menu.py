import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CategoryBase(BaseModel):
    name: str
    display_order: int = 0
    visible: bool = True
    icon: str | None = None
    color: str | None = None


class CategoryCreate(CategoryBase):
    pass


class CategoryUpdate(BaseModel):
    name: str | None = None
    display_order: int | None = None
    visible: bool | None = None
    icon: str | None = None
    color: str | None = None


class CategoryRead(CategoryBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    restaurant_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class AddonCreate(BaseModel):
    name: str
    price: float = 0


class AddonRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    price: float


class ProductBase(BaseModel):
    name: str
    category_id: uuid.UUID
    image_url: str | None = None
    gallery: list[str] = []
    description: str | None = None
    price: float = Field(ge=0)
    discount_price: float | None = Field(default=None, ge=0)
    gst_percent: float = Field(default=0, ge=0, le=100)
    preparation_time_minutes: int | None = None
    is_veg: bool = True
    available: bool = True
    is_featured: bool = False
    tags: list[str] = []
    stock_quantity: int | None = Field(default=None, ge=0)
    ingredients: str | None = None
    nutritional_info: dict[str, Any] = {}
    branch_ids: list[uuid.UUID] = []
    addon_ids: list[uuid.UUID] = []

    @model_validator(mode="after")
    def _validate_discount_price(self) -> "ProductBase":
        if self.discount_price is not None and self.discount_price >= self.price:
            raise ValueError("discount_price must be less than price")
        return self


class ProductCreate(ProductBase):
    pass


class ProductUpdate(BaseModel):
    name: str | None = None
    category_id: uuid.UUID | None = None
    image_url: str | None = None
    gallery: list[str] | None = None
    description: str | None = None
    price: float | None = None
    discount_price: float | None = None
    gst_percent: float | None = None
    preparation_time_minutes: int | None = None
    is_veg: bool | None = None
    available: bool | None = None
    is_featured: bool | None = None
    tags: list[str] | None = None
    stock_quantity: int | None = None
    ingredients: str | None = None
    nutritional_info: dict[str, Any] | None = None
    branch_ids: list[uuid.UUID] | None = None
    addon_ids: list[uuid.UUID] | None = None


class ProductRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    restaurant_id: uuid.UUID
    category_id: uuid.UUID
    name: str
    image_url: str | None
    gallery: list[str]
    description: str | None
    price: float
    discount_price: float | None
    gst_percent: float
    preparation_time_minutes: int | None
    is_veg: bool
    available: bool
    tags: list[str]
    stock_quantity: int | None
    ingredients: str | None
    nutritional_info: dict[str, Any]
    created_at: datetime
    updated_at: datetime
