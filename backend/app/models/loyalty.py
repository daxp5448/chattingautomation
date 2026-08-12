import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UUIDPrimaryKeyMixin, utcnow
from app.db.types import GUID
from app.models.enums import LoyaltyReason


class LoyaltyTransaction(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "loyalty_transactions"

    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    order_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("orders.id", ondelete="SET NULL"), nullable=True
    )
    points_delta: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[LoyaltyReason] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    customer = relationship("Customer", back_populates="loyalty_transactions")
