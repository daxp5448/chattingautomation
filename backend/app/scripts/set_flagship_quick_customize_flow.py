"""One-off: point the Flagship (sentinel Demo Bot) restaurant's
whatsapp_quick_customize_flow_id at the real, manually-built WhatsApp Flow (id
3615779808579689, single ORDER_SCREEN screen: option tier + quantity + notes, no
data-exchange endpoint -- verified live via the Graph API, see
app/services/generic_flow_engine.py's send_quick_customize_flow handling for how it's
sent/consumed). This is a REBUILD of an earlier Flow (id 1504663505025579) that Meta
deleted -- confirmed via a live GET returning "Object with ID ... does not exist" -- the
rebuild has an identical screen/field shape, so no engine code changed, only this id.
Every per-niche demo restaurant with no WhatsApp credentials of its own routes through
the Flagship's credentials (demo_sends_via_restaurant_id), so setting this once on the
Flagship makes the new "Quick Order" entry point live for every demo niche business that
has the step wired into its flow -- see app/scripts/sync_quick_order_flow_step.py for the
restaurant niche's own rollout.

draft_mode is set True because the Flow is currently in DRAFT status in Meta's Flow
Builder: only phone numbers registered as test numbers for the WhatsApp app will actually
receive/complete it until it's published. Flip this restaurant's
whatsapp_quick_customize_flow_draft_mode off (via Settings, not this script) once the
Flow is published.

Matches the sentinel restaurant by demo_sends_via_restaurant_id IS NULL + is_demo IS TRUE
+ niche_type IS NULL, same identifying shape set_flagship_welcome_banner.py uses.

Usage: python -m app.scripts.set_flagship_quick_customize_flow
"""

import asyncio
import logging

from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.restaurant import Restaurant

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

_FLOW_ID = "3615779808579689"


async def main() -> None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Restaurant).where(
                Restaurant.is_demo.is_(True),
                Restaurant.niche_type.is_(None),
                Restaurant.demo_sends_via_restaurant_id.is_(None),
            )
        )
        flagship = result.scalar_one()
        flagship.whatsapp_quick_customize_flow_id = _FLOW_ID
        flagship.whatsapp_quick_customize_flow_draft_mode = True
        await session.commit()
    logger.info("Flagship (%r) whatsapp_quick_customize_flow_id set to %s (draft_mode=True)", flagship.name, _FLOW_ID)


if __name__ == "__main__":
    asyncio.run(main())
