"""Owner/Manager-facing provisioning for a restaurant's native WhatsApp Flow ordering
screen -- see the approved "WhatsApp Flows for Ordering" plan. Ties together
whatsapp_flow_crypto.py (keypair generation), whatsapp_flow_client.py (Graph API calls),
and whatsapp_flow_order_service.py (the one shared order Flow JSON, reused across every
order-type niche) into a single enable/disable action, mirroring
whatsapp_templates.py's per-tenant Graph API provisioning shape.
"""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.config import settings
from app.core.deps import DbSession, require_roles, resolve_tenant_id
from app.core.security import encrypt_secret
from app.models.enums import UserRole
from app.models.user import User
from app.repositories.restaurant_repository import RestaurantRepository
from app.services import whatsapp_flow_client
from app.services.whatsapp_flow_crypto import generate_keypair
from app.services.whatsapp_flow_order_service import ORDER_FLOW_JSON

router = APIRouter(prefix="/restaurants/{restaurant_id}/whatsapp-flow", tags=["whatsapp-flow"])

logger = logging.getLogger(__name__)

# Same bar as whatsapp_templates.py's _MANAGE_TEMPLATES: restaurant-configuration
# territory.
_MANAGE_FLOW = require_roles(UserRole.OWNER, UserRole.MANAGER)


async def _get_restaurant_or_404(db, tenant_id: uuid.UUID):
    restaurant = await RestaurantRepository(db).get(tenant_id)
    if not restaurant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Business not found")
    return restaurant


@router.post("/enable")
async def enable_whatsapp_flow(restaurant_id: uuid.UUID, db: DbSession, user: User = Depends(_MANAGE_FLOW)) -> dict:
    """Idempotent: re-calling this (e.g. to rotate the key, or after a webhook alert
    about a public-key mismatch) deletes any previously provisioned Flow first
    (best-effort -- Meta account state, not the source of truth here) and provisions a
    fresh one, rather than leaving an orphaned stale Flow behind on Meta's side.
    """
    tenant_id = resolve_tenant_id(user, restaurant_id)
    restaurant = await _get_restaurant_or_404(db, tenant_id)

    if restaurant.whatsapp_flow_order_id:
        try:
            await whatsapp_flow_client.delete_flow(restaurant, restaurant.whatsapp_flow_order_id)
        except Exception:
            logger.warning("Failed to delete previous Flow %s for restaurant %s -- continuing anyway", restaurant.whatsapp_flow_order_id, restaurant.id, exc_info=True)

    private_pem, public_pem = generate_keypair()
    endpoint_uri = f"{settings.PUBLIC_API_BASE_URL}/webhook/flow/{restaurant.id}"
    try:
        await whatsapp_flow_client.register_public_key(restaurant, public_pem)
        flow_id = await whatsapp_flow_client.create_flow(restaurant, f"kelviontech_order_{restaurant.slug}", ["OTHER"], endpoint_uri)
        await whatsapp_flow_client.upload_flow_json(restaurant, flow_id, ORDER_FLOW_JSON)
        await whatsapp_flow_client.publish_flow(restaurant, flow_id)
    except Exception as exc:
        # Deliberately surfaces Meta's own message (e.g. "Blocked by Integrity") rather
        # than a generic failure -- this is frequently an account-standing issue only the
        # Owner can act on (verify the WABA), not a bug to silently retry (see the
        # approved plan's manual-spike finding).
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Failed to enable WhatsApp Flow ordering: {exc}") from exc

    restaurant.whatsapp_flow_order_id = flow_id
    restaurant.whatsapp_flow_private_key_encrypted = encrypt_secret(private_pem)
    await db.commit()
    return {"flow_id": flow_id, "endpoint_uri": endpoint_uri}


@router.post("/disable")
async def disable_whatsapp_flow(restaurant_id: uuid.UUID, db: DbSession, user: User = Depends(_MANAGE_FLOW)) -> dict:
    """Clears the local columns unconditionally (the actual behavior switch --
    generic_flow_engine.py only sends a Flow when whatsapp_flow_order_id is set) even if
    the best-effort remote delete below fails; instant, safe opt-out is more important
    than a clean remote teardown."""
    tenant_id = resolve_tenant_id(user, restaurant_id)
    restaurant = await _get_restaurant_or_404(db, tenant_id)

    if restaurant.whatsapp_flow_order_id:
        try:
            await whatsapp_flow_client.delete_flow(restaurant, restaurant.whatsapp_flow_order_id)
        except Exception:
            logger.warning("Failed to delete Flow %s for restaurant %s on disable -- clearing local state anyway", restaurant.whatsapp_flow_order_id, restaurant.id, exc_info=True)

    restaurant.whatsapp_flow_order_id = None
    restaurant.whatsapp_flow_private_key_encrypted = None
    await db.commit()
    return {"status": "disabled"}
