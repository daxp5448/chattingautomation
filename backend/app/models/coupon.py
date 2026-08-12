import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, utcnow
from app.db.types import GUID
from app.models.enums import CouponType


class Coupon(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "coupons"
    __table_args__ = (
        UniqueConstraint("restaurant_id", "code", name="uq_coupon_restaurant_code"),
        CheckConstraint("value >= 0", name="ck_coupon_value_non_negative"),
    )

    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    type: Mapped[CouponType] = mapped_column(nullable=False)
    value: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    min_order_amount: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    max_discount_amount: Mapped[float | None] = mapped_column(Numeric(10, 2))
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    usage_limit: Mapped[int | None] = mapped_column(Integer)
    usage_limit_per_customer: Mapped[int | None] = mapped_column(Integer)
    first_order_only: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_apply: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    restaurant = relationship("Restaurant", back_populates="coupons")
    orders = relationship("Order", back_populates="coupon")
    redemptions = relationship("CouponRedemption", back_populates="coupon", cascade="all, delete-orphan")


class CouponRedemption(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "coupon_redemptions"
    __table_args__ = (
        # DB-level backstop against double-redemption for the same order regardless of
        # locking at the application layer (e.g. two racing requests both passing the
        # in-app eligibility check before either commits).
        UniqueConstraint("coupon_id", "order_id", name="uq_coupon_redemption_coupon_order"),
    )

    coupon_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("coupons.id", ondelete="CASCADE"), nullable=False, index=True
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    discount_amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    redeemed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    coupon = relationship("Coupon", back_populates="redemptions")
