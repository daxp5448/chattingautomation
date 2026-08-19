"""Brings an ALREADY-PROVISIONED jewellery business's FlowDefinition in line with the
current jewellers.py TEMPLATE for two things: (1) the 3 carousel steps (material_select ->
jewellery_category_select -> design_gallery), and (2) the welcome step's button set.

Why this exists: a business's FlowDefinition.steps is cloned from NicheTemplate at
creation time (niche_provisioning.py::provision_from_template) -- editing jewellers.py's
TEMPLATE only changes what a BRAND NEW jewellery business gets going forward, it does
nothing for a jewellery business that was already provisioned before this feature landed
(same class of gap resync_demo_images.py's docstring documents for image URLs: there is
no existing mechanism that propagates a template change onto already-cloned rows).

Safe to re-run:
  - The 3 carousel steps are only ever appended, never duplicated (skipped if
    "design_gallery" is already among the restaurant's step_ids).
  - The welcome step's `static_options`/`routes` are reconciled to exactly match the
    template's CURRENT welcome step (add "welcome:explore_design", drop the retired
    "welcome:explore", correct ordering) -- a no-op once a restaurant is already in sync.
    This is intentionally NOT "additive only" like the first version of this script: the
    product owner explicitly asked for "Explore Collection" removed as a duplicate of the
    new carousel entry point, so a straight reconciliation (not a diff-and-append) is the
    correct behavior here. Only the welcome step's OWN static_options/routes are touched
    -- every other step (including any a business owner hand-edited via Flow Builder) is
    left completely alone.

Usage: python -m app.scripts.jewellery.sync_carousel_steps
"""

import asyncio
import copy
import logging

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from app.db.session import AsyncSessionLocal
from app.models.flow_definition import FlowDefinition
from app.models.restaurant import Restaurant
from app.niche_seeds.jewellers import TEMPLATE as JEWEL_TEMPLATE

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

_NEW_STEP_IDS = {"material_select", "jewellery_category_select", "design_gallery"}


def _template_step(step_id: str) -> dict:
    return next(s for s in JEWEL_TEMPLATE["default_flow_steps"] if s["step_id"] == step_id)


async def main() -> None:
    template_welcome = _template_step("welcome")
    new_steps = [s for s in JEWEL_TEMPLATE["default_flow_steps"] if s["step_id"] in _NEW_STEP_IDS]
    assert {s["step_id"] for s in new_steps} == _NEW_STEP_IDS, "jewellers.py TEMPLATE is missing an expected carousel step"

    async with AsyncSessionLocal() as session:
        restaurants = (await session.execute(select(Restaurant).where(Restaurant.niche_type == "jewellers"))).scalars().all()

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
            logger.info("Restaurant %r: reconciled carousel steps + welcome menu", restaurant.name)

        if updated:
            await session.commit()

    logger.info("Done -- updated=%d", updated)


if __name__ == "__main__":
    asyncio.run(main())
