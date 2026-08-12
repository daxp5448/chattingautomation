import uuid
from typing import Any

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID
from app.models.enums import EngagementStatus, EngagementType


class Engagement(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Generic replacement for app/models/order.py -- one "thing that happened" record
    covering all 4 action types (see EngagementType). `type` decides which of the
    optional fields below are meaningful:
      - order/purchase: `items` (see EngagementItem) + subtotal/tax/discount/total
      - inquiry: `details` holds the free-text message/lead context, no items/payment
      - appointment: `details` holds {staff_id, slot_start, slot_end}
      - booking: `details` holds {check_in, check_out, guests, room_item_id}
    """

    __tablename__ = "engagements"
    __table_args__ = (
        CheckConstraint("subtotal >= 0", name="ck_engagement_subtotal_non_negative"),
        CheckConstraint("tax >= 0", name="ck_engagement_tax_non_negative"),
        CheckConstraint("discount >= 0", name="ck_engagement_discount_non_negative"),
        CheckConstraint("total >= 0", name="ck_engagement_total_non_negative"),
    )

    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    branch_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("branches.id", ondelete="SET NULL"), nullable=True, index=True
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    reference_number: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)

    type: Mapped[EngagementType] = mapped_column(nullable=False, index=True)
    status: Mapped[EngagementStatus] = mapped_column(default=EngagementStatus.NEW, nullable=False, index=True)

    requires_payment: Mapped[bool] = mapped_column(default=False)
    payment_status: Mapped[str] = mapped_column(String(20), default="pending")
    payment_method: Mapped[str | None] = mapped_column(String(20))
    gateway_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    subtotal: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    tax: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    discount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    total: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)

    # Type-specific structured data -- see class docstring. Free-form text a customer
    # entered (inquiry notes, repair device model, vehicle number) also lives here under
    # a `notes`/`free_text` key rather than a dedicated column, since which fields apply
    # varies per niche, not per type.
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    restaurant = relationship("Restaurant")
    customer = relationship("Customer")
    items = relationship("EngagementItem", back_populates="engagement", cascade="all, delete-orphan")


class EngagementItem(UUIDPrimaryKeyMixin, Base):
    """Generic replacement for app/models/order.py::OrderItem -- only populated for
    order/purchase-type engagements (a cart line). Snapshots name/price at the moment
    added, same reasoning as OrderItem: a catalog price change must never retroactively
    change an existing engagement's total.
    """

    __tablename__ = "engagement_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_engagement_item_quantity_positive"),
        CheckConstraint("price_snapshot >= 0", name="ck_engagement_item_price_snapshot_non_negative"),
    )

    engagement_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("engagements.id", ondelete="CASCADE"), nullable=False, index=True
    )
    catalog_item_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("catalog_items.id", ondelete="RESTRICT"), nullable=False
    )
    name_snapshot: Mapped[str] = mapped_column(String(200), nullable=False)
    price_snapshot: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    engagement = relationship("Engagement", back_populates="items")
