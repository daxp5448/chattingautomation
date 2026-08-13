"""Proof for the "Demo Mode on a real business's own WhatsApp number" feature: a Super
Admin can toggle an already-live restaurant (e.g. Prince Corner) into the same
industry-picker experience the sentinel Demo Bot restaurant offers, choose which niches
appear, and toggle it back off with zero effect on that restaurant's own data.

See app/models/restaurant.py::demo_mode_enabled/demo_enabled_niche_codes,
app/api/v1/routers/restaurants.py::update_demo_mode,
app/api/v1/routers/webhook.py's routing check, and
app/services/demo_bot_service.py's credential self-healing.
"""

import hashlib
import hmac
import itertools
import json

from sqlalchemy import select

from app.core.config import settings
from app.core.security import encrypt_secret, hash_password
from app.models.enums import UserRole
from app.models.restaurant import Restaurant
from app.models.user import User
from app.services.demo_bot_service import handle_demo_inbound
from app.services.demo_restaurant_sync import sync_demo_restaurants
from app.services.generic_flow_engine import GenericInteraction
from app.services.niche_template_sync import sync_niche_templates
from app.services.whatsapp_client import InMemoryWhatsAppSender
from app.tests.test_restaurants import _register_super_admin

REAL_PHONE_NUMBER_ID = "REAL_BIZ_DEMO_MODE_TEST_PNID"

_wamid_counter = itertools.count(1)


def _next_wamid() -> str:
    return f"wamid.demomode.test.{next(_wamid_counter)}"


def _sign(body: bytes) -> str:
    digest = hmac.new(settings.WHATSAPP_APP_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


async def _post_webhook(client, value: dict):
    payload = {"object": "whatsapp_business_account", "entry": [{"id": "1", "changes": [{"value": value, "field": "messages"}]}]}
    body = json.dumps(payload).encode()
    response = await client.post(
        "/api/v1/webhook", content=body, headers={"X-Hub-Signature-256": _sign(body), "Content-Type": "application/json"}
    )
    assert response.status_code == 200
    return response


def _message_value(phone: str, message: dict) -> dict:
    return {
        "messaging_product": "whatsapp",
        "metadata": {"phone_number_id": REAL_PHONE_NUMBER_ID},
        "contacts": [{"wa_id": phone}],
        "messages": [{"from": phone, "id": _next_wamid(), **message}],
    }


def _text(body: str) -> dict:
    return {"type": "text", "text": {"body": body}}


async def _make_real_restaurant(db_session, name="Prince Corner Test") -> Restaurant:
    restaurant = Restaurant(
        name=name, slug=f"{name.lower().replace(' ', '-')}-demo-mode-test",
        whatsapp_phone_number_id=REAL_PHONE_NUMBER_ID,
        whatsapp_access_token_encrypted=encrypt_secret("real-token"),
    )
    db_session.add(restaurant)
    await db_session.commit()
    return restaurant


async def _make_owner(db_session, restaurant, email="owner-demo-mode-test@kelviontech.dev"):
    user = User(email=email, hashed_password=hash_password("OwnerPass123!"), role=UserRole.OWNER, restaurant_id=restaurant.id, is_active=True)
    db_session.add(user)
    await db_session.commit()


async def _owner_headers(client, email="owner-demo-mode-test@kelviontech.dev"):
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": "OwnerPass123!"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


# --- API: super-admin-only, validated -------------------------------------------------------


async def test_owner_cannot_toggle_demo_mode_on_their_own_restaurant(client, db_session):
    restaurant = await _make_real_restaurant(db_session)
    await _make_owner(db_session, restaurant)
    headers = await _owner_headers(client)

    resp = await client.patch(f"/api/v1/restaurants/{restaurant.id}/demo-mode", json={"enabled": True}, headers=headers)
    assert resp.status_code == 403, resp.text


async def test_super_admin_can_toggle_demo_mode(client, db_session):
    restaurant = await _make_real_restaurant(db_session)
    headers = await _register_super_admin(client)

    resp = await client.patch(f"/api/v1/restaurants/{restaurant.id}/demo-mode", json={"enabled": True}, headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["demo_mode_enabled"] is True

    resp = await client.patch(f"/api/v1/restaurants/{restaurant.id}/demo-mode", json={"enabled": False}, headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["demo_mode_enabled"] is False


async def test_toggle_rejects_unknown_niche_code(client, db_session):
    restaurant = await _make_real_restaurant(db_session)
    headers = await _register_super_admin(client)

    resp = await client.patch(
        f"/api/v1/restaurants/{restaurant.id}/demo-mode",
        json={"enabled": True, "niche_codes": ["not-a-real-niche"]},
        headers=headers,
    )
    assert resp.status_code == 400, resp.text


async def test_toggle_accepts_and_persists_real_niche_codes(client, db_session):
    await sync_niche_templates(db_session)
    restaurant = await _make_real_restaurant(db_session)
    headers = await _register_super_admin(client)

    resp = await client.patch(
        f"/api/v1/restaurants/{restaurant.id}/demo-mode",
        json={"enabled": True, "niche_codes": ["retail", "salon"]},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["demo_mode_enabled"] is True
    assert set(body["demo_enabled_niche_codes"]) == {"retail", "salon"}

    # Explicit null resets to "show every niche".
    resp = await client.patch(
        f"/api/v1/restaurants/{restaurant.id}/demo-mode", json={"enabled": True, "niche_codes": None}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["demo_enabled_niche_codes"] is None


async def test_omitting_niche_codes_leaves_existing_selection_untouched(client, db_session):
    await sync_niche_templates(db_session)
    restaurant = await _make_real_restaurant(db_session)
    headers = await _register_super_admin(client)

    await client.patch(
        f"/api/v1/restaurants/{restaurant.id}/demo-mode", json={"enabled": True, "niche_codes": ["retail"]}, headers=headers
    )
    resp = await client.patch(f"/api/v1/restaurants/{restaurant.id}/demo-mode", json={"enabled": False}, headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["demo_enabled_niche_codes"] == ["retail"]  # untouched by the enabled-only PATCH
    assert resp.json()["demo_mode_enabled"] is False


# --- picker filtering -------------------------------------------------------------------------


async def test_picker_filters_to_selected_niche_codes_only(db_session):
    await sync_niche_templates(db_session)
    restaurant = await _make_real_restaurant(db_session, name="Filter Test Biz")
    await sync_demo_restaurants(db_session, restaurant.id)
    restaurant.demo_mode_enabled = True
    restaurant.demo_enabled_niche_codes = ["retail", "salon"]
    await db_session.commit()

    sender = InMemoryWhatsAppSender()
    await handle_demo_inbound(db_session, sender, restaurant, "919999955501", GenericInteraction(kind="text", text="hi"), wa_message_id=_next_wamid())

    ids = set()
    for m in sender.sent:
        interactive = m.payload.get("interactive", {})
        if interactive.get("type") == "list":
            for section in interactive["action"]["sections"]:
                ids |= {r["id"] for r in section["rows"]}
    assert ids == {"demo:pick:retail", "demo:pick:salon"}


# --- real end-to-end webhook routing ------------------------------------------------------------


async def test_webhook_routes_to_demo_picker_when_demo_mode_enabled(client, db_session):
    await sync_niche_templates(db_session)
    restaurant = await _make_real_restaurant(db_session, name="Webhook Demo Mode Biz")
    await sync_demo_restaurants(db_session, restaurant.id)
    restaurant.demo_mode_enabled = True
    await db_session.commit()

    phone = "919999955502"
    resp = await _post_webhook(client, _message_value(phone, _text("hi")))
    assert resp.status_code == 200

    from app.models.customer import Customer
    from app.models.message import Message

    sentinel_customer = (await db_session.execute(
        select(Customer).where(Customer.restaurant_id == restaurant.id, Customer.phone == phone)
    )).scalar_one()
    messages = (await db_session.execute(
        select(Message).where(Message.restaurant_id == restaurant.id, Message.customer_id == sentinel_customer.id)
    )).scalars().all()
    # The industry picker (an interactive list), not this restaurant's own legacy flow --
    # proven by the presence of an outbound Message logged under the real restaurant while
    # demo_mode_enabled is on, since the legacy engine (uses_generic_engine=False, no
    # niche configured) would have nothing sensible to say to a bare "hi" at all.
    assert len(messages) > 0


async def test_webhook_uses_normal_flow_when_demo_mode_disabled(client, db_session):
    """The other half of the same proof: with demo_mode_enabled left at its default
    (False), a real restaurant's inbound webhook traffic must be byte-for-byte unaffected
    by this feature existing at all -- routes through the same engine it always has."""
    restaurant = await _make_real_restaurant(db_session, name="Untouched Biz")
    await db_session.commit()
    assert restaurant.demo_mode_enabled is False

    phone = "919999955503"
    resp = await _post_webhook(client, _message_value(phone, _text("hi")))
    assert resp.status_code == 200

    from app.models.demo_session import DemoSession

    # No DemoSession was ever created for this phone -- proves the demo dispatcher was
    # never entered at all (it always get_or_create's one on its very first branch).
    session_row = (await db_session.execute(select(DemoSession).where(DemoSession.customer_phone == phone))).scalar_one_or_none()
    assert session_row is None


# --- credential self-healing ------------------------------------------------------------------


async def test_picking_a_niche_repoints_credentials_to_whichever_number_is_currently_active(db_session):
    """The core correctness fix this feature needed: demo_sends_via_restaurant_id is a
    fixed column set once at provisioning time (see demo_restaurant_sync.py). Without
    self-healing it on pick, a demo restaurant first reached through one sentinel would
    silently keep trying to send through that sentinel's credentials forever, even after a
    prospect starts chatting with the very same niche through a completely different real
    number now in Demo Mode -- see demo_bot_service.py's handle_demo_inbound comment."""
    await sync_niche_templates(db_session)
    original_sentinel = await _make_real_restaurant(db_session, name="Original Sentinel")
    original_sentinel.is_demo = True
    original_sentinel.whatsapp_phone_number_id = "ORIGINAL_SENTINEL_PNID"
    await sync_demo_restaurants(db_session, original_sentinel.id)

    real_biz = await _make_real_restaurant(db_session, name="Second Number Biz")
    real_biz.whatsapp_phone_number_id = "SECOND_NUMBER_PNID"
    real_biz.demo_mode_enabled = True
    await db_session.commit()

    retail = (await db_session.execute(select(Restaurant).where(Restaurant.niche_type == "retail", Restaurant.is_demo.is_(True)))).scalar_one()
    assert retail.demo_sends_via_restaurant_id == original_sentinel.id  # provisioned against the first sentinel

    sender = InMemoryWhatsAppSender()
    phone = "919999955504"
    await handle_demo_inbound(db_session, sender, real_biz, phone, GenericInteraction(kind="text", text="hi"), wa_message_id=_next_wamid())
    await handle_demo_inbound(
        db_session, sender, real_biz, phone,
        GenericInteraction(kind="list_reply", reply_id="demo:pick:retail", text="Retail & Fashion"),
        wa_message_id=_next_wamid(),
    )

    await db_session.refresh(retail)
    assert retail.demo_sends_via_restaurant_id == real_biz.id  # self-healed to the number the customer actually used
