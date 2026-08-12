"""API-level proof for the Super Admin "Add Business" niche picker: GET /niche-templates
(what the frontend dropdown at frontend/app/(dashboard)/restaurants/page.tsx populates
from) and POST /restaurants with `niche_code` set (what submitting that form actually
does) -- end to end through real HTTP requests, not just unit-level service calls. No
browser is available in this environment to click through the actual page, so this is
the equivalent verification at the API boundary the frontend calls.
"""

from sqlalchemy import select

from app.models.catalog import CatalogCategory
from app.models.flow_definition import FlowDefinition
from app.models.restaurant import Restaurant
from app.services.niche_template_sync import sync_niche_templates
from app.tests.test_restaurants import _register_super_admin


async def test_niche_templates_endpoint_lists_synced_niches(client, db_session):
    await sync_niche_templates(db_session)
    headers = await _register_super_admin(client)

    resp = await client.get("/api/v1/niche-templates", headers=headers)
    assert resp.status_code == 200, resp.text
    codes = {t["code"] for t in resp.json()}
    assert {"salon", "restaurant"} <= codes
    salon = next(t for t in resp.json() if t["code"] == "salon")
    assert salon["action_type"] == "appointment"
    assert salon["name"] == "Salon & Spa"
    assert salon["icon"]


async def test_creating_restaurant_with_niche_code_auto_provisions_it(client, db_session):
    await sync_niche_templates(db_session)
    headers = await _register_super_admin(client)

    resp = await client.post(
        "/api/v1/restaurants",
        json={"name": "Glow Salon Test", "slug": "glow-salon-test-api", "niche_code": "salon"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    restaurant_id = body["id"]

    result = await db_session.execute(select(Restaurant).where(Restaurant.id == restaurant_id))
    restaurant = result.scalar_one()
    assert restaurant.uses_generic_engine is True
    assert restaurant.niche_type == "salon"

    categories = (await db_session.execute(
        select(CatalogCategory).where(CatalogCategory.restaurant_id == restaurant.id)
    )).scalars().all()
    assert len(categories) >= 6  # Salon ships 6 default categories

    flow = (await db_session.execute(
        select(FlowDefinition).where(FlowDefinition.restaurant_id == restaurant.id)
    )).scalar_one()
    assert flow.niche_code == "salon"
    assert flow.action_type.value == "appointment"
    assert len(flow.steps) > 0


async def test_creating_restaurant_with_unknown_niche_code_rejected(client, db_session):
    headers = await _register_super_admin(client)

    resp = await client.post(
        "/api/v1/restaurants",
        json={"name": "Bad Niche Biz", "slug": "bad-niche-biz", "niche_code": "not-a-real-niche"},
        headers=headers,
    )
    assert resp.status_code == 400, resp.text


async def test_creating_restaurant_without_niche_code_stays_on_legacy_engine(client, db_session):
    """The default path (no niche picked, "Custom / Legacy" in the dropdown) must
    behave exactly as it always has -- Restaurant.uses_generic_engine stays False,
    matching the hard constraint that no already-working business's behavior changes."""
    headers = await _register_super_admin(client)

    resp = await client.post(
        "/api/v1/restaurants", json={"name": "Classic Diner", "slug": "classic-diner-api"}, headers=headers
    )
    assert resp.status_code == 201, resp.text
    restaurant_id = resp.json()["id"]

    result = await db_session.execute(select(Restaurant).where(Restaurant.id == restaurant_id))
    restaurant = result.scalar_one()
    assert restaurant.uses_generic_engine is False
    assert restaurant.niche_type is None
