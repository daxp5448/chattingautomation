import uuid
from typing import Any

from sqlalchemy import JSON, Boolean, CheckConstraint, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID


class Customer(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "customers"
    __table_args__ = (
        UniqueConstraint("restaurant_id", "phone", name="uq_customer_restaurant_phone"),
        CheckConstraint("loyalty_points >= 0", name="ck_customer_loyalty_points_non_negative"),
    )

    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    phone: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(200))
    address: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    # Hard, unconditional gate for MARKETING-category broadcast campaigns (see
    # app/api/v1/routers/broadcasts.py) -- defaults False ("no consent on file") since
    # every existing row predates this column and Meta's own policy requires opt-in
    # before a MARKETING template can be sent. Not filtered on for UTILITY/AUTHENTICATION
    # campaigns, matching Meta's own category distinction.
    marketing_opt_in: Mapped[bool] = mapped_column(Boolean, default=False)
    # Denormalized running total for fast reads; loyalty_transactions is the source of truth/audit trail.
    loyalty_points: Mapped[int] = mapped_column(Integer, default=0)

    restaurant = relationship("Restaurant", back_populates="customers")
    orders = relationship("Order", back_populates="customer")
    conversation_state = relationship(
        "ConversationState", back_populates="customer", uselist=False, cascade="all, delete-orphan"
    )
    loyalty_transactions = relationship(
        "LoyaltyTransaction", back_populates="customer", cascade="all, delete-orphan"
    )
