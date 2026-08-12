"""Subscription lifecycle: suspend/cancel blocks the bot, only super_admin can flip
status, and every status change is recorded in the audit log.
"""
from sqlalchemy import select

from app.models.conversation_state import ConversationState
from app.repositories.audit_log_repository import AuditLogRepository
from app.tests.test_flow_engine import (  # noqa: F401 -- reuse fixtures/helpers
    _message_value,
    _post_webhook,
    _text,
    _use_in_memory_sender,
    demo_tenant,
)


async def _register_super_admin(client, email="status-admin@kelviontech.dev"):
    resp = await client.post(
        "/api/v1/auth/register", json={"email": email, "password": "TestPass123!", "role": "super_admin"}
    )
    assert resp.status_code == 201, resp.text
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": "TestPass123!"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def test_suspended_restaurant_bot_stops_responding(client, db_session, demo_tenant, _use_in_memory_sender):
    restaurant = demo_tenant["restaurant"]
    restaurant.status = "suspended"
    await db_session.commit()

    await _post_webhook(client, _message_value(_text("hi")))

    # No conversation state should ever be created for a blocked restaurant.
    result = await db_session.execute(
        select(ConversationState).where(ConversationState.restaurant_id == restaurant.id)
    )
    assert result.scalar_one_or_none() is None

    # The customer still hears something, rather than silence.
    assert len(_use_in_memory_sender.sent) == 1
    assert "isn't taking WhatsApp orders" in _use_in_memory_sender.sent[0].payload["text"]["body"]


async def test_cancelled_restaurant_bot_stops_responding(client, db_session, demo_tenant, _use_in_memory_sender):
    restaurant = demo_tenant["restaurant"]
    restaurant.status = "cancelled"
    await db_session.commit()

    await _post_webhook(client, _message_value(_text("hi")))

    result = await db_session.execute(
        select(ConversationState).where(ConversationState.restaurant_id == restaurant.id)
    )
    assert result.scalar_one_or_none() is None
    assert len(_use_in_memory_sender.sent) == 1


async def test_reactivated_restaurant_bot_responds_again(client, db_session, demo_tenant, _use_in_memory_sender):
    # Go through the real PATCH endpoint rather than mutating the ORM object directly --
    # that's what actually invalidates the phone_number_id -> restaurant cache the webhook
    # hot path reads from (see app/api/v1/routers/restaurants.py::update_restaurant). A
    # raw session mutation, like the other tests in this file use, wouldn't touch that
    # cache and would make this test depend on within-TTL timing instead of real behavior.
    restaurant = demo_tenant["restaurant"]
    admin_headers = await _register_super_admin(client)

    resp = await client.patch(
        f"/api/v1/restaurants/{restaurant.id}", json={"status": "suspended"}, headers=admin_headers
    )
    assert resp.status_code == 200, resp.text
    await _post_webhook(client, _message_value(_text("hi")))

    resp = await client.patch(
        f"/api/v1/restaurants/{restaurant.id}", json={"status": "active"}, headers=admin_headers
    )
    assert resp.status_code == 200, resp.text
    await _post_webhook(client, _message_value(_text("hi")))

    result = await db_session.execute(
        select(ConversationState).where(ConversationState.restaurant_id == restaurant.id)
    )
    assert result.scalar_one_or_none() is not None


async def test_only_super_admin_can_change_status(client, demo_tenant):
    admin_headers = await _register_super_admin(client)
    restaurant = demo_tenant["restaurant"]

    owner_resp = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "owner-status-test@kelviontech.dev",
            "password": "TestPass123!",
            "role": "owner",
            "restaurant_id": str(restaurant.id),
        },
        headers=admin_headers,
    )
    assert owner_resp.status_code == 201, owner_resp.text
    owner_login = await client.post(
        "/api/v1/auth/login", json={"email": "owner-status-test@kelviontech.dev", "password": "TestPass123!"}
    )
    owner_headers = {"Authorization": f"Bearer {owner_login.json()['access_token']}"}

    # Owner can edit ordinary settings...
    resp = await client.patch(
        f"/api/v1/restaurants/{restaurant.id}", json={"delivery_charge": 25}, headers=owner_headers
    )
    assert resp.status_code == 200, resp.text

    # ...but cannot suspend/cancel/reactivate their own restaurant.
    resp = await client.patch(
        f"/api/v1/restaurants/{restaurant.id}", json={"status": "cancelled"}, headers=owner_headers
    )
    assert resp.status_code == 403, resp.text

    # Super admin can.
    resp = await client.patch(
        f"/api/v1/restaurants/{restaurant.id}", json={"status": "suspended"}, headers=admin_headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "suspended"


async def test_status_change_is_audit_logged(client, db_session, demo_tenant):
    admin_headers = await _register_super_admin(client)
    restaurant = demo_tenant["restaurant"]

    resp = await client.patch(
        f"/api/v1/restaurants/{restaurant.id}", json={"status": "suspended"}, headers=admin_headers
    )
    assert resp.status_code == 200, resp.text

    entries = await AuditLogRepository(db_session).list_for_restaurant(restaurant.id)
    assert len(entries) == 1
    assert entries[0].action == "status_change"
    # demo_tenant doesn't explicitly set a status, so it starts at the model default.
    assert entries[0].diff == {"from": "onboarding", "to": "suspended"}

    log_resp = await client.get(f"/api/v1/restaurants/{restaurant.id}/audit-log", headers=admin_headers)
    assert log_resp.status_code == 200, log_resp.text
    assert len(log_resp.json()) == 1

    # Editing an unrelated field must NOT create a spurious audit entry.
    resp = await client.patch(
        f"/api/v1/restaurants/{restaurant.id}", json={"delivery_charge": 40}, headers=admin_headers
    )
    assert resp.status_code == 200, resp.text
    entries_after = await AuditLogRepository(db_session).list_for_restaurant(restaurant.id)
    assert len(entries_after) == 1
