"""Re-point every demo-image URL at the current settings.PUBLIC_MEDIA_BASE_URL.

Why this exists: niche_seeds/_media.py::demo_image_base() builds every seeded demo image
URL from PUBLIC_MEDIA_BASE_URL at the moment a niche was first seeded/provisioned. That
setting has since changed (from a never-actually-running local MinIO address to a public
ngrok tunnel), but the URLs already written into existing rows don't retroactively update
-- sync_niche_templates() only refreshes NicheTemplate rows (and skips is_customized
ones), and sync_demo_restaurants() is deliberately create-once, never touching an already-
provisioned demo restaurant's cloned catalog data. This script is the missing piece: a
straight "everything up to and including /demo/ gets replaced with the current base"
rewrite, safe to re-run every time the tunnel URL rotates (idempotent -- a URL already on
the current base is left untouched).

Touches: is_demo restaurants' catalog_items.images / catalog_categories.image_url /
cover_image_url / logo_url, and every non-customized NicheTemplate's
default_catalog[].icon_image / default_catalog[].items[].images / welcome_banner_image.

Usage: python -m app.scripts.resync_demo_images
"""

import asyncio
import logging
import re

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.catalog import CatalogCategory, CatalogItem
from app.models.niche_template import NicheTemplate
from app.models.restaurant import Restaurant

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# Matches anything up to and including the last "/demo/" segment, so this works whether
# the stored URL is still on the original dead localhost:9000 address or a previously
# resynced (but now stale, since ngrok rotates) tunnel URL.
_DEMO_PATH_RE = re.compile(r"^.*/demo/")


def _rebase(url: str | None) -> tuple[str | None, bool]:
    """Returns (possibly-rewritten url, changed?)."""
    if not url or "/demo/" not in url:
        return url, False
    new_base = f"{settings.PUBLIC_MEDIA_BASE_URL}/demo/"
    rewritten = _DEMO_PATH_RE.sub(new_base, url, count=1)
    return rewritten, rewritten != url


async def main() -> None:
    changed_items = changed_categories = changed_restaurants = changed_templates = 0

    async with AsyncSessionLocal() as session:
        # --- catalog items (multi-image JSON array) ---
        items = (await session.execute(select(CatalogItem).join(Restaurant).where(Restaurant.is_demo.is_(True)))).scalars().all()
        for item in items:
            new_images = []
            item_changed = False
            for url in item.images or []:
                rebased, changed = _rebase(url)
                new_images.append(rebased)
                item_changed = item_changed or changed
            if item_changed:
                item.images = new_images
                flag_modified(item, "images")
                changed_items += 1

        # --- catalog categories (single image_url string) ---
        categories = (await session.execute(select(CatalogCategory).join(Restaurant).where(Restaurant.is_demo.is_(True)))).scalars().all()
        for cat in categories:
            rebased, changed = _rebase(cat.image_url)
            if changed:
                cat.image_url = rebased
                changed_categories += 1

        # --- restaurant cover/logo images ---
        restaurants = (await session.execute(select(Restaurant).where(Restaurant.is_demo.is_(True)))).scalars().all()
        for r in restaurants:
            r_changed = False
            rebased_cover, changed = _rebase(r.cover_image_url)
            if changed:
                r.cover_image_url = rebased_cover
                r_changed = True
            rebased_logo, changed = _rebase(r.logo_url)
            if changed:
                r.logo_url = rebased_logo
                r_changed = True
            if r_changed:
                changed_restaurants += 1

        # --- niche templates (skip anything a Super Admin has customized, same guard
        #     sync_niche_templates() already respects) ---
        templates = (await session.execute(select(NicheTemplate).where(NicheTemplate.is_customized.is_(False)))).scalars().all()
        for t in templates:
            t_changed = False
            rebased_banner, changed = _rebase(t.welcome_banner_image)
            if changed:
                t.welcome_banner_image = rebased_banner
                t_changed = True

            catalog = t.default_catalog or []
            for category in catalog:
                rebased_icon, changed = _rebase(category.get("icon_image"))
                if changed:
                    category["icon_image"] = rebased_icon
                    t_changed = True
                for it in category.get("items", []):
                    new_images = []
                    for url in it.get("images") or []:
                        rebased, changed = _rebase(url)
                        new_images.append(rebased)
                        t_changed = t_changed or changed
                    if new_images:
                        it["images"] = new_images
            if t_changed:
                t.default_catalog = catalog
                flag_modified(t, "default_catalog")
                changed_templates += 1

        await session.commit()

    logger.info(
        "Resynced demo image URLs to %s -- items=%d categories=%d restaurants=%d templates=%d",
        settings.PUBLIC_MEDIA_BASE_URL, changed_items, changed_categories, changed_restaurants, changed_templates,
    )


if __name__ == "__main__":
    asyncio.run(main())
