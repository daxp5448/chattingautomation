"""GET /restaurants/{id}/whatsapp-templates/recommendations -- niche-aware template
recommendations for Broadcast Campaigns. Same helper style as test_broadcasts.py.
"""

from app.core.security import encrypt_secret
from app.models.enums import TemplateCategory, TemplatePurpose, TemplateStatus
from app.models.restaurant import Restaurant
from app.models.whatsapp_template import WhatsAppTemplate


async def _register_and_login(client, restaurant_id, role="owner", email="owner@template-rec-test.dev"):
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "TestPass123!", "role": role, "restaurant_id": str(restaurant_id)},
    )
    assert resp.status_code == 201, resp.text
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": "TestPass123!"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _make_restaurant(db_session, slug: str, niche_type: str | None = "jewellers") -> Restaurant:
    restaurant = Restaurant(
        name=f"Template Rec Test {slug}", slug=f"template-rec-test-{slug}",
        whatsapp_phone_number_id=f"TEMPLATE_REC_TEST_PHONE_{slug}",
        whatsapp_access_token_encrypted=encrypt_secret("fake-access-token"),
        niche_type=niche_type,
    )
    db_session.add(restaurant)
    await db_session.commit()
    return restaurant


async def _make_template(db_session, restaurant, name, purpose, status=TemplateStatus.APPROVED) -> WhatsAppTemplate:
    template = WhatsAppTemplate(
        restaurant_id=restaurant.id, name=name, category=TemplateCategory.MARKETING, purpose=purpose,
        language="en_US", body_text="Hi {{1}}", status=status, meta_template_id=f"meta_{name}" if status != TemplateStatus.DRAFT else None,
    )
    db_session.add(template)
    await db_session.commit()
    return template


async def test_recommendations_shaped_by_niche_and_own_approved_templates(client, db_session):
    restaurant = await _make_restaurant(db_session, "jewellers-shop", niche_type="jewellers")
    headers = await _register_and_login(client, restaurant.id)
    product_tpl = await _make_template(db_session, restaurant, "jewellery_showcase", TemplatePurpose.PRODUCT_SHOWCASE)
    await _make_template(db_session, restaurant, "jewellery_enquiry_draft", TemplatePurpose.ENQUIRY, status=TemplateStatus.DRAFT)

    resp = await client.get(f"/api/v1/restaurants/{restaurant.id}/whatsapp-templates/recommendations", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["product_showcase"]["id"] == str(product_tpl.id)
    # Enquiry has a template, but it's DRAFT (not approved) -- must not be recommended.
    assert body["enquiry"] is None
    # Jewellers' own recommended-purposes list -- confirms niche-specific shape, not every purpose.
    assert set(body.keys()) == {"product_showcase", "enquiry", "appointment", "follow_up", "offer"}


async def test_tenant_with_no_templates_gets_all_none_not_an_error(client, db_session):
    restaurant = await _make_restaurant(db_session, "empty-salon", niche_type="salon")
    headers = await _register_and_login(client, restaurant.id)

    resp = await client.get(f"/api/v1/restaurants/{restaurant.id}/whatsapp-templates/recommendations", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body.keys()) == {"appointment", "confirmation", "reminder", "follow_up"}
    assert all(v is None for v in body.values())


async def test_cashier_can_read_recommendations(client, db_session):
    restaurant = await _make_restaurant(db_session, "cashier-read", niche_type="restaurant")
    headers = await _register_and_login(client, restaurant.id, role="cashier", email="cashier@template-rec-test.dev")

    resp = await client.get(f"/api/v1/restaurants/{restaurant.id}/whatsapp-templates/recommendations", headers=headers)
    assert resp.status_code == 200, resp.text


async def test_owner_cannot_read_another_tenants_recommendations(client, db_session):
    restaurant_a = await _make_restaurant(db_session, "tenant-a")
    restaurant_b = await _make_restaurant(db_session, "tenant-b")
    headers_a = await _register_and_login(client, restaurant_a.id, email="owner-a@template-rec-test.dev")

    resp = await client.get(f"/api/v1/restaurants/{restaurant_b.id}/whatsapp-templates/recommendations", headers=headers_a)
    assert resp.status_code == 403


async def test_a_business_with_no_niche_type_falls_back_to_every_purpose(client, db_session):
    restaurant = await _make_restaurant(db_session, "no-niche", niche_type=None)
    headers = await _register_and_login(client, restaurant.id)

    resp = await client.get(f"/api/v1/restaurants/{restaurant.id}/whatsapp-templates/recommendations", headers=headers)
    assert resp.status_code == 200, resp.text
    from app.models.enums import TemplatePurpose as TP
    assert set(resp.json().keys()) == {p.value for p in TP}
