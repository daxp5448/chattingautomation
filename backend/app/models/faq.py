import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID


class FaqEntry(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "faq_entries"

    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    trigger_keywords: Mapped[list[str]] = mapped_column(JSON, default=list)
    answer: Mapped[str] = mapped_column(String(2000), nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    restaurant = relationship("Restaurant", back_populates="faq_entries")
