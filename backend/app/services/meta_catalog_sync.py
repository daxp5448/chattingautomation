"""Syncs JewelleryDesign rows into a restaurant's connected Meta/Facebook Commerce
Catalog, via the Graph API's per-item product-creation endpoint (`POST
/{catalog_id}/products`) -- the shape Meta documents for adding a single product to a
catalog (retailer_id, name, image_url, price as "<amount> <currency>", currency,
availability, condition, brand).

This is deliberately a plain, reusable service function -- NOT wired into any live
customer-facing send path. It exists to be called from a future one-off script or Super
Admin action once a restaurant actually has Restaurant.whatsapp_catalog_id set (nobody
does yet; the Commerce Catalog is still being set up on Meta's side). Until then this
module is inert: nothing imports or calls it automatically.

Mirrors app/services/whatsapp_template_client.py's shape (a small Graph API client
scoped to one concern, own httpx.AsyncClient per call, decrypt_secret for the access
token) rather than app/services/whatsapp_client.py's GraphAPIWhatsAppSender -- this isn't
a customer message send, it's an admin-side catalog-management call, same category as
template create/delete.
"""

import logging
from typing import Any

import httpx

from app.core.config import settings
from app.core.security import decrypt_secret
from app.models.jewellery_design import JewelleryDesign
from app.models.restaurant import Restaurant

logger = logging.getLogger(__name__)

GRAPH_API_BASE = "https://graph.facebook.com"

# Jewellery designs have no price column yet (out of scope for this pass -- a real
# per-design price needs a future JewelleryDesign.price column). Meta requires SOME
# price on every catalog product, so every design is synced with this placeholder until
# that column exists; real pricing is a follow-up, not something this function can fake
# correctly today.
_PLACEHOLDER_PRICE = "0 INR"


def _base_url() -> str:
    return f"{GRAPH_API_BASE}/{settings.WHATSAPP_GRAPH_API_VERSION}"


def _build_product_payload(restaurant: Restaurant, design: JewelleryDesign, retailer_id: str) -> dict[str, Any]:
    return {
        "retailer_id": retailer_id,
        "name": design.name,
        "image_url": f"{settings.PUBLIC_MEDIA_BASE_URL}/{design.image_key}",
        # See _PLACEHOLDER_PRICE above -- no real per-design price exists yet.
        "price": _PLACEHOLDER_PRICE,
        "currency": "INR",
        "availability": "in stock",
        "condition": "new",
        "brand": restaurant.name,
    }


async def sync_designs_to_catalog(
    session, restaurant: Restaurant, designs: list[JewelleryDesign]
) -> dict[str, Any]:
    """For each design in `designs` that has no meta_retailer_id yet, creates a product
    in `restaurant.whatsapp_catalog_id` via the Graph API and, on success, stamps
    design.meta_retailer_id and commits. Designs that already have a meta_retailer_id
    are counted as skipped (never re-submitted). Never raises on a per-design failure --
    one bad design shouldn't abort the whole batch -- but does raise ValueError up front
    if the restaurant has no catalog_id/access token configured at all, since in that
    case every design would fail identically and that's a caller/config error, not a
    per-item one.

    Returns {"synced": int, "failed": int, "skipped": int, "errors": list[dict]}.
    """
    catalog_id = restaurant.whatsapp_catalog_id
    access_token = decrypt_secret(restaurant.whatsapp_access_token_encrypted or "")
    if not catalog_id or not access_token:
        raise ValueError(
            "Restaurant has no whatsapp_catalog_id/whatsapp_access_token_encrypted "
            "configured -- cannot sync to a Meta Commerce Catalog yet"
        )

    synced = 0
    failed = 0
    skipped = 0
    errors: list[dict[str, Any]] = []

    async with httpx.AsyncClient(timeout=10.0, headers={"Authorization": f"Bearer {access_token}"}) as client:
        for design in designs:
            if design.meta_retailer_id:
                skipped += 1
                continue

            # design.id is already a stable, globally-unique retailer_id candidate --
            # reusing it (rather than minting a separate code) means re-running this
            # function is naturally idempotent per design even before meta_retailer_id
            # is stamped.
            retailer_id = str(design.id)
            payload = _build_product_payload(restaurant, design, retailer_id)
            try:
                response = await client.post(f"{_base_url()}/{catalog_id}/products", json=payload)
                response.raise_for_status()
            except httpx.HTTPError as exc:
                failed += 1
                detail = exc.response.text[:500] if isinstance(exc, httpx.HTTPStatusError) else str(exc)
                logger.error(
                    "Meta catalog sync failed for design %s (retailer_id=%s): %s",
                    design.id, retailer_id, detail,
                )
                errors.append({"design_id": str(design.id), "error": detail})
                continue

            design.meta_retailer_id = retailer_id
            session.add(design)
            await session.commit()
            synced += 1

    return {"synced": synced, "failed": failed, "skipped": skipped, "errors": errors}
