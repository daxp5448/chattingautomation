"""API-level proof for the generic engine's home-buttons endpoint: tenant isolation, the
full read/update round trip (title/icon/order/visible/destination), every validation rule
in app/services/flow_shape_validation.py, and -- the real payoff -- that a button marked
`visible: false` is genuinely untappable through the real conversation engine, not just
hidden from a list.
"""

import itertools

from sqlalchemy import select

from app.core.security import encrypt_secret, hash_password
from app.models.customer import Customer
from app.models.enums import EngagementType, UserRole
from app.models.generic_conversation_state import GenericConversationState
from app.models.niche_template import NicheTemplate
from app.models.restaurant import Restaurant
from app.models.user import User
from app.niche_seeds.restaurant import TEMPLATE
from app.services.generic_flow_engine import GenericInteraction, process_inbound_message
from app.services.niche_provisioning import provision_from_template
from app.services.whatsapp_client import InMemoryWhatsAppSender

_wamid_counter = itertools.count(1)


def _next_wamid() -> str:
    return f"wamid.homebuttons.test.{next(_wamid_counter)}"


async def _make_owner_tenant(db_session, slug: str) -> tuple[Restaurant, dict]:
    restaurant = Restaurant(
        name=f"Home Buttons Test {slug}", slug=f"home-buttons-test-{slug}",
        whatsapp_phone_number_id=f"HB_{slug.upper()}_PNID",
        whatsapp_access_token_encrypted=encrypt_secret("fake-token"),
    )
    db_session.add(restaurant)
    await db_session.flush()

    # `code` is globally unique -- reuse an already-seeded "restaurant" template row if a
    # prior call in this same test already created one, rather than colliding on insert.
    existing = (await db_session.execute(select(NicheTemplate).where(NicheTemplate.code == TEMPLATE["code"]))).scalar_one_or_none()
    if existing is not None:
        template = existing
    else:
        template = NicheTemplate(
            code=TEMPLATE["code"], name=TEMPLATE["name"], action_type=EngagementType(TEMPLATE["action_type"]),
            icon=TEMPLATE["icon"], welcome_message=TEMPLATE["welcome_message"],
            welcome_banner_image=TEMPLATE["welcome_banner_image"], welcome_buttons=TEMPLATE["welcome_buttons"],
            default_catalog=TEMPLATE["default_catalog"], default_flow_steps=TEMPLATE["default_flow_steps"],
            terminology=TEMPLATE["terminology"], default_modules=TEMPLATE["default_modules"],
        )
        db_session.add(template)
        await db_session.flush()
    await provision_from_template(db_session, restaurant, template)

    email = f"owner-hb-{slug}@kelviontech.dev"
    password = "OwnerPass123!"
    user = User(email=email, hashed_password=hash_password(password), role=UserRole.OWNER, restaurant_id=restaurant.id, is_active=True)
    db_session.add(user)
    await db_session.commit()
    return restaurant, {"email": email, "password": password}


async def _login(client, email: str, password: str) -> dict:
    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


# --- tenant isolation --------------------------------------------------------------------


async def test_owner_cannot_read_or_edit_another_tenants_flow(db_session, client):
    restaurant_a, creds_a = await _make_owner_tenant(db_session, "flowa")
    restaurant_b, creds_b = await _make_owner_tenant(db_session, "flowb")
    headers_a = await _login(client, **creds_a)

    resp = await client.get(f"/api/v1/restaurants/{restaurant_b.id}/flow", headers=headers_a)
    assert resp.status_code == 403

    resp = await client.get(f"/api/v1/restaurants/{restaurant_b.id}/flow/home-buttons", headers=headers_a)
    assert resp.status_code == 403

    resp = await client.patch(
        f"/api/v1/restaurants/{restaurant_b.id}/flow/home-buttons", headers=headers_a,
        json={"buttons": [{"id": "welcome:order", "title": "Order", "visible": True, "destination_step_id": "category_select"}]},
    )
    assert resp.status_code == 403


# --- happy path: read -> update -> read again --------------------------------------------


async def test_full_home_buttons_read_and_update_round_trip(db_session, client):
    restaurant, creds = await _make_owner_tenant(db_session, "roundtrip")
    headers = await _login(client, **creds)

    initial = await client.get(f"/api/v1/restaurants/{restaurant.id}/flow/home-buttons", headers=headers)
    assert initial.status_code == 200
    initial_buttons = initial.json()["buttons"]
    assert len(initial_buttons) == 7  # restaurant.py's welcome step has 7 static_options
    assert {b["id"] for b in initial_buttons} == {
        "welcome:order", "welcome:quick_order", "welcome:cart", "welcome:offers",
        "welcome:location", "welcome:contact", "welcome:human",
    }
    # Every existing button's destination resolved correctly (via routes or next fallback).
    by_id = {b["id"]: b for b in initial_buttons}
    assert by_id["welcome:order"]["destination_step_id"] == "category_select"
    assert by_id["welcome:offers"]["destination_step_id"] == "offers_info"

    new_buttons = [
        {"id": "welcome:order", "title": "Order Now", "icon": "\U0001f6d2", "visible": True, "destination_step_id": "category_select"},
        {"id": "welcome:contact", "title": "Call Us", "icon": None, "visible": False, "destination_step_id": "contact_info"},
        {"id": "welcome:new", "title": "New Button", "icon": "✨", "visible": True, "destination_step_id": "category_select"},
    ]
    updated = await client.patch(
        f"/api/v1/restaurants/{restaurant.id}/flow/home-buttons", headers=headers, json={"buttons": new_buttons}
    )
    assert updated.status_code == 200, updated.text
    result_buttons = {b["id"]: b for b in updated.json()["buttons"]}
    assert len(result_buttons) == 3  # whole-list-replace: the 2 dropped buttons are gone
    assert result_buttons["welcome:order"]["title"] == "Order Now"
    assert result_buttons["welcome:order"]["icon"] == "\U0001f6d2"
    assert result_buttons["welcome:contact"]["visible"] is False
    assert result_buttons["welcome:new"]["destination_step_id"] == "category_select"

    # Reading again (a fresh GET) confirms it was actually persisted, not just echoed back.
    reread = await client.get(f"/api/v1/restaurants/{restaurant.id}/flow/home-buttons", headers=headers)
    assert {b["id"] for b in reread.json()["buttons"]} == {"welcome:order", "welcome:contact", "welcome:new"}

    # Every other step in the flow is untouched -- fetch the full flow and confirm.
    full_flow = await client.get(f"/api/v1/restaurants/{restaurant.id}/flow", headers=headers)
    step_ids = {s["step_id"] for s in full_flow.json()["steps"]}
    assert "category_select" in step_ids and "order_confirm" in step_ids  # unrelated steps survived


# --- validation rejections -----------------------------------------------------------------


async def test_rejects_empty_button_list(db_session, client):
    restaurant, creds = await _make_owner_tenant(db_session, "empty")
    headers = await _login(client, **creds)
    resp = await client.patch(f"/api/v1/restaurants/{restaurant.id}/flow/home-buttons", headers=headers, json={"buttons": []})
    assert resp.status_code == 422  # min_length=1 on the schema itself


async def test_rejects_duplicate_button_ids(db_session, client):
    restaurant, creds = await _make_owner_tenant(db_session, "dupids")
    headers = await _login(client, **creds)
    resp = await client.patch(
        f"/api/v1/restaurants/{restaurant.id}/flow/home-buttons", headers=headers,
        json={"buttons": [
            {"id": "welcome:a", "title": "A", "visible": True, "destination_step_id": "category_select"},
            {"id": "welcome:a", "title": "A again", "visible": True, "destination_step_id": "category_select"},
        ]},
    )
    assert resp.status_code == 400
    assert "duplicate" in resp.json()["detail"].lower()


async def test_rejects_unknown_destination_step(db_session, client):
    restaurant, creds = await _make_owner_tenant(db_session, "baddest")
    headers = await _login(client, **creds)
    resp = await client.patch(
        f"/api/v1/restaurants/{restaurant.id}/flow/home-buttons", headers=headers,
        json={"buttons": [{"id": "welcome:x", "title": "X", "visible": True, "destination_step_id": "does_not_exist"}]},
    )
    assert resp.status_code == 400
    assert "does_not_exist" in resp.json()["detail"]


async def test_rejects_title_over_20_chars(db_session, client):
    restaurant, creds = await _make_owner_tenant(db_session, "longtitle")
    headers = await _login(client, **creds)
    resp = await client.patch(
        f"/api/v1/restaurants/{restaurant.id}/flow/home-buttons", headers=headers,
        json={"buttons": [{"id": "welcome:x", "title": "This Title Is Definitely Too Long", "visible": True, "destination_step_id": "category_select"}]},
    )
    assert resp.status_code == 400
    assert "20-char" in resp.json()["detail"]


async def test_rejects_wildcard_suffix_button_id(db_session, client):
    restaurant, creds = await _make_owner_tenant(db_session, "wildcard")
    headers = await _login(client, **creds)
    resp = await client.patch(
        f"/api/v1/restaurants/{restaurant.id}/flow/home-buttons", headers=headers,
        json={"buttons": [{"id": "welcome:*", "title": "X", "visible": True, "destination_step_id": "category_select"}]},
    )
    assert resp.status_code == 400
    assert "wildcard" in resp.json()["detail"].lower()


# --- the real payoff: a hidden button is genuinely untappable through the real engine ----


async def test_hidden_button_is_untappable_through_the_real_engine(db_session, client):
    restaurant, creds = await _make_owner_tenant(db_session, "hiddenreal")
    headers = await _login(client, **creds)

    current = await client.get(f"/api/v1/restaurants/{restaurant.id}/flow/home-buttons", headers=headers)
    buttons = current.json()["buttons"]
    for b in buttons:
        if b["id"] == "welcome:contact":
            b["visible"] = False
    updated = await client.patch(f"/api/v1/restaurants/{restaurant.id}/flow/home-buttons", headers=headers, json={"buttons": buttons})
    assert updated.status_code == 200

    sender = InMemoryWhatsAppSender()
    await process_inbound_message(
        db_session, sender, restaurant, "919876543299",
        GenericInteraction(kind="text", text="hi", profile_name="Test Customer"),
        wa_message_id=_next_wamid(),
    )
    # Confirm the hidden button is genuinely gone from what's rendered, not just flagged.
    last_interactive = next(m for m in reversed(sender.sent) if m.payload.get("type") == "interactive")
    interactive = last_interactive.payload["interactive"]
    rendered_ids = (
        {b["reply"]["id"] for b in interactive["action"]["buttons"]}
        if interactive["type"] == "button"
        else {r["id"] for r in interactive["action"]["sections"][0]["rows"]}
    )
    assert "welcome:contact" not in rendered_ids

    # And tapping its id anyway (e.g. a stale WhatsApp client cache, or someone probing)
    # is treated as invalid input, not routed anywhere.
    customer = (await db_session.execute(select(Customer).where(Customer.restaurant_id == restaurant.id))).scalar_one()
    customer_id = customer.id  # captured before expire_all() below invalidates the object
    state_before = (await db_session.execute(select(GenericConversationState).where(GenericConversationState.customer_id == customer_id))).scalar_one()
    assert state_before.current_step == "welcome"

    await process_inbound_message(
        db_session, sender, restaurant, "919876543299",
        GenericInteraction(kind="button_reply", reply_id="welcome:contact", text="Contact Restaurant"),
        wa_message_id=_next_wamid(),
    )
    db_session.expire_all()
    state_after = (await db_session.execute(select(GenericConversationState).where(GenericConversationState.customer_id == customer_id))).scalar_one()
    assert state_after.current_step == "welcome"  # never advanced to contact_info


# --- generalized per-step buttons editor (Bot Preview side-by-side editor) --------------


async def test_get_and_update_buttons_on_a_non_entry_step(db_session, client):
    """GET/PATCH /flow/steps/{step_id}/buttons -- the same _extract_home_buttons/
    _apply_home_buttons machinery as /home-buttons, generalized to any step_id."""
    restaurant, creds = await _make_owner_tenant(db_session, "stepbuttons")
    headers = await _login(client, **creds)

    initial = await client.get(f"/api/v1/restaurants/{restaurant.id}/flow/steps/cart_menu/buttons", headers=headers)
    assert initial.status_code == 200, initial.text
    initial_ids = {b["id"] for b in initial.json()["buttons"]}
    assert initial_ids == {"cart:add_more", "cart:checkout"}

    updated = await client.patch(
        f"/api/v1/restaurants/{restaurant.id}/flow/steps/cart_menu/buttons", headers=headers,
        json={"buttons": [
            {"id": "cart:add_more", "title": "Add More", "icon": None, "visible": True, "destination_step_id": "category_select"},
            {"id": "cart:checkout", "title": "Checkout Now", "icon": "✅", "visible": True, "destination_step_id": "address_capture"},
        ]},
    )
    assert updated.status_code == 200, updated.text
    by_id = {b["id"]: b for b in updated.json()["buttons"]}
    assert by_id["cart:checkout"]["title"] == "Checkout Now"
    assert by_id["cart:checkout"]["icon"] == "✅"

    # Every other step in the flow is untouched.
    full_flow = await client.get(f"/api/v1/restaurants/{restaurant.id}/flow", headers=headers)
    welcome_step = next(s for s in full_flow.json()["steps"] if s["step_id"] == "welcome")
    assert len(welcome_step["static_options"]) == 7


async def test_step_buttons_endpoint_404s_for_unknown_step(db_session, client):
    restaurant, creds = await _make_owner_tenant(db_session, "stepbuttons404")
    headers = await _login(client, **creds)
    resp = await client.get(f"/api/v1/restaurants/{restaurant.id}/flow/steps/not_a_real_step/buttons", headers=headers)
    assert resp.status_code == 404
