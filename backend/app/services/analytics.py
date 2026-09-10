"""Records funnel events for the generic engine -- the data-architecture half of the
"Analytics Foundation" phase (no dashboard/aggregation built here, deliberately; see
app/models/analytics_event.py's docstring for the full rationale and call-site map).

`record_event` only ever calls `session.add(...)` -- it never commits. Every call site
below is already inside a transaction that commits (or rolls back) as a unit with the
rest of that request's work, so an analytics row rides along with the real state change
it describes; it can never be recorded for a state change that itself got rolled back.
"""

import uuid
from typing import Any

from app.models.analytics_event import AnalyticsEvent

# The event vocabulary from the Business OS master plan's "Analytics Foundation" phase.
# FLOW_ABANDONED is deliberately NOT in this module's vocabulary -- "a customer stopped
# responding" can only be detected by a time-based background scan over stale
# GenericConversationState rows, not a synchronous engine hook, and building that scan
# job is out of scope for this pass.
FLOW_STARTED = "FLOW_STARTED"
NODE_VIEWED = "NODE_VIEWED"
BUTTON_CLICKED = "BUTTON_CLICKED"
PRODUCT_VIEWED = "PRODUCT_VIEWED"
PRODUCT_ADDED = "PRODUCT_ADDED"
CART_STARTED = "CART_STARTED"
CHECKOUT_STARTED = "CHECKOUT_STARTED"
PAYMENT_STARTED = "PAYMENT_STARTED"
PAYMENT_COMPLETED = "PAYMENT_COMPLETED"
BOOKING_STARTED = "BOOKING_STARTED"
BOOKING_COMPLETED = "BOOKING_COMPLETED"
LEAD_STARTED = "LEAD_STARTED"
LEAD_COMPLETED = "LEAD_COMPLETED"
HUMAN_HANDOFF = "HUMAN_HANDOFF"
FLOW_COMPLETED = "FLOW_COMPLETED"
# Fired when generic_flow_engine.py's conservative rule-based safety layer (see
# conversational_safety.py) refuses a free-text message -- lets a business owner see
# whether/how often this fires without ever logging the customer's own message text
# here (see `details` at the one call site: only the matched category, never the text).
SAFETY_REFUSAL = "SAFETY_REFUSAL"


def record_event(
    session,
    restaurant_id: uuid.UUID,
    event_type: str,
    *,
    customer_id: uuid.UUID | None = None,
    step_id: str | None = None,
    niche_code: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    session.add(
        AnalyticsEvent(
            restaurant_id=restaurant_id,
            customer_id=customer_id,
            event_type=event_type,
            step_id=step_id,
            niche_code=niche_code,
            details=details or {},
        )
    )
