import uuid

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID


class RestaurantInvoiceCounter(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One row per (restaurant, Indian financial year), tracking the next sequential
    invoice number to hand out. See app/services/invoice_numbering.py::assign_invoice_number
    for the race-safe get-or-increment logic that reads/writes this table."""

    __tablename__ = "restaurant_invoice_counters"
    __table_args__ = (
        UniqueConstraint("restaurant_id", "financial_year", name="uq_invoice_counter_restaurant_fy"),
    )

    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Indian financial year (April 1 - March 31), e.g. "2026-27".
    financial_year: Mapped[str] = mapped_column(String(10), nullable=False)
    next_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
