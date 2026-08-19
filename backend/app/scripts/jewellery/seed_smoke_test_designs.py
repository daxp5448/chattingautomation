"""One-off, idempotent smoke-test seed: reuses the 4 existing jewellery demo photos
(gold/diamond/silver/bridal, already on disk under media_storage/demo/jewellers/) to
create a handful of JewelleryDesign rows for the demo jewellery restaurant, purely so the
carousel's full mechanism (materials -> categories -> paginated images -> Load More ->
Back) can be smoke-tested over real WhatsApp before any real Unsplash-sourced photos are
downloaded. NOT real catalog content -- source="smoke_test" marks these rows distinctly
so the real Unsplash downloader script (source="unsplash") never collides with or
double-counts them, and so they're easy to find/clear later.

gold/bangles gets 12 rows (page_size is 10) specifically so Load More is exercised, not
just a single-page combo.

Idempotent: skips entirely if this restaurant already has any source="smoke_test" rows.

Usage: python -m app.scripts.jewellery.seed_smoke_test_designs
"""

import asyncio
import logging

from sqlalchemy import select

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.jewellery_design import JewelleryDesign
from app.models.restaurant import Restaurant

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# (material, category, image_key, count)
_COMBOS = [
    ("gold", "bangles", "demo/jewellers/gold.jpg", 12),
    ("gold", "rings", "demo/jewellers/gold.jpg", 3),
    ("diamond", "rings", "demo/jewellers/diamond.jpg", 5),
    ("silver", "earrings", "demo/jewellers/silver.jpg", 4),
    ("gold", "bridal", "demo/jewellers/bridal.jpg", 6),
]


async def main() -> None:
    async with AsyncSessionLocal() as session:
        restaurant = (
            await session.execute(
                select(Restaurant).where(Restaurant.niche_type == "jewellers", Restaurant.is_demo.is_(True))
            )
        ).scalars().first()
        if restaurant is None:
            logger.error("No demo jewellery restaurant found -- nothing to seed")
            return

        already_seeded = (
            await session.execute(
                select(JewelleryDesign.id).where(
                    JewelleryDesign.restaurant_id == restaurant.id, JewelleryDesign.source == "smoke_test"
                ).limit(1)
            )
        ).scalar_one_or_none()
        if already_seeded is not None:
            logger.info("Restaurant %r already has smoke-test designs -- nothing to do", restaurant.name)
            return

        total = 0
        for material, category, image_key, count in _COMBOS:
            for i in range(1, count + 1):
                session.add(
                    JewelleryDesign(
                        restaurant_id=restaurant.id,
                        material=material,
                        category=category,
                        name=f"{material.title()} {category.title()} Design {i:03d}",
                        design_code=f"smoke_{material}_{category}_{i:03d}",
                        image_key=image_key,
                        thumbnail_key=None,
                        source="smoke_test",
                        source_id=f"smoke-{material}-{category}-{i}",
                        display_order=i,
                        is_active=True,
                    )
                )
                total += 1
        await session.commit()
        logger.info(
            "Seeded %d smoke-test JewelleryDesign rows for %r across %d combos (base URL: %s)",
            total, restaurant.name, len(_COMBOS), settings.PUBLIC_MEDIA_BASE_URL,
        )


if __name__ == "__main__":
    asyncio.run(main())
