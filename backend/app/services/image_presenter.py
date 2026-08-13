"""Resolves which images (and captions) the bot actually shows for a catalog item --
Image-table-backed rows when ready `Image` rows exist, falling back to the legacy
`CatalogItem.images` JSON URL-list otherwise (that column has exactly one remaining
consumer: this file). Every result is already filtered to active images and sorted by
(display_order, created_at) -- callers never need to re-apply either.
"""

import uuid
from dataclasses import dataclass

from app.models.catalog import CatalogItem
from app.repositories.image_repository import ImageRepository
from app.services import image_storage_service


@dataclass
class ItemImage:
    url: str
    caption: str | None = None


def _current_images(images: list) -> list[ItemImage]:
    # "Current" images only: ready, active, and not superseded by a later replace()
    # (replace() links replaced_by_image_id on the OLD row rather than deleting it, so a
    # stale pre-replacement image must not resurface here). Already ordered by the
    # repository query (display_order, created_at); this just filters, it doesn't re-sort.
    current = [img for img in images if img.status == "ready" and img.is_active and img.replaced_by_image_id is None]
    result = []
    for img in current:
        variant = img.variants.get("website") or img.variants.get("whatsapp")
        if variant:
            result.append(ItemImage(url=image_storage_service.public_url(variant["key"]), caption=img.caption))
    return result


async def resolve_item_images(session, item: CatalogItem, restaurant_id: uuid.UUID) -> list[ItemImage]:
    images = await ImageRepository(session).list_for_catalog_item(item.id, restaurant_id)
    resolved = _current_images(images)
    if resolved:
        return resolved

    return [ItemImage(url=u) for u in (item.images or [])]


async def resolve_item_images_bulk(session, items: list[CatalogItem], restaurant_id: uuid.UUID) -> dict[uuid.UUID, list[ItemImage]]:
    """Batched sibling of resolve_item_images -- one query for every item in `items` instead
    of one query per item. Used by generic_flow_engine.py's photo-burst gating, which needs
    every option's image up front to decide whether to burst, not just the first hit.
    """
    all_images = await ImageRepository(session).list_for_catalog_items([item.id for item in items], restaurant_id)
    by_item: dict[uuid.UUID, list] = {}
    for img in all_images:
        by_item.setdefault(img.catalog_item_id, []).append(img)

    result: dict[uuid.UUID, list[ItemImage]] = {}
    for item in items:
        resolved = _current_images(by_item.get(item.id, []))
        result[item.id] = resolved if resolved else [ItemImage(url=u) for u in (item.images or [])]
    return result
