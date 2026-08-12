import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID
from app.models.enums import BroadcastRecipientStatus, BroadcastStatus


class BroadcastCampaign(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A bulk WhatsApp send to a segment of a restaurant's own customers, using an
    APPROVED WhatsAppTemplate (Meta requires this for any business-initiated message
    outside the 24-hour customer-service window). See app/tasks/broadcast_sender.py for
    the actual send loop and app/api/v1/routers/broadcasts.py for the lifecycle.

    `BroadcastRecipient` rows are only created when the campaign actually starts (see
    the `start` endpoint), not at creation time -- so editing the segment on a DRAFT
    campaign never has stale recipient rows to reconcile.
    """

    __tablename__ = "broadcast_campaigns"

    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    template_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("whatsapp_templates.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Empty list = every non-blocked customer -- an explicit, documented convention
    # (not an accidental "forgot to set a segment" footgun), enforced/confirmed at the
    # UI layer with a "this will message ALL N customers" confirmation.
    segment_tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    # Each entry is either a literal string, or the recognized token "{{customer_name}}"
    # resolved per-recipient at send time (see app/tasks/broadcast_sender.py) -- not a
    # general templating language, just this one built-in personalization token plus
    # fixed literals, matching the platform's "don't over-build past what's needed" rule.
    variable_template: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[BroadcastStatus] = mapped_column(default=BroadcastStatus.DRAFT, nullable=False)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Denormalized for cheap dashboard reads -- the authoritative per-recipient detail
    # always lives on BroadcastRecipient; these are updated alongside it, never instead
    # of it. See app/tasks/broadcast_sender.py.
    total_recipients: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sent_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failure_reason: Mapped[str | None] = mapped_column(String(500))


class BroadcastRecipient(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One row per customer targeted by a campaign, snapshotted at `start` time (see
    BroadcastCampaign's docstring). `customer.is_blocked`/anonymized status is
    re-checked immediately before each send (app/tasks/broadcast_sender.py), not just
    once here at snapshot time -- a campaign can take minutes to work through, and a
    customer can withdraw consent or request erasure while it's running.
    """

    __tablename__ = "broadcast_recipients"
    __table_args__ = (
        UniqueConstraint("campaign_id", "customer_id", name="uq_broadcast_recipient_campaign_customer"),
    )

    campaign_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("broadcast_campaigns.id", ondelete="CASCADE"), nullable=False, index=True
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[BroadcastRecipientStatus] = mapped_column(default=BroadcastRecipientStatus.PENDING, nullable=False)
    error_reason: Mapped[str | None] = mapped_column(String(500))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
