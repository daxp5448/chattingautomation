import uuid
from typing import Any

from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID


class AnalyticsEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The funnel-analytics data-architecture foundation (Business OS master plan,
    "Analytics Foundation" phase) -- deliberately just an append-only event log, no
    dashboard/aggregation built on top of it yet. Recorded from a handful of existing
    choke points in app/services/generic_flow_engine.py (`_render_step` for every step
    shown to a customer, `_process_input`/`_run_action` for taps and cart mutations,
    `_create_engagement` for order/booking/appointment/inquiry start+completion,
    human_handoff's render branch) plus app/api/v1/routers/generic_payments.py's webhook
    (payment confirmation) -- see record_analytics_event's docstring for the exact
    event_type vocabulary and why FLOW_ABANDONED is NOT emitted here (it needs a
    time-based background scan, not a synchronous engine hook, and is out of scope for
    this pass).

    Legacy-engine (flow_engine.py) traffic does not emit these -- Prince Corner and any
    other Restaurant.uses_generic_engine=False business must stay completely unaffected
    by generic-engine-only work, same hard constraint as everywhere else in this project.
    """

    __tablename__ = "analytics_events"

    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("customers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # Which flow step this event happened at/because of, if any (e.g. NODE_VIEWED's own
    # step, or the step a BUTTON_CLICKED tap was made on) -- lets a future funnel report
    # group "how many customers reached step X" without re-deriving it from the raw
    # Message transcript.
    step_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    niche_code: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    # Small, event-specific extra context (e.g. {"reply_id": "category:<uuid>"} for a
    # BUTTON_CLICKED, {"reference_number": "..."} for a *_COMPLETED) -- deliberately a
    # free JSON bag rather than a wide fixed-column table, same reasoning as
    # CatalogItem.attributes: the exact useful payload differs per event_type and niche,
    # and a dashboard built on this later can read whatever it needs out of it.
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
