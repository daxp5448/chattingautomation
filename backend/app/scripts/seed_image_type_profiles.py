"""Run once after deploying (same operational shape as `alembic upgrade head` and
app/scripts/seed_niche_templates.py -- see app/services/image_type_profile_defaults.py's
module docstring for why this isn't migration data) to load the 10 default
ImageTypeProfile rows so the Universal Image Processing Pipeline is immediately usable.

Usage: python -m app.scripts.seed_image_type_profiles
"""

import asyncio
import logging

from app.db.session import AsyncSessionLocal
from app.services.image_type_profile_defaults import sync_default_profiles

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


async def main() -> None:
    async with AsyncSessionLocal() as session:
        synced = await sync_default_profiles(session)
    logger.info("Synced %d image type profile(s): %s", len(synced), ", ".join(sorted(synced)))


if __name__ == "__main__":
    asyncio.run(main())
