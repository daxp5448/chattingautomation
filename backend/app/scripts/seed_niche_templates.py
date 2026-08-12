"""Run once after deploying (same operational shape as `alembic upgrade head` -- not
automatic, see app/services/niche_template_sync.py's docstring for why) to load every
app/niche_seeds/*.py TEMPLATE into the real niche_templates table, so Super Admin's Add
Business niche picker (GET /niche-templates) has something to show.

Usage: python -m app.scripts.seed_niche_templates
"""

import asyncio
import logging

from app.db.session import AsyncSessionLocal
from app.services.niche_template_sync import sync_niche_templates

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


async def main() -> None:
    async with AsyncSessionLocal() as session:
        synced = await sync_niche_templates(session)
    logger.info("Synced %d niche template(s): %s", len(synced), ", ".join(sorted(synced)))


if __name__ == "__main__":
    asyncio.run(main())
