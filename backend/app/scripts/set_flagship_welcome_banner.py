"""One-off: point the Flagship (sentinel Demo Bot) restaurant's cover_image_url at the
current KelvionTech welcome banner in media_storage/flagship/welcome_banner.png, served
through the same public media passthrough every other demo image already uses (see
app/api/v1/routers/media.py) so it renders in WhatsApp exactly like any other image
message -- no new mechanism, just a value for a field demo_bot_service.py's
_welcome_banner_messages() already reads.

This IS the permanent setup: cover_image_url is a real, persisted DB column, and
_welcome_banner_messages() already sends it (via send_generic_messages_batch, image
FIRST) before the industry-picker options message on every single "Hi" -- that ordering
guarantee was established and tested earlier this session (see
send_generic_messages_batch's own docstring), not something this script needs to
reimplement. Safe/idempotent to re-run any time the banner image itself is replaced --
just overwrite media_storage/flagship/welcome_banner.png and rerun.

Matches the sentinel restaurant by demo_sends_via_restaurant_id IS NULL + is_demo IS TRUE
+ niche_type IS NULL (the actual identifying shape of "the one flagship/sentinel
restaurant"), not by name -- names get renamed (e.g. "KelvionTech Flagship Demo" ->
"KelvionTech Business OS", see app/scripts/rename_demo_restaurants.py) but this shape
doesn't change.

Usage: python -m app.scripts.set_flagship_welcome_banner
"""

import asyncio
import logging

from sqlalchemy import select

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.restaurant import Restaurant

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


async def main() -> None:
    url = f"{settings.PUBLIC_MEDIA_BASE_URL}/flagship/welcome_banner.png"
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Restaurant).where(
                Restaurant.is_demo.is_(True),
                Restaurant.niche_type.is_(None),
                Restaurant.demo_sends_via_restaurant_id.is_(None),
            )
        )
        flagship = result.scalar_one()
        flagship.cover_image_url = url
        # _welcome_banner_messages() sends BOTH logo_url and cover_image_url if both are
        # set (two separate banner images, two separate captions) -- cleared here so
        # exactly one banner image goes out before the industry picker, matching "this
        # image sent first" (singular). Set logo_url again deliberately (via Settings, not
        # this script) if a distinct small logo + full banner combination is ever wanted.
        flagship.logo_url = None
        await session.commit()
    logger.info("Flagship (%r) cover_image_url set to %s, logo_url cleared", flagship.name, url)


if __name__ == "__main__":
    asyncio.run(main())
