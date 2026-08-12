import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID


class Category(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "categories"

    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    visible: Mapped[bool] = mapped_column(Boolean, default=True)
    icon: Mapped[str | None] = mapped_column(String(100))
    color: Mapped[str | None] = mapped_column(String(20))

    restaurant = relationship("Restaurant", back_populates="categories")
    products = relationship("Product", back_populates="category")
