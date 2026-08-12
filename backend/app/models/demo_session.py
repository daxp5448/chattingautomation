import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID


class DemoSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Tracks which niche a real WhatsApp phone number is currently trying on the one
    Demo Bot line (see app/services/demo_bot_service.py) -- deliberately NOT scoped per
    demo line (the product spec is one WhatsApp number); adding a second demo line later
    is a small additive follow-up, not designed for here.

    A `Customer`/`GenericConversationState` row can't carry this by itself: those are
    scoped to a single `restaurant_id` (one niche's demo restaurant), but one real phone
    number moves between many niches' demo restaurants over the life of a single "try
    another industry" session, and needs one small row that survives that -- this is it.
    """

    __tablename__ = "demo_sessions"

    customer_phone: Mapped[str] = mapped_column(String(30), nullable=False, unique=True, index=True)
    # NULL = at the industry picker, not yet inside any niche's demo.
    active_restaurant_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("restaurants.id", ondelete="SET NULL"), nullable=True
    )
