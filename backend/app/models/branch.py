import uuid
from typing import Any

from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID
from app.models.enums import BranchStatus


class Branch(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "branches"

    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    address: Mapped[str | None] = mapped_column(String(500))
    google_map_link: Mapped[str | None] = mapped_column(String(500))
    latitude: Mapped[float | None]
    longitude: Mapped[float | None]
    phone: Mapped[str | None] = mapped_column(String(30))
    delivery_radius_km: Mapped[float | None]
    opening_hours: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    manager_name: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[BranchStatus] = mapped_column(default=BranchStatus.OPEN, nullable=False)
    estimated_delivery_time_minutes: Mapped[int | None]
    kitchen_name: Mapped[str | None] = mapped_column(String(200))
    printer_name: Mapped[str | None] = mapped_column(String(200))

    restaurant = relationship("Restaurant", back_populates="branches")
    orders = relationship("Order", back_populates="branch")
