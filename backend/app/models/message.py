import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKeyMixin, utcnow
from app.db.types import GUID
from app.models.enums import MessageDirection, MessageSender


class Message(UUIDPrimaryKeyMixin, Base):
    """Conversation transcript log. Phase 1 only tracked current conversation state;
    this persists every inbound/outbound message so staff have context during a
    human handover, and so the Live Chat view can render a transcript.
    """

    __tablename__ = "messages"

    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    direction: Mapped[MessageDirection] = mapped_column(nullable=False)
    sent_by: Mapped[MessageSender] = mapped_column(nullable=False)
    staff_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    body: Mapped[str] = mapped_column(String(4096), nullable=False)
    # Meta's stable per-message id (e.g. "wamid.xxx") for inbound messages, used to make
    # webhook processing idempotent -- Meta may retry a webhook delivery, and this lets us
    # detect and skip a message we've already processed instead of creating a duplicate
    # order. Nullable because outbound (bot/staff) messages never set it.
    wa_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
