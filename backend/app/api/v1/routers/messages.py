"""A single shared preview endpoint for the Message Management screens (both the
Super-Admin niche-template editor and a business's own flow-message editor, see
niche_templates.py / flow_definitions.py) -- renders {{variable}} substitution through
the exact same app/services/template_engine.py the live conversation engine uses, so
"what the admin sees in preview" and "what the customer actually receives" can never
drift apart.
"""

from fastapi import APIRouter

from app.core.deps import CurrentUser
from app.schemas.message_catalog import MessagePreviewRequest, MessagePreviewResponse
from app.services.template_engine import render_template

router = APIRouter(prefix="/messages", tags=["messages"])

# Realistic stand-in values for every variable a flow message might reference (see
# generic_flow_engine.py::_prompt_text for the fixed ones, plus whatever a niche's own
# context capture_keys add) -- used whenever the caller doesn't supply their own sample
# `variables`, so a brand-new message can be previewed before any real conversation data
# exists to render it against.
_SAMPLE_VARIABLES = {
    "business_name": "Sample Business",
    "restaurant_name": "Sample Business",
    "customer_name": "Priya Sharma",
    "currency": "₹",
    "date": "13 Aug 2026",
    "time": "06:45 PM",
    "order_id": "SB-2026-000123",
    "booking_id": "SB-2026-000123",
    "last_reference_number": "SB-2026-000123",
    "total": "999",
    "last_total": "999.00",
    "quantity": "2",
    "address": "221B Baker Street, Bandra West",
    "service_name": "Sample Service",
    "product_name": "Sample Product",
    "pending_item_name": "Sample Product",
    "pending_item_price": "₹999",
    "category_id_label": "Sample Category",
    "item_id_label": "Sample Item",
    "staff_id_label": "Sample Staff",
    "date_label": "Today",
    "time_label": "10:00 AM",
    "cart_summary": "Sample Product x 2\n₹1,998",
    "cart_total": "1998",
    "payment_link_url": "",
}


@router.post("/preview", response_model=MessagePreviewResponse)
async def preview_message(payload: MessagePreviewRequest, user: CurrentUser) -> MessagePreviewResponse:
    context = {**_SAMPLE_VARIABLES, **(payload.variables or {})}
    return MessagePreviewResponse(rendered=render_template(payload.text, context))
