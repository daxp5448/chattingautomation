"""Compat shim for the Universal Image Processing Pipeline's pilot surface: read-side
only, so `CatalogItem.images` (the existing JSON URL-list column) is never dropped or
migrated by this pass -- it has exactly one consumer today
(generic_flow_engine.py::_Engine._image_for_step), and this is the one function that
consumer switches to. Returns Image-table-backed URLs when ready `Image` rows exist for a
catalog item, falling back to the legacy JSON list otherwise. The real migration
(backfilling existing URL strings into `Image` rows, then dropping the JSON column) is
explicit future follow-up, not this task.
"""

import uuid

from app.models.catalog import CatalogItem
from app.repositories.image_repository import ImageRepository
from app.services import image_storage_service


async def resolve_item_images(session, item: CatalogItem, restaurant_id: uuid.UUID) -> list[str]:
    images = await ImageRepository(session).list_for_catalog_item(item.id, restaurant_id)
    # "Current" images only: ready, and not superseded by a later replace() (replace()
    # links replaced_by_image_id on the OLD row rather than deleting it, so a stale
    # pre-replacement image must not resurface here).
    current = [img for img in images if img.status == "ready" and img.replaced_by_image_id is None]

    urls = []
    for img in current:
        variant = img.variants.get("website") or img.variants.get("whatsapp")
        if variant:
            urls.append(image_storage_service.public_url(variant["key"]))
    if urls:
        return urls

    return item.images or []
