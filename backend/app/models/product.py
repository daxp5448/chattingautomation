import uuid
from typing import Any

from sqlalchemy import JSON, Boolean, CheckConstraint, Column, ForeignKey, Integer, Numeric, String, Table
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID

product_branch = Table(
    "product_branch",
    Base.metadata,
    Column("product_id", GUID(), ForeignKey("products.id", ondelete="CASCADE"), primary_key=True),
    Column("branch_id", GUID(), ForeignKey("branches.id", ondelete="CASCADE"), primary_key=True),
)

product_addon = Table(
    "product_addon",
    Base.metadata,
    Column("product_id", GUID(), ForeignKey("products.id", ondelete="CASCADE"), primary_key=True),
    Column("addon_id", GUID(), ForeignKey("addons.id", ondelete="CASCADE"), primary_key=True),
)


class Product(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("price >= 0", name="ck_product_price_non_negative"),
        # Nullable-safe: SQL CHECK treats NULL as passing (the row still satisfies the
        # constraint), so an explicit "IS NULL OR ..." isn't strictly required for
        # correctness here, but it's spelled out for readability.
        CheckConstraint("discount_price IS NULL OR discount_price >= 0", name="ck_product_discount_price_non_negative"),
        CheckConstraint("stock_quantity IS NULL OR stock_quantity >= 0", name="ck_product_stock_quantity_non_negative"),
    )

    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("categories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    image_url: Mapped[str | None] = mapped_column(String(500))
    gallery: Mapped[list[str]] = mapped_column(JSON, default=list)
    description: Mapped[str | None] = mapped_column(String(2000))
    price: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    discount_price: Mapped[float | None] = mapped_column(Numeric(10, 2))
    gst_percent: Mapped[float] = mapped_column(Numeric(5, 2), default=0)
    preparation_time_minutes: Mapped[int | None] = mapped_column(Integer)
    is_veg: Mapped[bool] = mapped_column(Boolean, default=True)
    available: Mapped[bool] = mapped_column(Boolean, default=True)
    is_featured: Mapped[bool] = mapped_column(Boolean, default=False)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    stock_quantity: Mapped[int | None] = mapped_column(Integer)
    ingredients: Mapped[str | None] = mapped_column(String(2000))
    nutritional_info: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    restaurant = relationship("Restaurant", back_populates="products")
    category = relationship("Category", back_populates="products")
    branches = relationship("Branch", secondary=product_branch)
    addons = relationship("Addon", secondary=product_addon, back_populates="products")


class Addon(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "addons"

    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    price: Mapped[float] = mapped_column(Numeric(10, 2), default=0)

    products = relationship("Product", secondary=product_addon, back_populates="addons")
