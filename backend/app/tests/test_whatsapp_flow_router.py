"""Proof for POST /restaurants/{id}/whatsapp-flow/enable|disable -- role gating, the
"raise on failure, only mutate local state after every Graph API call actually succeeds"
gateway idiom (same shape whatsapp_templates.py's submit endpoint already uses), and the
idempotent-re-enable-deletes-the-old-Flow-first behavior. Mocks whatsapp_flow_client
entirely (no live Meta calls) -- the client's own request shapes are covered by
test_whatsapp_flow_client.py, and the real end-to-end provisioning was already proven
against Meta's live API during the manual spike (see the approved plan).
"""

from app.core.security import decrypt_secret, encrypt_secret
from app.services import whatsapp_flow_client
from app.tests.test_whatsapp_templates import _make_restaurant, _register_and_login


async def _ok(*a, **k):
    return {"success": True}


async def _ok_no_validation_errors(*a, **k):
    return {"success": True, "validation_errors": []}


async def test_owner_can_enable_flow_ordering(client, db_session, monkeypatch):
    restaurant = await _make_restaurant(db_session, "flow-enable")
    headers = await _register_and_login(client, restaurant.id)

    async def fake_create_flow(*a, **k):
        return "meta-flow-id-123"

    monkeypatch.setattr(whatsapp_flow_client, "register_public_key", _ok)
    monkeypatch.setattr(whatsapp_flow_client, "create_flow", fake_create_flow)
    monkeypatch.setattr(whatsapp_flow_client, "upload_flow_json", _ok_no_validation_errors)
    monkeypatch.setattr(whatsapp_flow_client, "publish_flow", _ok)

    resp = await client.post(f"/api/v1/restaurants/{restaurant.id}/whatsapp-flow/enable", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["flow_id"] == "meta-flow-id-123"

    await db_session.refresh(restaurant)
    assert restaurant.whatsapp_flow_order_id == "meta-flow-id-123"
    assert restaurant.whatsapp_flow_private_key_encrypted
    assert "BEGIN PRIVATE KEY" in decrypt_secret(restaurant.whatsapp_flow_private_key_encrypted)


async def test_enable_failure_surfaces_502_and_leaves_restaurant_unchanged(client, db_session, monkeypatch):
    restaurant = await _make_restaurant(db_session, "flow-enable-fail")
    headers = await _register_and_login(client, restaurant.id)

    async def fake_create_flow(*a, **k):
        return "meta-flow-id-456"

    async def _blocked_by_integrity(*a, **k):
        raise Exception("Blocked by Integrity")

    monkeypatch.setattr(whatsapp_flow_client, "register_public_key", _ok)
    monkeypatch.setattr(whatsapp_flow_client, "create_flow", fake_create_flow)
    monkeypatch.setattr(whatsapp_flow_client, "upload_flow_json", _ok_no_validation_errors)
    monkeypatch.setattr(whatsapp_flow_client, "publish_flow", _blocked_by_integrity)

    resp = await client.post(f"/api/v1/restaurants/{restaurant.id}/whatsapp-flow/enable", headers=headers)
    assert resp.status_code == 502
    assert "Blocked by Integrity" in resp.json()["detail"]

    await db_session.refresh(restaurant)
    assert restaurant.whatsapp_flow_order_id is None
    assert restaurant.whatsapp_flow_private_key_encrypted is None


async def test_disable_clears_columns(client, db_session, monkeypatch):
    restaurant = await _make_restaurant(db_session, "flow-disable")
    restaurant.whatsapp_flow_order_id = "meta-flow-id-789"
    restaurant.whatsapp_flow_private_key_encrypted = encrypt_secret("fake-private-key")
    await db_session.commit()
    headers = await _register_and_login(client, restaurant.id)

    monkeypatch.setattr(whatsapp_flow_client, "delete_flow", _ok)

    resp = await client.post(f"/api/v1/restaurants/{restaurant.id}/whatsapp-flow/disable", headers=headers)
    assert resp.status_code == 200

    await db_session.refresh(restaurant)
    assert restaurant.whatsapp_flow_order_id is None
    assert restaurant.whatsapp_flow_private_key_encrypted is None


async def test_disable_succeeds_even_when_remote_delete_fails(client, db_session, monkeypatch):
    """Instant, safe local opt-out matters more than a clean remote teardown -- see the
    approved plan's rollback strategy."""
    restaurant = await _make_restaurant(db_session, "flow-disable-remote-fail")
    restaurant.whatsapp_flow_order_id = "meta-flow-id-999"
    restaurant.whatsapp_flow_private_key_encrypted = encrypt_secret("fake-private-key")
    await db_session.commit()
    headers = await _register_and_login(client, restaurant.id)

    async def _fails(*a, **k):
        raise Exception("network error")

    monkeypatch.setattr(whatsapp_flow_client, "delete_flow", _fails)

    resp = await client.post(f"/api/v1/restaurants/{restaurant.id}/whatsapp-flow/disable", headers=headers)
    assert resp.status_code == 200

    await db_session.refresh(restaurant)
    assert restaurant.whatsapp_flow_order_id is None


async def test_re_enable_deletes_the_previous_flow_first(client, db_session, monkeypatch):
    restaurant = await _make_restaurant(db_session, "flow-reenable")
    restaurant.whatsapp_flow_order_id = "old-flow-id"
    restaurant.whatsapp_flow_private_key_encrypted = encrypt_secret("old-private-key")
    await db_session.commit()
    headers = await _register_and_login(client, restaurant.id)

    deleted_ids = []

    async def fake_delete_flow(r, flow_id):
        deleted_ids.append(flow_id)
        return {"success": True}

    async def fake_create_flow(*a, **k):
        return "new-flow-id"

    monkeypatch.setattr(whatsapp_flow_client, "delete_flow", fake_delete_flow)
    monkeypatch.setattr(whatsapp_flow_client, "register_public_key", _ok)
    monkeypatch.setattr(whatsapp_flow_client, "create_flow", fake_create_flow)
    monkeypatch.setattr(whatsapp_flow_client, "upload_flow_json", _ok_no_validation_errors)
    monkeypatch.setattr(whatsapp_flow_client, "publish_flow", _ok)

    resp = await client.post(f"/api/v1/restaurants/{restaurant.id}/whatsapp-flow/enable", headers=headers)
    assert resp.status_code == 200
    assert deleted_ids == ["old-flow-id"]

    await db_session.refresh(restaurant)
    assert restaurant.whatsapp_flow_order_id == "new-flow-id"


async def test_cashier_cannot_enable_flow_ordering(client, db_session):
    restaurant = await _make_restaurant(db_session, "flow-cashier")
    headers = await _register_and_login(client, restaurant.id, role="cashier", email="cashier-flow@template-test.dev")

    resp = await client.post(f"/api/v1/restaurants/{restaurant.id}/whatsapp-flow/enable", headers=headers)
    assert resp.status_code == 403
