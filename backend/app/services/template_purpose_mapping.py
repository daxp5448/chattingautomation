"""Niche-aware WhatsApp Message Template recommendation for Broadcast Campaigns -- the
one place templates are actually usable (Message Templates exist for business-initiated
sends OUTSIDE the 24-hour session window; the live bot conversation always happens
INSIDE that window and already uses free-form interactive messages, so templates are
never selected for a live flow step -- see generic_flow_engine.py, untouched by this
module).

Templates are strictly per-tenant (WhatsAppTemplate.restaurant_id), never shared across
businesses, so "best available template" only ever searches the calling tenant's own
rows -- there is no cross-tenant niche template pool to match against, only a static,
platform-wide list of which TemplatePurposes are typically useful for a given niche
(this file), scored against what that ONE tenant actually has approved.
"""

from app.models.enums import TemplatePurpose, TemplateStatus
from app.models.whatsapp_template import WhatsAppTemplate

# One ordered list per niche code -- order is priority (earlier = more central to that
# niche's typical Broadcast Campaign use cases), matching the per-niche breakdown in the
# original spec, collapsed onto the shared TemplatePurpose vocabulary. A niche code not
# present here (or None, e.g. a Custom/Legacy-engine business with no niche_type) falls
# back to every purpose (see recommend_templates) rather than recommending nothing.
NICHE_RECOMMENDED_PURPOSES: dict[str, list[TemplatePurpose]] = {
    "restaurant": [
        TemplatePurpose.OFFER, TemplatePurpose.ORDER_CONFIRMATION, TemplatePurpose.CONFIRMATION,
    ],
    "jewellers": [
        TemplatePurpose.PRODUCT_SHOWCASE, TemplatePurpose.ENQUIRY, TemplatePurpose.APPOINTMENT,
        TemplatePurpose.FOLLOW_UP, TemplatePurpose.OFFER,
    ],
    "salon": [
        TemplatePurpose.APPOINTMENT, TemplatePurpose.CONFIRMATION, TemplatePurpose.REMINDER,
        TemplatePurpose.FOLLOW_UP,
    ],
    "gym": [
        TemplatePurpose.OFFER, TemplatePurpose.ENQUIRY, TemplatePurpose.CONFIRMATION,
        TemplatePurpose.FOLLOW_UP,
    ],
    "hotel": [
        TemplatePurpose.PRODUCT_SHOWCASE, TemplatePurpose.ENQUIRY, TemplatePurpose.BOOKING,
        TemplatePurpose.CONFIRMATION,
    ],
    "real_estate": [
        TemplatePurpose.PRODUCT_SHOWCASE, TemplatePurpose.ENQUIRY, TemplatePurpose.APPOINTMENT,
        TemplatePurpose.FOLLOW_UP,
    ],
    "automobile": [
        TemplatePurpose.APPOINTMENT, TemplatePurpose.CONFIRMATION, TemplatePurpose.REMINDER,
    ],
    "clinic": [
        TemplatePurpose.APPOINTMENT, TemplatePurpose.CONFIRMATION, TemplatePurpose.REMINDER,
        TemplatePurpose.FOLLOW_UP,
    ],
    "education": [
        TemplatePurpose.ENQUIRY, TemplatePurpose.CONFIRMATION, TemplatePurpose.FOLLOW_UP,
    ],
    "electronics": [
        TemplatePurpose.PRODUCT_SHOWCASE, TemplatePurpose.ENQUIRY, TemplatePurpose.ORDER_CONFIRMATION,
    ],
    "grocery": [
        TemplatePurpose.PRODUCT_SHOWCASE, TemplatePurpose.ORDER_CONFIRMATION, TemplatePurpose.OFFER,
    ],
    "retail": [
        TemplatePurpose.PRODUCT_SHOWCASE, TemplatePurpose.ENQUIRY, TemplatePurpose.ORDER_CONFIRMATION,
        TemplatePurpose.OFFER,
    ],
}


def recommend_templates(
    templates: list[WhatsAppTemplate], niche_code: str | None
) -> dict[TemplatePurpose, WhatsAppTemplate | None]:
    """For every purpose this niche typically needs (every TemplatePurpose if the niche
    code is unknown/None -- the generic-business fallback), pick this tenant's own best
    APPROVED template with a matching `purpose`. Never fabricates a template and never
    raises: a purpose with no approved match maps to None, left for the Owner to create
    one. First-approved-match wins on a tie (stable, no randomness) -- there is only ever
    one recommendation slot per purpose, so a tie only matters for which template a
    tenant with two templates of the same purpose sees suggested first.
    """
    purposes = NICHE_RECOMMENDED_PURPOSES.get(niche_code or "") or list(TemplatePurpose)
    approved_by_purpose: dict[TemplatePurpose, WhatsAppTemplate] = {}
    for template in templates:
        if template.status != TemplateStatus.APPROVED:
            continue
        approved_by_purpose.setdefault(template.purpose, template)

    return {purpose: approved_by_purpose.get(purpose) for purpose in purposes}
