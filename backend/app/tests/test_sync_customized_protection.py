"""Proves the is_customized bug fix (found during design review of this feature): both
seed-sync functions must skip a row a Super Admin has customized, instead of reverting it
on the next (normal, repeatable) run of the seed script -- while still updating any
never-touched row, so the "pick up new code-defined defaults" upgrade path still works.
"""

from sqlalchemy import select

from app.models.image_type_profile import ImageTypeProfile
from app.models.niche_template import NicheTemplate
from app.services.image_type_profile_defaults import sync_default_profiles
from app.services.niche_template_sync import sync_niche_templates


async def test_customized_niche_template_survives_resync(db_session):
    await sync_niche_templates(db_session)
    result = await db_session.execute(select(NicheTemplate).where(NicheTemplate.code == "salon"))
    salon = result.scalar_one()
    salon.name = "Custom Salon Name"
    salon.is_customized = True
    await db_session.commit()

    synced_codes = await sync_niche_templates(db_session)
    assert "salon" not in synced_codes  # skipped, not touched

    db_session.expire_all()
    result = await db_session.execute(select(NicheTemplate).where(NicheTemplate.code == "salon"))
    refreshed = result.scalar_one()
    assert refreshed.name == "Custom Salon Name"  # edit survived


async def test_never_customized_niche_template_still_updates_on_resync(db_session):
    await sync_niche_templates(db_session)
    result = await db_session.execute(select(NicheTemplate).where(NicheTemplate.code == "salon"))
    salon = result.scalar_one()
    assert salon.is_customized is False
    salon_id = salon.id

    # Simulate a stale/mismatched name (as if the code-defined default changed since last
    # sync) -- re-running sync on a never-customized row must correct it back.
    salon.name = "Stale Name Nobody Chose"
    await db_session.commit()

    synced_codes = await sync_niche_templates(db_session)
    assert "salon" in synced_codes

    db_session.expire_all()
    result = await db_session.execute(select(NicheTemplate).where(NicheTemplate.id == salon_id))
    refreshed = result.scalar_one()
    assert refreshed.name == "Salon & Spa"  # corrected back to the code-defined default


async def test_customized_image_type_profile_survives_resync(db_session):
    await sync_default_profiles(db_session)
    result = await db_session.execute(select(ImageTypeProfile).where(ImageTypeProfile.code == "product"))
    product = result.scalar_one()
    product.label = "Custom Product Label"
    product.is_customized = True
    await db_session.commit()

    synced_codes = await sync_default_profiles(db_session)
    assert "product" not in synced_codes

    db_session.expire_all()
    result = await db_session.execute(select(ImageTypeProfile).where(ImageTypeProfile.code == "product"))
    refreshed = result.scalar_one()
    assert refreshed.label == "Custom Product Label"


async def test_never_customized_image_type_profile_still_updates_on_resync(db_session):
    await sync_default_profiles(db_session)
    result = await db_session.execute(select(ImageTypeProfile).where(ImageTypeProfile.code == "product"))
    product = result.scalar_one()
    assert product.is_customized is False
    product_id = product.id

    product.label = "Stale Label"
    await db_session.commit()

    synced_codes = await sync_default_profiles(db_session)
    assert "product" in synced_codes

    db_session.expire_all()
    result = await db_session.execute(select(ImageTypeProfile).where(ImageTypeProfile.id == product_id))
    refreshed = result.scalar_one()
    assert refreshed.label == "Product"
