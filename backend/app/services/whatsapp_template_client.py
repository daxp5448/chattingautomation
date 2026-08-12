"""Meta Graph API client for managing a restaurant's own WhatsApp Message Templates --
separate from app/services/whatsapp_client.py's GraphAPIWhatsAppSender because the URL
shape is different (WABA-scoped `/{whatsapp_business_account_id}/message_templates`, not
phone-number-scoped `/{phone_number_id}/messages`) and because the failure semantics
should differ too: every call site here is an interactive Owner/Manager button click in
the dashboard (create/submit/delete a template), not routine customer messaging, so this
raises on failure (mirrors app/services/payment/razorpay.py's RazorpayGateway --
response.raise_for_status(), no retry loop, no swallowing into an {"error": ...} dict) --
the router (app/api/v1/routers/whatsapp_templates.py) catches and translates to a clean
502, the same "only mutate local state after the gateway call actually succeeds" shape
app/api/v1/routers/orders.py's refund endpoint already uses.

Scope: positional {{1}}, {{2}}, ... body-only templates for this pass -- no header/
footer/buttons/named variables. See app/models/whatsapp_template.py for the full scope
note.
"""

from typing import Any

import httpx

from app.core.config import settings
from app.core.security import decrypt_secret
from app.models.restaurant import Restaurant
from app.models.whatsapp_template import WhatsAppTemplate

GRAPH_API_BASE = "https://graph.facebook.com"


def _credentials(restaurant: Restaurant) -> tuple[str, str]:
    waba_id = restaurant.whatsapp_business_account_id or ""
    access_token = decrypt_secret(restaurant.whatsapp_access_token_encrypted or "")
    if not waba_id or not access_token:
        raise ValueError("WhatsApp Business Account is not configured for this restaurant")
    return waba_id, access_token


def _base_url() -> str:
    return f"{GRAPH_API_BASE}/{settings.WHATSAPP_GRAPH_API_VERSION}"


async def create_template(restaurant: Restaurant, template: WhatsAppTemplate) -> dict[str, Any]:
    """Submits `template` for Meta review. Raises on any failure (missing credentials,
    name collision, malformed body, network/5xx) -- never returns a partial success."""
    waba_id, access_token = _credentials(restaurant)
    payload = {
        "name": template.name,
        "category": template.category.value.upper(),
        "language": template.language,
        "components": [
            {
                "type": "BODY",
                "text": template.body_text,
                **(
                    {"example": {"body_text": [template.variable_examples]}}
                    if template.variable_examples
                    else {}
                ),
            }
        ],
    }
    async with httpx.AsyncClient(timeout=10.0, headers={"Authorization": f"Bearer {access_token}"}) as client:
        response = await client.post(f"{_base_url()}/{waba_id}/message_templates", json=payload)
        response.raise_for_status()
        return response.json()


async def get_template_status(restaurant: Restaurant, meta_template_id: str) -> dict[str, Any]:
    """Returns Meta's current view of one template (fields include `status` and, when
    rejected, `rejected_reason`) -- the direct node-fetch shape works for any Graph API
    object id, including a message template's."""
    _waba_id, access_token = _credentials(restaurant)
    async with httpx.AsyncClient(timeout=10.0, headers={"Authorization": f"Bearer {access_token}"}) as client:
        response = await client.get(
            f"{_base_url()}/{meta_template_id}", params={"fields": "status,rejected_reason"}
        )
        response.raise_for_status()
        return response.json()


async def delete_template(restaurant: Restaurant, name: str) -> dict[str, Any]:
    """Meta's delete API is by template `name`, not id. Called BEFORE the local row is
    deleted (see the router) -- deleting local-first would risk permanently orphaning the
    name on Meta's side with no local record left to retry or even notice the orphan."""
    waba_id, access_token = _credentials(restaurant)
    async with httpx.AsyncClient(timeout=10.0, headers={"Authorization": f"Bearer {access_token}"}) as client:
        response = await client.delete(f"{_base_url()}/{waba_id}/message_templates", params={"name": name})
        response.raise_for_status()
        return response.json()
