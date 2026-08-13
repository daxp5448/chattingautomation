"""Meta Graph API client for provisioning a restaurant's own WhatsApp Flow (native ordering
screen) -- mirrors app/services/whatsapp_template_client.py's shape exactly: per-tenant
Graph API calls using the restaurant's own decrypted access token, raises on failure (no
swallowing into an {"error": ...} dict), router translates to a clean 502.

Verified directly against Meta's current docs before writing this (not from memory):
- Flow lifecycle (create/upload-asset/publish/delete) is WABA-scoped:
  POST /{waba_id}/flows, POST /{flow_id}/assets, POST /{flow_id}/publish, DELETE /{flow_id}.
- The public-key registration endpoint is PHONE-NUMBER-scoped, not WABA-scoped (a detail
  that's easy to get wrong -- "one active public key per phone number", per Meta's own
  docs): POST /{phone_number_id}/whatsapp_business_encryption, field `business_public_key`.
"""

from typing import Any

import httpx

from app.core.config import settings
from app.core.security import decrypt_secret
from app.models.restaurant import Restaurant

GRAPH_API_BASE = "https://graph.facebook.com"


def _credentials(restaurant: Restaurant) -> tuple[str, str, str]:
    waba_id = restaurant.whatsapp_business_account_id or ""
    phone_number_id = restaurant.whatsapp_phone_number_id or ""
    access_token = decrypt_secret(restaurant.whatsapp_access_token_encrypted or "")
    if not waba_id or not phone_number_id or not access_token:
        raise ValueError("WhatsApp Business Account is not configured for this restaurant")
    return waba_id, phone_number_id, access_token


def _base_url() -> str:
    return f"{GRAPH_API_BASE}/{settings.WHATSAPP_GRAPH_API_VERSION}"


async def register_public_key(restaurant: Restaurant, public_key_pem: str) -> dict[str, Any]:
    _waba_id, phone_number_id, access_token = _credentials(restaurant)
    async with httpx.AsyncClient(timeout=10.0, headers={"Authorization": f"Bearer {access_token}"}) as client:
        response = await client.post(
            f"{_base_url()}/{phone_number_id}/whatsapp_business_encryption",
            data={"business_public_key": public_key_pem},
        )
        response.raise_for_status()
        return response.json()


async def create_flow(restaurant: Restaurant, name: str, categories: list[str], endpoint_uri: str) -> str:
    """Returns the new Flow's id (still in DRAFT -- see publish_flow). `endpoint_uri` is
    where Meta sends every data_exchange call for this Flow -- required here (not set via
    a separate update call) since Flow JSON v3.0+ needs it from the start."""
    waba_id, _phone_number_id, access_token = _credentials(restaurant)
    async with httpx.AsyncClient(timeout=10.0, headers={"Authorization": f"Bearer {access_token}"}) as client:
        response = await client.post(
            f"{_base_url()}/{waba_id}/flows",
            json={"name": name, "categories": categories, "endpoint_uri": endpoint_uri},
        )
        response.raise_for_status()
        return response.json()["id"]


async def upload_flow_json(restaurant: Restaurant, flow_id: str, flow_json: dict[str, Any]) -> dict[str, Any]:
    """Raises if Meta reports any validation_errors -- a 200 with a non-empty
    validation_errors list is still a failure for our purposes (confirmed against the real
    API during the manual spike: a missing required screen field returns 200 with
    validation_errors populated, not a 4xx)."""
    import json

    _waba_id, _phone_number_id, access_token = _credentials(restaurant)
    files = {"file": ("flow.json", json.dumps(flow_json), "application/json")}
    data = {"name": "flow.json", "asset_type": "FLOW_JSON"}
    async with httpx.AsyncClient(timeout=10.0, headers={"Authorization": f"Bearer {access_token}"}) as client:
        response = await client.post(f"{_base_url()}/{flow_id}/assets", files=files, data=data)
        response.raise_for_status()
        result = response.json()
        if result.get("validation_errors"):
            raise ValueError(f"Flow JSON validation failed: {result['validation_errors']}")
        return result


async def publish_flow(restaurant: Restaurant, flow_id: str) -> dict[str, Any]:
    """Can fail with Meta's own account-level integrity/verification gate (error code
    139000, "Blocked by Integrity") independent of the Flow JSON's own correctness --
    confirmed during the manual spike against a temporary/unverified test WABA. The router
    surfaces this as a 502 with Meta's own message rather than masking it, since it's an
    account-standing issue the caller (Owner) needs to actually see and act on, not a bug.
    """
    waba_id, _phone_number_id, access_token = _credentials(restaurant)
    async with httpx.AsyncClient(timeout=10.0, headers={"Authorization": f"Bearer {access_token}"}) as client:
        response = await client.post(f"{_base_url()}/{flow_id}/publish", json={})
        response.raise_for_status()
        return response.json()


async def delete_flow(restaurant: Restaurant, flow_id: str) -> dict[str, Any]:
    _waba_id, _phone_number_id, access_token = _credentials(restaurant)
    async with httpx.AsyncClient(timeout=10.0, headers={"Authorization": f"Bearer {access_token}"}) as client:
        response = await client.delete(f"{_base_url()}/{flow_id}")
        response.raise_for_status()
        return response.json()
