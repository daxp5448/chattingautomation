"""app/services/niche_template_sync.py -- proves the discovery + upsert mechanism that
turns app/niche_seeds/*.py TEMPLATE dicts into real niche_templates rows (what Super
Admin's Add Business niche picker, GET /niche-templates, actually reads from). Robust to
however many niches exist at any point (doesn't hardcode an expected count), since more
niches get added to app/niche_seeds/ over time.
"""

from sqlalchemy import select

from app.models.enums import EngagementType
from app.models.niche_template import NicheTemplate
from app.services.niche_template_sync import discover_templates, sync_niche_templates


def test_discover_templates_finds_the_known_proof_niches():
    templates = discover_templates()
    codes = {t["code"] for t in templates}
    # The two niches already built and merged at the time this test was written --
    # doesn't assert an exact total, since more niches are added over time.
    assert {"salon", "restaurant"} <= codes
    for template in templates:
        assert template["action_type"] in {"order", "inquiry", "appointment", "booking"}
        assert template["default_catalog"], f"{template['code']} has no default catalog content"
        assert template["default_flow_steps"], f"{template['code']} has no default flow"


async def test_sync_creates_rows_with_correct_action_type(db_session):
    synced_codes = await sync_niche_templates(db_session)
    assert "salon" in synced_codes and "restaurant" in synced_codes

    result = await db_session.execute(select(NicheTemplate).where(NicheTemplate.code == "salon"))
    salon_row = result.scalar_one()
    assert salon_row.action_type == EngagementType.APPOINTMENT
    assert salon_row.name == "Salon & Spa"

    result = await db_session.execute(select(NicheTemplate).where(NicheTemplate.code == "restaurant"))
    restaurant_row = result.scalar_one()
    assert restaurant_row.action_type == EngagementType.ORDER


async def test_sync_is_idempotent_and_updates_in_place(db_session):
    await sync_niche_templates(db_session)
    result = await db_session.execute(select(NicheTemplate).where(NicheTemplate.code == "salon"))
    first_id = result.scalar_one().id

    # Re-running must update the same row, not insert a duplicate (the whole point of
    # upsert-by-code -- a template's `code` is the unique key both here and on the
    # niche_templates table itself, see app/models/niche_template.py).
    await sync_niche_templates(db_session)
    result = await db_session.execute(select(NicheTemplate).where(NicheTemplate.code == "salon"))
    rows = result.scalars().all()
    assert len(rows) == 1
    assert rows[0].id == first_id
