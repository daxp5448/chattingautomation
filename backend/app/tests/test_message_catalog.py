"""API-level proof for the Message Management system (see app/services/message_catalog.py,
and its endpoints on niche_templates.py / flow_definitions.py / messages.py): listing a
niche template's or a business's own flow messages as a searchable catalog, editing one
message's text, restoring defaults (niche-template level restores to the original seed
file; business-flow level restores to the niche template's current text), tenant
isolation, RBAC, and the shared preview endpoint.
"""

from sqlalchemy import select

from app.models.enums import EngagementType
from app.models.niche_template import NicheTemplate
from app.niche_seeds.restaurant import TEMPLATE
from app.tests.test_flow_definitions_home_buttons import _login, _make_owner_tenant
from app.tests.test_restaurants import _register_super_admin


async def _get_or_create_restaurant_template(db_session) -> NicheTemplate:
    """Every test file manages its own NicheTemplate fixtures (the test DB starts
    empty) -- mirrors test_flow_definitions_home_buttons.py::_make_owner_tenant's own
    "reuse if a prior call in this test already created one" pattern, since `code` is
    globally unique."""
    existing = (await db_session.execute(select(NicheTemplate).where(NicheTemplate.code == TEMPLATE["code"]))).scalar_one_or_none()
    if existing is not None:
        return existing
    template = NicheTemplate(
        code=TEMPLATE["code"], name=TEMPLATE["name"], action_type=EngagementType(TEMPLATE["action_type"]),
        icon=TEMPLATE["icon"], welcome_message=TEMPLATE["welcome_message"],
        welcome_banner_image=TEMPLATE["welcome_banner_image"], welcome_buttons=TEMPLATE["welcome_buttons"],
        default_catalog=TEMPLATE["default_catalog"], default_flow_steps=TEMPLATE["default_flow_steps"],
        terminology=TEMPLATE["terminology"], default_modules=TEMPLATE["default_modules"],
    )
    db_session.add(template)
    await db_session.commit()
    return template


# --- niche-template-level message catalog (Super Admin) -----------------------------------


async def test_list_niche_template_messages_returns_every_text_bearing_step(client, db_session):
    headers = await _register_super_admin(client)
    restaurant_template = await _get_or_create_restaurant_template(db_session)

    resp = await client.get(f"/api/v1/niche-templates/{restaurant_template.id}/messages", headers=headers)
    assert resp.status_code == 200
    entries = resp.json()
    by_key = {e["message_key"]: e for e in entries}
    assert "restaurant.welcome" in by_key
    assert "restaurant.human_handoff" in by_key
    assert by_key["restaurant.human_handoff"]["field"] == "message"
    assert by_key["restaurant.welcome"]["field"] == "prompt"
    assert "{{business_name}}" in by_key["restaurant.welcome"]["text"]
    # condition/delay/api_call/ai_response steps (none exist in restaurant.py today, but
    # the point stands) never show up -- every entry here must be a real, editable
    # customer-visible message, not an internal auto-advance directive.
    assert all(e["step_type"] not in ("condition", "delay", "api_call", "ai_response") for e in entries)


async def test_edit_and_restore_niche_template_message(client, db_session):
    headers = await _register_super_admin(client)
    restaurant_template = await _get_or_create_restaurant_template(db_session)
    template_id = restaurant_template.id

    original = await client.get(f"/api/v1/niche-templates/{template_id}/messages", headers=headers)
    original_welcome = next(e for e in original.json() if e["step_id"] == "welcome")["text"]

    edited = await client.patch(
        f"/api/v1/niche-templates/{template_id}/messages/welcome", headers=headers, json={"text": "Hiya {{business_name}}!"}
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["text"] == "Hiya {{business_name}}!"

    # Persisted, and the template is now flagged customized (protects it from seed re-sync).
    reread = await client.get(f"/api/v1/niche-templates/{template_id}", headers=headers)
    assert reread.json()["is_customized"] is True
    reread_messages = await client.get(f"/api/v1/niche-templates/{template_id}/messages", headers=headers)
    assert next(e for e in reread_messages.json() if e["step_id"] == "welcome")["text"] == "Hiya {{business_name}}!"

    restored = await client.post(f"/api/v1/niche-templates/{template_id}/messages/welcome/restore-default", headers=headers)
    assert restored.status_code == 200, restored.text
    assert restored.json()["text"] == original_welcome


async def test_niche_template_message_edit_requires_super_admin(client, db_session):
    headers = await _register_super_admin(client)
    restaurant_template = await _get_or_create_restaurant_template(db_session)

    _, owner_creds = await _make_owner_tenant(db_session, "msgcatalog-rbac")
    owner_headers = await _login(client, **owner_creds)

    resp = await client.patch(
        f"/api/v1/niche-templates/{restaurant_template.id}/messages/welcome", headers=owner_headers, json={"text": "Hacked"}
    )
    assert resp.status_code == 403


async def test_unknown_step_id_returns_404(client, db_session):
    headers = await _register_super_admin(client)
    restaurant_template = await _get_or_create_restaurant_template(db_session)

    resp = await client.patch(
        f"/api/v1/niche-templates/{restaurant_template.id}/messages/not_a_real_step",
        headers=headers, json={"text": "Anything"},
    )
    assert resp.status_code == 404


# --- business-flow-level message catalog (Owner/Manager) ----------------------------------


async def test_list_flow_messages_flags_customization_against_niche_default(db_session, client):
    restaurant, creds = await _make_owner_tenant(db_session, "msgcatalog-flow")
    headers = await _login(client, **creds)

    initial = await client.get(f"/api/v1/restaurants/{restaurant.id}/flow/messages", headers=headers)
    assert initial.status_code == 200
    welcome_entry = next(e for e in initial.json() if e["step_id"] == "welcome")
    assert welcome_entry["is_customized"] is False
    assert welcome_entry["default_text"] == welcome_entry["text"]

    edited = await client.patch(
        f"/api/v1/restaurants/{restaurant.id}/flow/messages/welcome", headers=headers, json={"text": "Custom welcome!"}
    )
    assert edited.status_code == 200
    assert edited.json()["is_customized"] is True
    assert edited.json()["text"] == "Custom welcome!"

    reread = await client.get(f"/api/v1/restaurants/{restaurant.id}/flow/messages", headers=headers)
    reread_welcome = next(e for e in reread.json() if e["step_id"] == "welcome")
    assert reread_welcome["is_customized"] is True
    assert reread_welcome["text"] == "Custom welcome!"
    assert reread_welcome["default_text"] != "Custom welcome!"

    restored = await client.post(f"/api/v1/restaurants/{restaurant.id}/flow/messages/welcome/restore-default", headers=headers)
    assert restored.status_code == 200
    assert restored.json()["is_customized"] is False
    assert restored.json()["text"] == welcome_entry["default_text"]


async def test_flow_messages_are_tenant_isolated(db_session, client):
    restaurant_a, creds_a = await _make_owner_tenant(db_session, "msgcatalog-a")
    restaurant_b, creds_b = await _make_owner_tenant(db_session, "msgcatalog-b")
    headers_a = await _login(client, **creds_a)

    resp = await client.get(f"/api/v1/restaurants/{restaurant_b.id}/flow/messages", headers=headers_a)
    assert resp.status_code == 403

    resp = await client.patch(
        f"/api/v1/restaurants/{restaurant_b.id}/flow/messages/welcome", headers=headers_a, json={"text": "Hacked"}
    )
    assert resp.status_code == 403


# --- preview -------------------------------------------------------------------------------


async def test_preview_renders_supplied_variables(client):
    headers = await _register_super_admin(client)
    resp = await client.post(
        "/api/v1/messages/preview", headers=headers,
        json={"text": "Hi {{customer_name}}, order {{order_id}} is ready!", "variables": {"customer_name": "Rohan", "order_id": "PC-42"}},
    )
    assert resp.status_code == 200
    assert resp.json()["rendered"] == "Hi Rohan, order PC-42 is ready!"


async def test_preview_falls_back_to_sample_variables_when_none_supplied(client):
    headers = await _register_super_admin(client)
    resp = await client.post(
        "/api/v1/messages/preview", headers=headers, json={"text": "Welcome to {{business_name}}!"}
    )
    assert resp.status_code == 200
    assert resp.json()["rendered"] == "Welcome to Sample Business!"


async def test_preview_unknown_variable_renders_as_empty_not_literal(client):
    headers = await _register_super_admin(client)
    resp = await client.post(
        "/api/v1/messages/preview", headers=headers, json={"text": "Value: [{{totally_unknown_var}}]"}
    )
    assert resp.status_code == 200
    assert resp.json()["rendered"] == "Value: []"
