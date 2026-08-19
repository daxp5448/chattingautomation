"""Auto-provisions one demo Restaurant per current NicheTemplate, so the Demo Bot (see
app/services/demo_bot_service.py) has something real to hand a prospect for every niche
without any business being provisioned for them.

Deliberately create-once, not refresh-on-every-run, unlike the is_customized-protected
sync pattern in app/services/niche_template_sync.py / image_type_profile_defaults.py.
That pattern exists to stop a routine re-sync from silently reverting a Super Admin's
hand-edit -- there's no equivalent edit path here (nobody hand-edits a demo restaurant's
catalog/flow directly). The real reason this can't just re-run provision_from_template()
on an already-provisioned demo restaurant is structural: FlowDefinition.restaurant_id is
unique (a second provisioning call would violate it), and EngagementItem.catalog_item_id
is ON DELETE RESTRICT, so replacing old catalog rows once any demo order/booking has
happened against them fails outright. A real "reset this niche's demo" admin action is
possible later, but it has to explicitly delete that demo restaurant's entire history
first (Message/GenericConversationState/EngagementItem/Engagement/Customer, then the old
FlowDefinition/catalog) -- not something a routine sync re-run should ever do silently.
"""

import logging

from sqlalchemy import select

from app.models.restaurant import Restaurant
from app.repositories.niche_template_repository import NicheTemplateRepository
from app.services.niche_provisioning import provision_from_template

logger = logging.getLogger(__name__)


async def _unique_demo_slug(session, code: str) -> str:
    """`demo-{code}` is unique against every OTHER demo restaurant (is_demo rows only
    ever come from this function), but not necessarily against an unrelated pre-existing
    business that happens to already own that exact slug (found live: a stray, non-demo
    "Demo Restaurant" / slug="demo-restaurant" business blocked provisioning the entire
    "restaurant" niche, and -- before this fix -- took the other 11 niches down with it
    in the same all-or-nothing transaction). Falls back to a numeric suffix, same
    resolution a human would reach for if the plain slug were taken when creating a
    business by hand.
    """
    base = f"demo-{code}"
    candidate = base
    suffix = 2
    while (await session.execute(select(Restaurant.id).where(Restaurant.slug == candidate))).scalar_one_or_none() is not None:
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


async def sync_demo_restaurants(session, sentinel_restaurant_id) -> list[str]:
    """Returns the list of niche codes a demo restaurant was newly created for. A niche
    that already has one is left completely untouched.

    Each niche commits independently (a savepoint per niche, rolled back on that niche's
    own failure only) -- one niche hitting an unexpected error must never take the other
    11, already successfully provisioned in this same call, down with it.
    """
    created = []
    templates = await NicheTemplateRepository(session).list_all()
    for template in templates:
        existing = await session.execute(
            select(Restaurant).where(Restaurant.niche_type == template.code, Restaurant.is_demo.is_(True))
        )
        if existing.scalar_one_or_none() is not None:
            continue

        try:
            async with session.begin_nested():
                restaurant = Restaurant(
                    name=f"Demo — {template.name}",
                    slug=await _unique_demo_slug(session, template.code),
                    is_demo=True,
                    demo_sends_via_restaurant_id=sentinel_restaurant_id,
                    # No whatsapp_phone_number_id of its own -- never looked up directly
                    # by the webhook (app/api/v1/routers/webhook.py); the sentinel owns
                    # the only real demo number, and send_generic_message routes through
                    # it (see app/services/generic_flow_engine.py) via
                    # demo_sends_via_restaurant_id above.
                )
                session.add(restaurant)
                await session.flush()
                await provision_from_template(session, restaurant, template)
        except Exception:
            logger.exception("Demo restaurant provisioning failed for niche '%s' -- other niches unaffected", template.code)
            continue

        await session.commit()
        created.append(template.code)

    return created
