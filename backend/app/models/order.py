import uuid
from typing import Any

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID
from app.models.enums import FulfillmentType, OrderStatus, PaymentMethod, PaymentStatus


class Order(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint("subtotal >= 0", name="ck_order_subtotal_non_negative"),
        CheckConstraint("tax >= 0", name="ck_order_tax_non_negative"),
        CheckConstraint("discount >= 0", name="ck_order_discount_non_negative"),
        CheckConstraint("delivery_charge >= 0", name="ck_order_delivery_charge_non_negative"),
        CheckConstraint("total >= 0", name="ck_order_total_non_negative"),
    )

    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    branch_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    coupon_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("coupons.id", ondelete="SET NULL"), nullable=True
    )
    order_number: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)

    status: Mapped[OrderStatus] = mapped_column(default=OrderStatus.PENDING, nullable=False, index=True)
    payment_status: Mapped[PaymentStatus] = mapped_column(default=PaymentStatus.PENDING, nullable=False)
    payment_method: Mapped[PaymentMethod] = mapped_column(default=PaymentMethod.COD, nullable=False)
    fulfillment_type: Mapped[FulfillmentType] = mapped_column(default=FulfillmentType.DELIVERY, nullable=False)
    # Gateway-specific payment reference (e.g. Razorpay payment link/order id). Kept generic
    # so a future gateway doesn't need its own dedicated columns.
    gateway_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    delivery_address: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    subtotal: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, default=0)
    tax: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, default=0)
    delivery_charge: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, default=0)
    discount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, default=0)
    total: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, default=0)
    notes: Mapped[str | None] = mapped_column(String(1000))

    invoice_number: Mapped[str | None] = mapped_column(String(50), unique=True)
    invoice_url: Mapped[str | None] = mapped_column(String(1000))

    restaurant = relationship("Restaurant", back_populates="orders")
    branch = relationship("Branch", back_populates="orders")
    customer = relationship("Customer", back_populates="orders")
    coupon = relationship("Coupon", back_populates="orders")
    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")


class OrderItem(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "order_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_order_item_quantity_positive"),
        CheckConstraint("price_snapshot >= 0", name="ck_order_item_price_snapshot_non_negative"),
    )

    order_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    name_snapshot: Mapped[str] = mapped_column(String(200), nullable=False)
    price_snapshot: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    addons_snapshot: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)

    order = relationship("Order", back_populates="items")
