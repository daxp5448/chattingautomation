"""Run after deploying (same operational shape as `alembic upgrade head` /
`seed_niche_templates` -- not automatic, see app/services/demo_restaurant_sync.py's
docstring for why) to auto-provision one demo Restaurant per current NicheTemplate, so
the Demo Bot's industry picker has something real to hand every niche's prospect.

Requires the one sentinel "Demo Bot" restaurant (is_demo=True, with a real
whatsapp_phone_number_id configured) to already exist -- create it once through the
normal restaurant-creation flow (check "Demo Bot restaurant" on /restaurants) before
running this.

Usage: python -m app.scripts.seed_demo_restaurants
"""

import asyncio
import logging

from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.restaurant import Restaurant
from app.services.demo_restaurant_sync import sync_demo_restaurants

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


async def main() -> None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Restaurant).where(Restaurant.is_demo.is_(True), Restaurant.whatsapp_phone_number_id.is_not(None))
        )
        sentinel = result.scalars().first()
        if sentinel is None:
            logger.error(
                "No sentinel Demo Bot restaurant found (is_demo=True with a real "
                "whatsapp_phone_number_id configured) -- create it first via the normal "
                "restaurant-creation flow."
            )
            return
        created = await sync_demo_restaurants(session, sentinel.id)
    logger.info("Provisioned %d new demo restaurant(s): %s", len(created), ", ".join(sorted(created)))


if __name__ == "__main__":
    asyncio.run(main())
