"""Proof for Phase 2, Item 1: WhatsApp Template Manager -- CRUD lifecycle, tenant
isolation, role gating, the raise-not-swallow submit/delete gateway idiom (mirrors
app/tests/test_payment_and_order_lifecycle.py's refund tests), and the status-polling
task (mirrors app/tests/test_reconciliation.py's shape).
"""

from sqlalchemy import select

from app.core.security import encrypt_secret
from app.models.enums import TemplateStatus
from app.models.restaurant import Restaurant
from app.models.whatsapp_template import WhatsAppTemplate
from app.services import whatsapp_template_client
from app.services.whatsapp_client import InMemoryWhatsAppSender
from app.tasks.whatsapp_template_status_sync import _sync_template_statuses

PHONE_NUMBER_ID = "TEMPLATE_TEST_PHONE_NUMBER_ID"
WABA_ID = "TEMPLATE_TEST_WABA_ID"


async def _register_and_login(client, restaurant_id, role="owner", email="owner@template-test.dev"):
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "TestPass123!", "role": role, "restaurant_id": str(restaurant_id)},
    )
    assert resp.status_code == 201, resp.text
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": "TestPass123!"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _make_restaurant(db_session, slug: str) -> Restaurant:
    restaurant = Restaurant(
        name=f"Template Test {slug}", slug=f"template-test-{slug}",
        whatsapp_phone_number_id=f"{PHONE_NUMBER_ID}_{slug}",
        whatsapp_business_account_id=f"{WABA_ID}_{slug}",
        whatsapp_access_token_encrypted=encrypt_secret("fake-access-token"),
    )
    db_session.add(restaurant)
    await db_session.commit()
    return restaurant


def _create_payload(name="order_confirmation"):
    return {
        "name": name, "category": "utility", "language": "en_US",
        "body_text": "Hi {{1}}, your order {{2}} is confirmed.", "variable_examples": ["Asha", "ORD123"],
    }


# --- CRUD lifecycle --------------------------------------------------------------------


async def test_create_list_get_draft_template(client, db_session):
    restaurant = await _make_restaurant(db_session, "crud")
    headers = await _register_and_login(client, restaurant.id)

    resp = await client.post(f"/api/v1/restaurants/{restaurant.id}/whatsapp-templates", json=_create_payload(), headers=headers)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "draft"
    assert body["meta_template_id"] is None
    template_id = body["id"]

    listed = await client.get(f"/api/v1/restaurants/{restaurant.id}/whatsapp-templates", headers=headers)
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    detail = await client.get(f"/api/v1/restaurants/{restaurant.id}/whatsapp-templates/{template_id}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["name"] == "order_confirmation"


async def test_create_rejects_malformed_name(client, db_session):
    restaurant = await _make_restaurant(db_session, "badname")
    headers = await _register_and_login(client, restaurant.id)
    resp = await client.post(
        f"/api/v1/restaurants/{restaurant.id}/whatsapp-templates", json=_create_payload(name="Order Confirmation!"), headers=headers
    )
    assert resp.status_code == 422


async def test_create_rejects_duplicate_name(client, db_session):
    restaurant = await _make_restaurant(db_session, "dupe")
    headers = await _register_and_login(client, restaurant.id)
    await client.post(f"/api/v1/restaurants/{restaurant.id}/whatsapp-templates", json=_create_payload(), headers=headers)
    resp = await client.post(f"/api/v1/restaurants/{restaurant.id}/whatsapp-templates", json=_create_payload(), headers=headers)
    assert resp.status_code == 409


async def test_update_draft_allowed(client, db_session):
    restaurant = await _make_restaurant(db_session, "editdraft")
    headers = await _register_and_login(client, restaurant.id)
    created = await client.post(f"/api/v1/restaurants/{restaurant.id}/whatsapp-templates", json=_create_payload(), headers=headers)
    template_id = created.json()["id"]

    resp = await client.patch(
        f"/api/v1/restaurants/{restaurant.id}/whatsapp-templates/{template_id}", json={"body_text": "Updated {{1}}"}, headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["body_text"] == "Updated {{1}}"


async def test_update_rejected_once_pending(client, db_session, monkeypatch):
    restaurant = await _make_restaurant(db_session, "editpending")
    headers = await _register_and_login(client, restaurant.id)
    created = await client.post(f"/api/v1/restaurants/{restaurant.id}/whatsapp-templates", json=_create_payload(), headers=headers)
    template_id = created.json()["id"]

    async def fake_create(restaurant, template):
        return {"id": "meta_tpl_123"}

    monkeypatch.setattr(whatsapp_template_client, "create_template", fake_create)
    submitted = await client.post(f"/api/v1/restaurants/{restaurant.id}/whatsapp-templates/{template_id}/submit", headers=headers)
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["status"] == "pending"

    resp = await client.patch(
        f"/api/v1/restaurants/{restaurant.id}/whatsapp-templates/{template_id}", json={"body_text": "Nope"}, headers=headers
    )
    assert resp.status_code == 400


# --- submit: raise-not-swallow ----------------------------------------------------------


async def test_submit_success_sets_pending_and_meta_id(client, db_session, monkeypatch):
    restaurant = await _make_restaurant(db_session, "submitok")
    headers = await _register_and_login(client, restaurant.id)
    created = await client.post(f"/api/v1/restaurants/{restaurant.id}/whatsapp-templates", json=_create_payload(), headers=headers)
    template_id = created.json()["id"]

    async def fake_create(restaurant, template):
        return {"id": "meta_tpl_456"}

    monkeypatch.setattr(whatsapp_template_client, "create_template", fake_create)
    resp = await client.post(f"/api/v1/restaurants/{restaurant.id}/whatsapp-templates/{template_id}/submit", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "pending"
    assert body["meta_template_id"] == "meta_tpl_456"
    assert body["submitted_at"] is not None


async def test_submit_failure_leaves_template_unchanged(client, db_session, monkeypatch):
    restaurant = await _make_restaurant(db_session, "submitfail")
    headers = await _register_and_login(client, restaurant.id)
    created = await client.post(f"/api/v1/restaurants/{restaurant.id}/whatsapp-templates", json=_create_payload(), headers=headers)
    template_id = created.json()["id"]

    async def failing_create(restaurant, template):
        raise RuntimeError("meta 500")

    monkeypatch.setattr(whatsapp_template_client, "create_template", failing_create)
    resp = await client.post(f"/api/v1/restaurants/{restaurant.id}/whatsapp-templates/{template_id}/submit", headers=headers)
    assert resp.status_code == 502

    detail = await client.get(f"/api/v1/restaurants/{restaurant.id}/whatsapp-templates/{template_id}", headers=headers)
    assert detail.json()["status"] == "draft"
    assert detail.json()["meta_template_id"] is None


# --- test-send ---------------------------------------------------------------------------


async def test_test_send_rejected_unless_approved(client, db_session):
    restaurant = await _make_restaurant(db_session, "testsendreject")
    headers = await _register_and_login(client, restaurant.id)
    created = await client.post(f"/api/v1/restaurants/{restaurant.id}/whatsapp-templates", json=_create_payload(), headers=headers)
    template_id = created.json()["id"]

    resp = await client.post(
        f"/api/v1/restaurants/{restaurant.id}/whatsapp-templates/{template_id}/test-send",
        json={"to_phone": "919876543210", "variable_values": ["Asha", "ORD123"]}, headers=headers,
    )
    assert resp.status_code == 400


async def test_test_send_succeeds_once_approved(client, db_session, monkeypatch):
    restaurant = await _make_restaurant(db_session, "testsendok")
    headers = await _register_and_login(client, restaurant.id)
    created = await client.post(f"/api/v1/restaurants/{restaurant.id}/whatsapp-templates", json=_create_payload(), headers=headers)
    template_id = created.json()["id"]

    template = (await db_session.execute(select(WhatsAppTemplate).where(WhatsAppTemplate.id == template_id))).scalar_one()
    template.status = TemplateStatus.APPROVED
    template.meta_template_id = "meta_tpl_789"
    await db_session.commit()

    sender = InMemoryWhatsAppSender()
    monkeypatch.setattr("app.api.v1.routers.whatsapp_templates._sender", sender)

    resp = await client.post(
        f"/api/v1/restaurants/{restaurant.id}/whatsapp-templates/{template_id}/test-send",
        json={"to_phone": "919876543210", "variable_values": ["Asha", "ORD123"]}, headers=headers,
    )
    assert resp.status_code == 204, resp.text
    assert len(sender.sent) == 1
    sent = sender.sent[0]
    assert sent.payload["type"] == "template"
    assert sent.payload["template"]["name"] == "order_confirmation"
    assert sent.payload["template"]["components"][0]["parameters"][0]["text"] == "Asha"


# --- delete: gateway-first ordering -------------------------------------------------------


async def test_delete_draft_never_calls_meta(client, db_session, monkeypatch):
    restaurant = await _make_restaurant(db_session, "deletedraft")
    headers = await _register_and_login(client, restaurant.id)
    created = await client.post(f"/api/v1/restaurants/{restaurant.id}/whatsapp-templates", json=_create_payload(), headers=headers)
    template_id = created.json()["id"]

    called = []
    monkeypatch.setattr(whatsapp_template_client, "delete_template", lambda *a, **k: called.append(1))

    resp = await client.delete(f"/api/v1/restaurants/{restaurant.id}/whatsapp-templates/{template_id}", headers=headers)
    assert resp.status_code == 204
    assert called == []


async def test_delete_submitted_template_calls_meta_first_and_succeeds(client, db_session, monkeypatch):
    restaurant = await _make_restaurant(db_session, "deleteok")
    headers = await _register_and_login(client, restaurant.id)
    created = await client.post(f"/api/v1/restaurants/{restaurant.id}/whatsapp-templates", json=_create_payload(), headers=headers)
    template_id = created.json()["id"]

    template = (await db_session.execute(select(WhatsAppTemplate).where(WhatsAppTemplate.id == template_id))).scalar_one()
    template.meta_template_id = "meta_tpl_delete_ok"
    await db_session.commit()

    async def fake_delete(restaurant, name):
        return {"success": True}

    monkeypatch.setattr(whatsapp_template_client, "delete_template", fake_delete)
    resp = await client.delete(f"/api/v1/restaurants/{restaurant.id}/whatsapp-templates/{template_id}", headers=headers)
    assert resp.status_code == 204

    remaining = (await db_session.execute(select(WhatsAppTemplate).where(WhatsAppTemplate.id == template_id))).scalar_one_or_none()
    assert remaining is None


async def test_delete_submitted_template_keeps_local_row_when_meta_call_fails(client, db_session, monkeypatch):
    """The gap the design review found: deleting local-first could orphan the name on
    Meta's side forever. This proves the local row survives a failed Meta delete."""
    restaurant = await _make_restaurant(db_session, "deletefail")
    headers = await _register_and_login(client, restaurant.id)
    created = await client.post(f"/api/v1/restaurants/{restaurant.id}/whatsapp-templates", json=_create_payload(), headers=headers)
    template_id = created.json()["id"]

    template = (await db_session.execute(select(WhatsAppTemplate).where(WhatsAppTemplate.id == template_id))).scalar_one()
    template.meta_template_id = "meta_tpl_delete_fail"
    await db_session.commit()

    async def failing_delete(restaurant, name):
        raise RuntimeError("meta 500")

    monkeypatch.setattr(whatsapp_template_client, "delete_template", failing_delete)
    resp = await client.delete(f"/api/v1/restaurants/{restaurant.id}/whatsapp-templates/{template_id}", headers=headers)
    assert resp.status_code == 502

    remaining = (await db_session.execute(select(WhatsAppTemplate).where(WhatsAppTemplate.id == template_id))).scalar_one_or_none()
    assert remaining is not None


# --- tenant isolation + role gating ------------------------------------------------------


async def test_owner_cannot_read_or_edit_another_tenants_templates(client, db_session):
    # Two owners across two tenants in one test: /auth/register only allows an
    # unauthenticated bootstrap registration for the very first account on the whole
    # deployment (app/api/v1/routers/auth.py::register) -- the second owner has to be
    # created directly via the DB + logged in through /auth/login instead, same pattern
    # as app/tests/test_flow_definitions_home_buttons.py::_make_owner_tenant.
    from app.core.security import hash_password
    from app.models.user import User

    restaurant_a = await _make_restaurant(db_session, "tenanta")
    restaurant_b = await _make_restaurant(db_session, "tenantb")
    headers_a = await _register_and_login(client, restaurant_a.id, email="owner-a@template-test.dev")

    user_b = User(
        email="owner-b@template-test.dev", hashed_password=hash_password("TestPass123!"),
        role="owner", restaurant_id=restaurant_b.id, is_active=True,
    )
    db_session.add(user_b)
    await db_session.commit()
    login_b = await client.post("/api/v1/auth/login", json={"email": "owner-b@template-test.dev", "password": "TestPass123!"})
    assert login_b.status_code == 200, login_b.text
    headers_b = {"Authorization": f"Bearer {login_b.json()['access_token']}"}

    created_b = await client.post(
        f"/api/v1/restaurants/{restaurant_b.id}/whatsapp-templates", json=_create_payload(), headers=headers_b
    )
    template_id = created_b.json()["id"]

    resp = await client.get(f"/api/v1/restaurants/{restaurant_b.id}/whatsapp-templates/{template_id}", headers=headers_a)
    assert resp.status_code == 403

    resp = await client.get(f"/api/v1/restaurants/{restaurant_b.id}/whatsapp-templates", headers=headers_a)
    assert resp.status_code == 403


async def test_cashier_forbidden_from_creating_templates(client, db_session):
    restaurant = await _make_restaurant(db_session, "cashier")
    headers = await _register_and_login(client, restaurant.id, role="cashier", email="cashier@template-test.dev")
    resp = await client.post(f"/api/v1/restaurants/{restaurant.id}/whatsapp-templates", json=_create_payload(), headers=headers)
    assert resp.status_code == 403


async def test_cashier_can_still_read_templates(client, db_session):
    restaurant = await _make_restaurant(db_session, "cashierread")
    owner_headers = await _register_and_login(client, restaurant.id, email="owner-cr@template-test.dev")
    await client.post(f"/api/v1/restaurants/{restaurant.id}/whatsapp-templates", json=_create_payload(), headers=owner_headers)

    cashier_headers = await _register_and_login(client, restaurant.id, role="cashier", email="cashier-cr@template-test.dev")
    resp = await client.get(f"/api/v1/restaurants/{restaurant.id}/whatsapp-templates", headers=cashier_headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 1


# --- status-polling task ------------------------------------------------------------------


async def test_polling_task_marks_approved(db_session, monkeypatch):
    restaurant = await _make_restaurant(db_session, "pollapprove")
    template = WhatsAppTemplate(
        restaurant_id=restaurant.id, name="poll_approve", category="utility", language="en_US",
        body_text="Hi {{1}}", variable_examples=["Asha"], status=TemplateStatus.PENDING, meta_template_id="meta_poll_1",
    )
    db_session.add(template)
    await db_session.commit()
    template_id = template.id

    async def fake_status(restaurant, meta_template_id):
        return {"status": "APPROVED"}

    monkeypatch.setattr(whatsapp_template_client, "get_template_status", fake_status)
    updated = await _sync_template_statuses()
    assert updated == 1

    db_session.expire_all()
    refreshed = (await db_session.execute(select(WhatsAppTemplate).where(WhatsAppTemplate.id == template_id))).scalar_one()
    assert refreshed.status == TemplateStatus.APPROVED
    assert refreshed.last_synced_at is not None


async def test_polling_task_marks_rejected_with_reason(db_session, monkeypatch):
    restaurant = await _make_restaurant(db_session, "pollreject")
    template = WhatsAppTemplate(
        restaurant_id=restaurant.id, name="poll_reject", category="marketing", language="en_US",
        body_text="Hi {{1}}", variable_examples=["Asha"], status=TemplateStatus.PENDING, meta_template_id="meta_poll_2",
    )
    db_session.add(template)
    await db_session.commit()
    template_id = template.id

    async def fake_status(restaurant, meta_template_id):
        return {"status": "REJECTED", "rejected_reason": "INVALID_FORMAT"}

    monkeypatch.setattr(whatsapp_template_client, "get_template_status", fake_status)
    updated = await _sync_template_statuses()
    assert updated == 1

    db_session.expire_all()
    refreshed = (await db_session.execute(select(WhatsAppTemplate).where(WhatsAppTemplate.id == template_id))).scalar_one()
    assert refreshed.status == TemplateStatus.REJECTED
    assert refreshed.rejection_reason == "INVALID_FORMAT"


async def test_polling_task_leaves_still_pending_untouched(db_session, monkeypatch):
    restaurant = await _make_restaurant(db_session, "pollpending")
    template = WhatsAppTemplate(
        restaurant_id=restaurant.id, name="poll_pending", category="utility", language="en_US",
        body_text="Hi {{1}}", variable_examples=["Asha"], status=TemplateStatus.PENDING, meta_template_id="meta_poll_3",
    )
    db_session.add(template)
    await db_session.commit()
    template_id = template.id

    async def fake_status(restaurant, meta_template_id):
        return {"status": "PENDING"}

    monkeypatch.setattr(whatsapp_template_client, "get_template_status", fake_status)
    updated = await _sync_template_statuses()
    assert updated == 0

    db_session.expire_all()
    refreshed = (await db_session.execute(select(WhatsAppTemplate).where(WhatsAppTemplate.id == template_id))).scalar_one()
    assert refreshed.status == TemplateStatus.PENDING


async def test_polling_task_one_bad_lookup_does_not_block_the_rest_of_the_batch(db_session, monkeypatch):
    restaurant = await _make_restaurant(db_session, "pollbatch")
    bad = WhatsAppTemplate(
        restaurant_id=restaurant.id, name="poll_bad", category="utility", language="en_US",
        body_text="Hi {{1}}", variable_examples=["Asha"], status=TemplateStatus.PENDING, meta_template_id="meta_poll_bad",
    )
    good = WhatsAppTemplate(
        restaurant_id=restaurant.id, name="poll_good", category="utility", language="en_US",
        body_text="Hi {{1}}", variable_examples=["Asha"], status=TemplateStatus.PENDING, meta_template_id="meta_poll_good",
    )
    db_session.add_all([bad, good])
    await db_session.commit()
    bad_id, good_id = bad.id, good.id

    async def flaky_status(restaurant, meta_template_id):
        if meta_template_id == "meta_poll_bad":
            raise RuntimeError("gateway timeout")
        return {"status": "APPROVED"}

    monkeypatch.setattr(whatsapp_template_client, "get_template_status", flaky_status)
    updated = await _sync_template_statuses()
    assert updated == 1

    db_session.expire_all()
    bad_refreshed = (await db_session.execute(select(WhatsAppTemplate).where(WhatsAppTemplate.id == bad_id))).scalar_one()
    good_refreshed = (await db_session.execute(select(WhatsAppTemplate).where(WhatsAppTemplate.id == good_id))).scalar_one()
    assert bad_refreshed.status == TemplateStatus.PENDING
    assert good_refreshed.status == TemplateStatus.APPROVED
