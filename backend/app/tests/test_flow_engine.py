import hashlib
import hmac
import itertools
import json

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models.branch import Branch
from app.models.category import Category
from app.models.enums import BranchStatus
from app.models.order import Order
from app.models.product import Product
from app.models.restaurant import Restaurant

PHONE_NUMBER_ID = "TEST_PHONE_NUMBER_ID"
CUSTOMER_PHONE = "919999999999"


def _sign(body: bytes) -> str:
    digest = hmac.new(settings.WHATSAPP_APP_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


async def _post_webhook(client, value: dict):
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{"id": "1", "changes": [{"value": value, "field": "messages"}]}],
    }
    body = json.dumps(payload).encode()
    response = await client.post(
        "/api/v1/webhook", content=body, headers={"X-Hub-Signature-256": _sign(body), "Content-Type": "application/json"}
    )
    assert response.status_code == 200
    return response


_wa_message_id_counter = itertools.count(1)


def _message_value(message: dict) -> dict:
    # Each call gets its own wa_message_id -- process_inbound_message treats a repeated id
    # as an already-processed duplicate (that's the point, see flow_engine.py), so a fixed
    # literal here would make every message past the first in a multi-step test silently
    # no-op instead of advancing the conversation.
    wa_message_id = f"wamid.test.{next(_wa_message_id_counter)}"
    return {
        "messaging_product": "whatsapp",
        "metadata": {"phone_number_id": PHONE_NUMBER_ID},
        "contacts": [{"wa_id": CUSTOMER_PHONE}],
        "messages": [{"from": CUSTOMER_PHONE, "id": wa_message_id, **message}],
    }


def _text(body: str) -> dict:
    return {"type": "text", "text": {"body": body}}


def _list_reply(id_: str) -> dict:
    return {"type": "interactive", "interactive": {"type": "list_reply", "list_reply": {"id": id_, "title": id_}}}


def _button_reply(id_: str) -> dict:
    return {"type": "interactive", "interactive": {"type": "button_reply", "button_reply": {"id": id_, "title": id_}}}


def _location(latitude: float, longitude: float, name: str | None = None) -> dict:
    loc: dict = {"latitude": latitude, "longitude": longitude}
    if name:
        loc["name"] = name
    return {"type": "location", "location": loc}


@pytest.fixture(autouse=True)
def _use_in_memory_sender(monkeypatch):
    from app.services.whatsapp_client import InMemoryWhatsAppSender

    fake_sender = InMemoryWhatsAppSender()
    monkeypatch.setattr("app.api.v1.routers.webhook._sender", fake_sender)
    return fake_sender


@pytest.fixture
async def demo_tenant(db_session):
    restaurant = Restaurant(
        name="Test Diner",
        slug="test-diner",
        delivery_charge=20,
        whatsapp_phone_number_id=PHONE_NUMBER_ID,
    )
    db_session.add(restaurant)
    await db_session.flush()

    branch = Branch(restaurant_id=restaurant.id, name="Main", status=BranchStatus.OPEN)
    category = Category(restaurant_id=restaurant.id, name="Mains", display_order=1)
    db_session.add_all([branch, category])
    await db_session.flush()

    product = Product(
        restaurant_id=restaurant.id,
        category_id=category.id,
        name="Veg Burger",
        price=150,
        gst_percent=5,
    )
    db_session.add(product)
    await db_session.commit()

    return {"restaurant": restaurant, "branch": branch, "category": category, "product": product}


async def test_full_order_flow_creates_order(client, db_session, demo_tenant):
    category = demo_tenant["category"]
    product = demo_tenant["product"]

    await _post_webhook(client, _message_value(_text("hi")))
    await _post_webhook(client, _message_value(_button_reply("button:order_food")))
    await _post_webhook(client, _message_value(_list_reply(f"category:{category.id}")))
    await _post_webhook(client, _message_value(_list_reply(f"product:{product.id}")))
    await _post_webhook(client, _message_value(_text("2")))
    await _post_webhook(client, _message_value(_button_reply("cart:checkout")))
    await _post_webhook(client, _message_value(_button_reply("fulfillment:delivery")))
    await _post_webhook(client, _message_value(_text("skip")))  # no coupon
    await _post_webhook(client, _message_value(_text("123 Test Street")))
    await _post_webhook(client, _message_value(_button_reply("order:confirm")))

    result = await db_session.execute(select(Order))
    orders = list(result.scalars().all())
    assert len(orders) == 1

    order = orders[0]
    assert order.subtotal == 300  # 150 * 2
    assert order.tax == 15  # 5% of 300
    assert order.delivery_charge == 20
    assert order.total == 335


async def test_invalid_webhook_signature_rejected(client, demo_tenant):
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{"id": "1", "changes": [{"value": _message_value(_text("hi")), "field": "messages"}]}],
    }
    body = json.dumps(payload).encode()
    response = await client.post(
        "/api/v1/webhook", content=body, headers={"X-Hub-Signature-256": "sha256=deadbeef", "Content-Type": "application/json"}
    )
    assert response.status_code == 401


async def test_webhook_verification_handshake(client):
    response = await client.get(
        "/api/v1/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": settings.WHATSAPP_WEBHOOK_VERIFY_TOKEN,
            "hub.challenge": "12345",
        },
    )
    assert response.status_code == 200
    assert response.text == "12345"
