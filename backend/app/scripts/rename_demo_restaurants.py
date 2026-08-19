"""Renames every restaurant whose `name` contains the literal word "Demo" to a clean,
professional name -- `Restaurant.name` feeds directly into the {{business_name}} template
variable every customer-facing bot message uses (see generic_flow_engine.py::_prompt_text),
so "Demo" in the name leaks into real WhatsApp conversations (e.g. "Welcome to Demo --
Jewellers!"). `is_demo` (a separate boolean column) is untouched -- these restaurants are
still internally flagged/excluded from platform stats exactly as before; only the
customer-visible `name` string changes.

Idempotent: skips any restaurant whose name no longer contains "demo" (case-insensitive).

Usage: python -m app.scripts.rename_demo_restaurants
"""

import asyncio
import logging

from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.restaurant import Restaurant

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# Explicit mapping (not a mechanical "strip the word Demo") so every result reads as a
# real, professional business name -- exactly what a prospect trying the platform should
# see, niche by niche.
_RENAMES = {
    "KelvionTech Flagship Demo": "KelvionTech Business OS",
    "Demo — Automobile Service & Showroom": "KelvionTech Automobile Service & Showroom",
    "Demo — Clinic & Healthcare": "KelvionTech Clinic & Healthcare",
    "Demo — Education & Coaching": "KelvionTech Education & Coaching",
    "Demo — Electronics & Mobile Store": "KelvionTech Electronics & Mobile Store",
    "Demo — Grocery & Kirana Store": "KelvionTech Grocery & Kirana Store",
    "Demo — Gym & Fitness Studio": "KelvionTech Gym & Fitness Studio",
    "Demo — Hotel & Guesthouse": "KelvionTech Hotel & Guesthouse",
    "Demo — Jewellers": "KelvionTech Jewellers",
    "Demo — Real Estate": "KelvionTech Real Estate",
    "Demo — Restaurant": "KelvionTech Restaurant",
    "Demo — Retail & Fashion": "KelvionTech Retail & Fashion",
    "Demo — Salon & Spa": "KelvionTech Salon & Spa",
    "Demo Restaurant": "KelvionTech Restaurant (Legacy)",
}


async def main() -> None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Restaurant).where(Restaurant.name.ilike("%demo%")))
        restaurants = result.scalars().all()

        renamed, unmapped = 0, []
        for r in restaurants:
            new_name = _RENAMES.get(r.name)
            if new_name is None:
                unmapped.append(r.name)
                continue
            logger.info("Renaming %r -> %r (id=%s)", r.name, new_name, r.id)
            r.name = new_name
            renamed += 1

        if renamed:
            await session.commit()

    if unmapped:
        logger.warning("No mapping found for these names (left unchanged): %s", unmapped)
    logger.info("Done -- renamed=%d unmapped=%d", renamed, len(unmapped))


if __name__ == "__main__":
    asyncio.run(main())
