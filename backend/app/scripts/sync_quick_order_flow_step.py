"""Brings an ALREADY-PROVISIONED restaurant business's FlowDefinition in line with the
current restaurant.py TEMPLATE for the new "Quick Order" WhatsApp Flow entry point
(quick_order_flow -> quick_order_confirmed) and the welcome step's button set -- same
gap sync_carousel_steps.py documents for jewellers.py: editing restaurant.py's TEMPLATE
only changes what a BRAND NEW restaurant gets going forward, it does nothing for one
already provisioned before this feature landed.

Safe to re-run:
  - The 2 new steps are only ever appended, never duplicated (skipped if
    "quick_order_flow" is already among the restaurant's step_ids).
  - The welcome step's `static_options`/`routes` are reconciled to exactly match the
    template's CURRENT welcome step -- a no-op once a restaurant is already in sync. Only
    the welcome step's OWN static_options/routes are touched -- every other step is left
    completely alone.

Adding this step to a business's flow is harmless even before its own
whatsapp_quick_customize_flow_id is set: the step's own fallback_next sends the customer
straight to category_select instead of a dead end (see generic_flow_engine.py's
send_quick_customize_flow handling).

Usage: python -m app.scripts.sync_quick_order_flow_step
"""

import asyncio
import copy
import logging

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from app.db.session import AsyncSessionLocal
from app.models.flow_definition import FlowDefinition
from app.models.restaurant import Restaurant
from app.niche_seeds.restaurant import TEMPLATE as RESTAURANT_TEMPLATE

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

_NEW_STEP_IDS = {"quick_order_flow", "quick_order_confirmed"}


def _template_step(step_id: str) -> dict:
    return next(s for s in RESTAURANT_TEMPLATE["default_flow_steps"] if s["step_id"] == step_id)


async def main() -> None:
    template_welcome = _template_step("welcome")
    new_steps = [s for s in RESTAURANT_TEMPLATE["default_flow_steps"] if s["step_id"] in _NEW_STEP_IDS]
    assert {s["step_id"] for s in new_steps} == _NEW_STEP_IDS, "restaurant.py TEMPLATE is missing an expected quick-order step"

    async with AsyncSessionLocal() as session:
        restaurants = (await session.execute(select(Restaurant).where(Restaurant.niche_type == "restaurant"))).scalars().all()

        updated = 0
        for restaurant in restaurants:
            fd = (
                await session.execute(select(FlowDefinition).where(FlowDefinition.restaurant_id == restaurant.id))
            ).scalar_one_or_none()
            if fd is None:
                logger.warning("Restaurant %r (%s) has no FlowDefinition -- skipping", restaurant.name, restaurant.id)
                continue

            steps = list(fd.steps)
            existing_step_ids = {s.get("step_id") for s in steps}
            changed = False

            if not (_NEW_STEP_IDS & existing_step_ids):
                steps.extend(copy.deepcopy(new_steps))
                changed = True

            for i, step in enumerate(steps):
                if step.get("step_id") != "welcome":
                    continue
                new_welcome = {**step, "static_options": template_welcome["static_options"], "routes": template_welcome["routes"]}
                if new_welcome["static_options"] != step.get("static_options") or new_welcome["routes"] != step.get("routes"):
                    steps[i] = new_welcome
                    changed = True
                break

            if not changed:
                logger.info("Restaurant %r already in sync -- skipping", restaurant.name)
                continue

            fd.steps = steps
            flag_modified(fd, "steps")
            updated += 1
            logger.info("Restaurant %r: added Quick Order Flow step + welcome menu", restaurant.name)

        if updated:
            await session.commit()

    logger.info("Done -- updated=%d", updated)


if __name__ == "__main__":
    asyncio.run(main())
