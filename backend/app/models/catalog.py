import uuid
from typing import Any

from sqlalchemy import JSON, Boolean, CheckConstraint, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID


class CatalogCategory(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Generic replacement for app/models/category.py, used only by businesses on the
    generic engine (Restaurant.uses_generic_engine=True). Deliberately a separate table
    rather than reusing `categories`: the legacy table/flow must stay completely
    untouched (see generic_flow_engine.py module docstring) -- this is a parallel system,
    not a shared one.
    """

    __tablename__ = "catalog_categories"

    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    visible: Mapped[bool] = mapped_column(Boolean, default=True)
    image_url: Mapped[str | None] = mapped_column(String(1000))

    items = relationship("CatalogItem", back_populates="category", cascade="all, delete-orphan")


class CatalogItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Generic replacement for app/models/product.py. `attributes` carries whatever a
    niche needs (is_veg/spice_level for a restaurant, duration_minutes for a salon
    service, bedrooms/sqft for a listing) as a flexible JSON bag rather than fixed
    columns -- see the architecture review's Part C for why JSONB over an EAV table.
    """

    __tablename__ = "catalog_items"
    __table_args__ = (
        CheckConstraint("price IS NULL OR price >= 0", name="ck_catalog_item_price_non_negative"),
    )

    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("catalog_categories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(String(2000))
    images: Mapped[list[str]] = mapped_column(JSON, default=list)

    # Nullable: an inquiry-type niche (real estate, jewellers-by-default) commonly shows
    # "starting from"/"on request" rather than one fixed number -- see price_type.
    price: Mapped[float | None] = mapped_column(Numeric(12, 2))
    # fixed | starting_from | per_hour | on_request | free -- validated at the schema
    # layer (a plain string here, not a DB enum, since this list may grow per niche
    # without a migration).
    price_type: Mapped[str] = mapped_column(String(20), default="fixed")

    available: Mapped[bool] = mapped_column(Boolean, default=True)
    is_featured: Mapped[bool] = mapped_column(Boolean, default=False)
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    stock_quantity: Mapped[int | None] = mapped_column(Integer)

    attributes: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    category = relationship("CatalogCategory", back_populates="items")
