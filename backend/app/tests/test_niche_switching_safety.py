"""FINAL PRE-LIVE VERIFICATION section 7: there is no endpoint that lets a Super Admin
switch an already-provisioned business's niche. Confirms that's genuinely enforced (not
just "no button for it in the UI" while the API quietly accepts it) and that attempting
it through the API is a safe no-op -- niche_type, catalog, and the FlowDefinition all
stay exactly as originally provisioned, never partially/silently mutated.
"""

from sqlalchemy import select

from app.models.catalog import CatalogCategory
from app.models.flow_definition import FlowDefinition
from app.services.niche_template_sync import sync_niche_templates
from app.tests.test_restaurants import _register_super_admin


async def test_patching_niche_code_on_an_existing_business_is_a_silent_safe_noop(client, db_session):
    """RestaurantUpdate (the PATCH schema) has no niche_code field at all -- confirms
    niche switching genuinely isn't wired up anywhere, not merely hidden from the UI."""
    await sync_niche_templates(db_session)
    headers = await _register_super_admin(client)

    created = await client.post(
        "/api/v1/restaurants",
        json={"name": "Niche Switch Test", "slug": "niche-switch-test", "niche_code": "jewellers"},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    restaurant_id = created.json()["id"]

    before = await client.get(f"/api/v1/restaurants/{restaurant_id}", headers=headers)
    assert before.json()["niche_type"] == "jewellers"
    assert before.json()["uses_generic_engine"] is True

    flow_before = (await db_session.execute(select(FlowDefinition).where(FlowDefinition.restaurant_id == restaurant_id))).scalar_one()
    categories_before = (await db_session.execute(select(CatalogCategory).where(CatalogCategory.restaurant_id == restaurant_id))).scalars().all()
    assert flow_before.niche_code == "jewellers"
    assert len(categories_before) > 0

    # Attempt to "switch" niches via PATCH -- the field isn't in RestaurantUpdate's
    # schema at all, so this must be a harmless no-op: 200 OK (not a 422/500), but the
    # business's actual niche_type/flow/catalog completely unchanged.
    switch_attempt = await client.patch(
        f"/api/v1/restaurants/{restaurant_id}", json={"niche_code": "restaurant", "name": "Niche Switch Test"}, headers=headers
    )
    assert switch_attempt.status_code == 200, switch_attempt.text

    after = await client.get(f"/api/v1/restaurants/{restaurant_id}", headers=headers)
    assert after.json()["niche_type"] == "jewellers", "niche_type must never silently change via PATCH"

    db_session.expire_all()
    flow_after = (await db_session.execute(select(FlowDefinition).where(FlowDefinition.restaurant_id == restaurant_id))).scalar_one()
    categories_after = (await db_session.execute(select(CatalogCategory).where(CatalogCategory.restaurant_id == restaurant_id))).scalars().all()
    assert flow_after.id == flow_before.id
    assert flow_after.niche_code == "jewellers"  # still the original niche's flow, untouched
    assert {c.id for c in categories_after} == {c.id for c in categories_before}  # no stale/duplicate catalog rows


async def test_no_endpoint_exists_to_reprovision_a_businesss_niche(client):
    """Belt-and-suspenders: confirm there's no OTHER route (re-provision, switch-niche,
    etc.) anywhere under /restaurants that would let this happen a different way."""
    headers = await _register_super_admin(client)
    created = await client.post(
        "/api/v1/restaurants", json={"name": "No Reprovision Route", "slug": "no-reprovision-route"}, headers=headers
    )
    restaurant_id = created.json()["id"]

    for path in (
        f"/api/v1/restaurants/{restaurant_id}/niche",
        f"/api/v1/restaurants/{restaurant_id}/switch-niche",
        f"/api/v1/restaurants/{restaurant_id}/reprovision",
        f"/api/v1/restaurants/{restaurant_id}/provision",
    ):
        resp = await client.post(path, json={"niche_code": "restaurant"}, headers=headers)
        assert resp.status_code in (404, 405), f"unexpected route exists at {path}: {resp.status_code}"
