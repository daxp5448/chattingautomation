"""Provisioning-time behavior of Restaurant.conversation_settings /
NicheTemplate.default_personality -- same merge-never-clobber contract already proven for
default_modules -> loyalty_settings (see niche_provisioning.py), applied to the new pair.
"""

from sqlalchemy import select

from app.models.niche_template import NicheTemplate
from app.models.restaurant import Restaurant
from app.services.niche_template_sync import sync_niche_templates
from app.tests.test_restaurants import _register_super_admin


async def test_provisioning_copies_default_personality_onto_a_new_restaurant(client, db_session):
    await sync_niche_templates(db_session)
    headers = await _register_super_admin(client)

    created = await client.post(
        "/api/v1/restaurants",
        json={"name": "Personality Copy Test", "slug": "personality-copy-test", "niche_code": "jewellers"},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    restaurant_id = created.json()["id"]

    template = (await db_session.execute(select(NicheTemplate).where(NicheTemplate.code == "jewellers"))).scalar_one()
    assert template.default_personality  # sanity: the seed actually set one

    restaurant = await db_session.get(Restaurant, restaurant_id)
    assert restaurant.conversation_settings == template.default_personality


async def test_a_pre_set_conversation_setting_is_never_clobbered_by_provisioning(client, db_session, monkeypatch):
    """Mirrors niche_provisioning.py's own default_modules test precedent: a business's
    own pre-set value must win over the template's default, not get silently overwritten.
    Simulated by monkeypatching Restaurant.__init__-time default via a direct PATCH right
    after creation, then re-provisioning is never a thing that happens today (see
    test_niche_switching_safety.py) -- so this instead proves the merge direction itself
    via niche_provisioning.provision_from_template called a second time on a *fresh*
    in-memory Restaurant that already carries a pre-set conversation_settings value,
    exactly how the function is documented to behave."""
    from app.models.restaurant import Restaurant as RestaurantModel
    from app.repositories.niche_template_repository import NicheTemplateRepository
    from app.services.niche_provisioning import provision_from_template

    await sync_niche_templates(db_session)
    template = await NicheTemplateRepository(db_session).get_by_code("jewellers")

    restaurant = RestaurantModel(
        name="Pre-set Tone Business",
        slug="pre-set-tone-business",
        conversation_settings={"tone": "owner_already_chose_this"},
    )
    db_session.add(restaurant)
    await db_session.flush()

    await provision_from_template(db_session, restaurant, template)

    assert restaurant.conversation_settings["tone"] == "owner_already_chose_this"
    # Keys the business never set itself still come from the template default.
    assert restaurant.conversation_settings["emoji_level"] == template.default_personality["emoji_level"]
