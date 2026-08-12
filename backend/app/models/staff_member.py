import uuid
from typing import Any

from sqlalchemy import JSON, Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID


class StaffMember(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A bookable person for appointment-type niches with staff selection on (salon
    stylist, doctor, agent) -- distinct from app/models/user.py::User, which is a login
    account. A StaffMember doesn't need or get a login; a business can list a stylist
    here who never touches the admin panel.
    """

    __tablename__ = "staff_members"

    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    branch_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("branches.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    title: Mapped[str | None] = mapped_column(String(200))  # e.g. "Senior Stylist", "Dr."
    photo_url: Mapped[str | None] = mapped_column(String(1000))
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    # {"mon": [["09:00","18:00"]], "tue": [...], ...} -- per-day working windows this
    # staff member is bookable in, minus whatever's already booked (see
    # app/services/generic_flow_engine.py::_available_slots). Falls back to the
    # business's own working hours if unset.
    working_hours: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
