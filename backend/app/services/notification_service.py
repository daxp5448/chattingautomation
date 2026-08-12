"""One shared staff-notification function every generic-engine niche calls at the end of
its flow -- see app/services/generic_flow_engine.py::_Engine._create_engagement. Keyed
only off `engagement.type`, never off niche, so a new niche template needs zero code
here -- exactly the "notification module is generic, not niche-specific" requirement.
"""

import logging

from app.core.security import decrypt_secret
from app.models.customer import Customer
from app.models.engagement import Engagement
from app.models.enums import EngagementType
from app.models.restaurant import Restaurant
from app.services.whatsapp_client import OutboundMessage, WhatsAppSender

logger = logging.getLogger(__name__)

_SUBJECT_BY_TYPE = {
    EngagementType.ORDER: "New order",
    EngagementType.INQUIRY: "New inquiry",
    EngagementType.APPOINTMENT: "New appointment",
    EngagementType.BOOKING: "New booking",
}


def _summary_line(engagement: Engagement, customer: Customer) -> str:
    who = customer.name or customer.phone
    if engagement.type == EngagementType.ORDER:
        return f"{len(engagement.items)} item(s), total {engagement.total}"
    if engagement.type == EngagementType.APPOINTMENT:
        d = engagement.details or {}
        return f"{d.get('date_label', d.get('date', ''))} at {d.get('time', '')}"
    if engagement.type == EngagementType.BOOKING:
        d = engagement.details or {}
        return f"{d.get('check_in', '')} to {d.get('check_out', '')}, {d.get('guests_label', '')}"
    d = engagement.details or {}
    return d.get("note") or "See conversation for details"


async def notify_business(session, sender: WhatsAppSender, restaurant: Restaurant, engagement: Engagement, customer: Customer) -> None:
    if not restaurant.staff_notification_number:
        logger.info(
            "No staff_notification_number configured for restaurant %s; skipping staff notification for engagement %s",
            restaurant.id,
            engagement.reference_number,
        )
        return

    subject = _SUBJECT_BY_TYPE.get(engagement.type, "New engagement")
    who = customer.name or customer.phone
    body = (
        f"📩 {subject} — {restaurant.name}\n"
        f"Ref: {engagement.reference_number}\n"
        f"From: {who} ({customer.phone})\n"
        f"{_summary_line(engagement, customer)}"
    )
    access_token = decrypt_secret(restaurant.whatsapp_access_token_encrypted or "")
    try:
        await sender.send(
            restaurant.whatsapp_phone_number_id or "",
            access_token,
            OutboundMessage.text(restaurant.staff_notification_number, body),
        )
    except Exception:
        # A failed staff notification must never fail the customer's own flow -- the
        # engagement is already committed by the time this runs (see
        # generic_flow_engine.py::_create_engagement); this is best-effort, same
        # reasoning as every other outbound send in this codebase.
        logger.warning("Failed to send staff notification for engagement %s", engagement.reference_number, exc_info=True)
