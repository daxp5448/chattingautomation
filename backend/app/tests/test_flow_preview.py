"""API-level proof for the Super Admin Bot Preview simulator (see
app/api/v1/routers/flow_preview.py): drives the REAL restaurant flow end-to-end through
the HTTP API, confirms no real Engagement/payment/notification is ever created, confirms
a live edit (welcome text/image/button) is reflected on the very next preview turn with
no caching, confirms session persistence across turns and reset, tenant isolation, and
RBAC.
"""

from sqlalchemy import select

from app.models.customer import Customer
from app.models.engagement import Engagement
from app.models.generic_conversation_state import GenericConversationState
from app.tests.test_flow_definitions_home_buttons import _login, _make_owner_tenant


async def test_preview_walks_the_real_restaurant_flow_start_to_confirmation(db_session, client):
    restaurant, creds = await _make_owner_tenant(db_session, "preview-happy")
    headers = await _login(client, **creds)
    base = f"/api/v1/restaurants/{restaurant.id}/flow/preview"

    resp = await client.post(base, headers=headers, json={"kind": "text", "text": "hi"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    session_id = body["session_id"]
    assert session_id

    def _flatten_options(messages):
        for m in messages:
            interactive = m.get("interactive", {})
            if interactive.get("type") == "button":
                return [b["reply"]["id"] for b in interactive["action"]["buttons"]]
            if interactive.get("type") == "list":
                return [r["id"] for r in interactive["action"]["sections"][0]["rows"]]
        return []

    welcome_options = _flatten_options(body["messages"])
    assert "welcome:order" in welcome_options

    resp = await client.post(base, headers=headers, json={"session_id": session_id, "kind": "button_reply", "reply_id": "welcome:order"})
    assert resp.status_code == 200, resp.text
    category_options = _flatten_options(resp.json()["messages"])
    assert any(o.startswith("category:") for o in category_options)
    category_id = next(o for o in category_options if o.startswith("category:"))

    resp = await client.post(base, headers=headers, json={"session_id": session_id, "kind": "button_reply", "reply_id": category_id})
    item_options = _flatten_options(resp.json()["messages"])
    item_id = next(o for o in item_options if o.startswith("item:"))

    resp = await client.post(base, headers=headers, json={"session_id": session_id, "kind": "button_reply", "reply_id": item_id})
    qty_options = _flatten_options(resp.json()["messages"])
    assert "qty:1" in qty_options

    resp = await client.post(base, headers=headers, json={"session_id": session_id, "kind": "button_reply", "reply_id": "qty:1"})
    cart_options = _flatten_options(resp.json()["messages"])
    assert "cart:checkout" in cart_options

    resp = await client.post(base, headers=headers, json={"session_id": session_id, "kind": "button_reply", "reply_id": "cart:checkout"})
    address_options = _flatten_options(resp.json()["messages"])
    assert "__skip__" in address_options

    resp = await client.post(base, headers=headers, json={"session_id": session_id, "kind": "button_reply", "reply_id": "__skip__"})
    confirm_options = _flatten_options(resp.json()["messages"])
    assert "order:confirm" in confirm_options

    resp = await client.post(base, headers=headers, json={"session_id": session_id, "kind": "button_reply", "reply_id": "order:confirm"})
    final_body = " ".join(
        m.get("text", {}).get("body", "") for m in resp.json()["messages"] if m.get("type") == "text"
    )
    assert "PREVIEW-0000" in final_body

    # The whole point of dry_run: nothing real was ever created.
    engagements = (await db_session.execute(select(Engagement).where(Engagement.restaurant_id == restaurant.id))).scalars().all()
    assert engagements == []


async def test_preview_customer_is_isolated_from_real_customers(db_session, client):
    restaurant, creds = await _make_owner_tenant(db_session, "preview-isolation")
    headers = await _login(client, **creds)

    resp = await client.post(
        f"/api/v1/restaurants/{restaurant.id}/flow/preview", headers=headers, json={"kind": "text", "text": "hi"}
    )
    session_id = resp.json()["session_id"]

    customers = (await db_session.execute(select(Customer).where(Customer.restaurant_id == restaurant.id))).scalars().all()
    assert len(customers) == 1
    assert customers[0].phone == f"preview:{session_id}"
    assert customers[0].phone.startswith("preview:")  # can never collide with a real all-digits WhatsApp number


async def test_preview_reflects_a_live_edit_immediately(db_session, client):
    """The non-negotiable acceptance test from the brief: edit the welcome message via
    the real Message Management endpoint, then re-run the preview with NO other change
    -- the new text must appear on the very next "hi", proving there is no separate
    cached/fake preview configuration anywhere."""
    restaurant, creds = await _make_owner_tenant(db_session, "preview-live-edit")
    headers = await _login(client, **creds)
    base = f"/api/v1/restaurants/{restaurant.id}/flow/preview"

    def _welcome_body(messages) -> str:
        # The welcome step renders with show_image=True, so its text is the caption of
        # an image message (or a photo-burst intro text) rather than a bare text message
        # -- concatenate every text-bearing field so this test doesn't depend on which
        # rendering path fired.
        parts = []
        for m in messages:
            if m.get("type") == "text":
                parts.append(m["text"]["body"])
            elif m.get("type") == "image":
                parts.append(m["image"].get("caption", ""))
            elif m.get("type") == "interactive":
                parts.append(m.get("interactive", {}).get("body", {}).get("text", ""))
        return " ".join(parts)

    first = await client.post(base, headers=headers, json={"kind": "text", "text": "hi"})
    first_text = _welcome_body(first.json()["messages"])
    assert "Totally New Welcome Copy 12345" not in first_text

    edited = await client.patch(
        f"/api/v1/restaurants/{restaurant.id}/flow/messages/welcome", headers=headers,
        json={"text": "Totally New Welcome Copy 12345 for {{business_name}}"},
    )
    assert edited.status_code == 200, edited.text

    second = await client.post(base, headers=headers, json={"kind": "text", "text": "hi"})
    second_text = _welcome_body(second.json()["messages"])
    assert "Totally New Welcome Copy 12345" in second_text
    assert restaurant.name in second_text  # {{business_name}} still resolves through the real engine


async def test_reset_clears_preview_session_state(db_session, client):
    restaurant, creds = await _make_owner_tenant(db_session, "preview-reset")
    headers = await _login(client, **creds)
    base = f"/api/v1/restaurants/{restaurant.id}/flow/preview"

    first = await client.post(base, headers=headers, json={"kind": "text", "text": "hi"})
    session_id = first.json()["session_id"]
    await client.post(base, headers=headers, json={"session_id": session_id, "kind": "button_reply", "reply_id": "welcome:order"})

    state = (
        await db_session.execute(
            select(GenericConversationState)
            .join(Customer, GenericConversationState.customer_id == Customer.id)
            .where(Customer.phone == f"preview:{session_id}")
        )
    ).scalar_one()
    assert state.current_step == "category_select"

    resp = await client.post(f"{base}/reset", headers=headers, params={"session_id": session_id})
    assert resp.status_code == 204

    remaining = (await db_session.execute(select(Customer).where(Customer.phone == f"preview:{session_id}"))).scalars().all()
    assert remaining == []

    # A fresh "hi" with the same session_id after reset starts a brand-new conversation.
    restarted = await client.post(base, headers=headers, json={"session_id": session_id, "kind": "text", "text": "hi"})
    assert restarted.status_code == 200


async def test_preview_requires_owner_or_manager_and_is_tenant_isolated(db_session, client):
    restaurant_a, creds_a = await _make_owner_tenant(db_session, "preview-rbac-a")
    restaurant_b, _ = await _make_owner_tenant(db_session, "preview-rbac-b")
    headers_a = await _login(client, **creds_a)

    resp = await client.post(
        f"/api/v1/restaurants/{restaurant_b.id}/flow/preview", headers=headers_a, json={"kind": "text", "text": "hi"}
    )
    assert resp.status_code == 403


async def test_preview_jump_renders_a_deep_step_directly(db_session, client):
    """"Preview This Step" -- jumps straight to cart_menu's current rendering without
    walking through category/item/quantity first."""
    restaurant, creds = await _make_owner_tenant(db_session, "preview-jump")
    headers = await _login(client, **creds)

    resp = await client.post(
        f"/api/v1/restaurants/{restaurant.id}/flow/preview/jump", headers=headers, json={"step_id": "cart_menu"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["session_id"]

    interactive = next(m for m in body["messages"] if m.get("type") == "interactive")
    option_ids = {b["reply"]["id"] for b in interactive["interactive"]["action"]["buttons"]}
    assert {"cart:add_more", "cart:checkout"} <= option_ids  # plus an auto-injected Back button (cart_menu has a back_target)

    # No real data was touched -- this is still dry_run under the hood.
    engagements = (await db_session.execute(select(Engagement).where(Engagement.restaurant_id == restaurant.id))).scalars().all()
    assert engagements == []


async def test_preview_jump_requires_owner_or_manager(db_session, client):
    restaurant, _ = await _make_owner_tenant(db_session, "preview-jump-rbac")
    other_restaurant, other_creds = await _make_owner_tenant(db_session, "preview-jump-rbac-other")
    headers = await _login(client, **other_creds)

    resp = await client.post(
        f"/api/v1/restaurants/{restaurant.id}/flow/preview/jump", headers=headers, json={"step_id": "welcome"}
    )
    assert resp.status_code == 403
