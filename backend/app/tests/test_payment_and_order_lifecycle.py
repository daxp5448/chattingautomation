"""Covers the payment-webhook hardening and order-lifecycle work in:
  - app/api/v1/routers/payments.py (row-locked webhook, full logging, failure events)
  - app/api/v1/routers/orders.py (refund endpoint, status transition guard,
    coupon/loyalty reversal on cancel, COD-completion payment accuracy, customer
    WhatsApp notifications, customer_name/customer_phone on OrderRead)
  - app/repositories/order_repository.py (dashboard_stats' new paid_revenue figure)
"""

import hashlib
import hmac
import json
import uuid

import pytest
from sqlalchemy import select

from app.core.security import encrypt_secret
from app.models.coupon import Coupon, CouponRedemption
from app.models.customer import Customer
from app.models.enums import CouponType, FulfillmentType, LoyaltyReason, OrderStatus, PaymentMethod, PaymentStatus
from app.models.loyalty import LoyaltyTransaction
from app.models.order import Order
from app.models.restaurant import Restaurant
from app.repositories.order_repository import OrderRepository
from app.services.payment.razorpay import RazorpayGateway
from app.services.whatsapp_client import InMemoryWhatsAppSender

WEBHOOK_SECRET = "whsec_test_secret"
CUSTOMER_PHONE = "919876500000"


@pytest.fixture(autouse=True)
def _fake_senders(monkeypatch):
    """Swap the real Graph API sender for an in-memory one on both routers under test, so
    assertions on "did we message the customer" don't depend on network access.
    """
    payments_sender = InMemoryWhatsAppSender()
    orders_sender = InMemoryWhatsAppSender()
    monkeypatch.setattr("app.api.v1.routers.payments._sender", payments_sender)
    monkeypatch.setattr("app.api.v1.routers.orders._sender", orders_sender)
    return {"payments": payments_sender, "orders": orders_sender}


@pytest.fixture
async def tenant(db_session):
    restaurant = Restaurant(
        name="Payment Test Diner",
        slug="payment-test-diner",
        whatsapp_phone_number_id="PAYMENT_TEST_PHONE",
        whatsapp_access_token_encrypted=encrypt_secret("fake-access-token"),
        razorpay_webhook_secret_encrypted=encrypt_secret(WEBHOOK_SECRET),
        razorpay_key_id="rzp_test_key",
        razorpay_key_secret_encrypted=encrypt_secret("rzp_test_secret"),
    )
    db_session.add(restaurant)
    await db_session.flush()

    customer = Customer(restaurant_id=restaurant.id, phone=CUSTOMER_PHONE, name="Jane Doe", loyalty_points=30)
    db_session.add(customer)
    await db_session.commit()

    return restaurant, customer


def _make_order(restaurant, customer, *, order_number, payment_status=PaymentStatus.PENDING, total=250, **kwargs):
    return Order(
        restaurant_id=restaurant.id,
        branch_id=restaurant.id,  # FK not enforced under SQLite here (matches test_reconciliation.py)
        customer_id=customer.id,
        order_number=order_number,
        total=total,
        payment_status=payment_status,
        **kwargs,
    )


async def _register_and_login(client, restaurant_id, role="owner", email="owner@payment-test.dev"):
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "TestPass123!", "role": role, "restaurant_id": str(restaurant_id)},
    )
    assert resp.status_code == 201, resp.text
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": "TestPass123!"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _razorpay_payload(event: str, order_id, payment_id: str = "pay_test123") -> bytes:
    payload = {
        "event": event,
        "payload": {
            "payment_link": {"entity": {"notes": {"order_id": str(order_id)}}},
            "payment": {"entity": {"id": payment_id, "notes": {}}},
        },
    }
    return json.dumps(payload).encode()


def _sign(body: bytes) -> str:
    return hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()


async def _post_webhook(client, body: bytes, signature: str | None = None):
    headers = {"Content-Type": "application/json"}
    if signature is not None:
        headers["X-Razorpay-Signature"] = signature
    return await client.post("/api/v1/payments/razorpay/webhook", content=body, headers=headers)


# --- webhook: row-lock / idempotency ------------------------------------------------------


async def test_webhook_redelivery_does_not_duplicate_payment_confirmation(client, db_session, tenant, _fake_senders):
    """Simulates the realistic Razorpay redelivery scenario: the same 'payment_link.paid'
    event arrives twice (e.g. Razorpay retried because it never saw our first 200). The
    order-fetch is now `.with_for_update()`-locked specifically so two such deliveries
    can't both pass the `payment_status != PAID` guard -- this drives that guard twice in a
    row and asserts the customer is only notified once and the order lands PAID exactly
    once, which is the outcome that lock protects. (SQLite's `.with_for_update()` is a
    no-op per app/repositories/coupon_repository.py, so this test verifies the resulting
    idempotent behavior rather than raw lock contention, which SQLite in this harness
    can't meaningfully simulate.)
    """
    restaurant, customer = tenant
    order = _make_order(restaurant, customer, order_number="RZP1", payment_method=PaymentMethod.RAZORPAY)
    db_session.add(order)
    await db_session.commit()
    order_id = order.id

    body = _razorpay_payload("payment_link.paid", order_id)
    signature = _sign(body)

    first = await _post_webhook(client, body, signature)
    assert first.status_code == 200
    second = await _post_webhook(client, body, signature)
    assert second.status_code == 200

    # populate_existing=True refreshes db_session's already-in-identity-map copy of this
    # row directly from this query's result, instead of expire_all() + a separate lazy
    # reload -- the latter can trigger a nested implicit query mid-row-processing that
    # SQLAlchemy's async/greenlet bridge doesn't support (MissingGreenlet), since the
    # order was actually written by a different session (the ASGI request's own).
    refreshed = (
        await db_session.execute(select(Order).where(Order.id == order_id).execution_options(populate_existing=True))
    ).scalar_one()
    assert refreshed.payment_status == PaymentStatus.PAID
    assert refreshed.gateway_metadata.get("payment_id") == "pay_test123"

    assert len(_fake_senders["payments"].sent) == 1


async def test_webhook_order_not_found_logged_and_ignored(client, tenant):
    body = _razorpay_payload("payment_link.paid", uuid.uuid4())
    resp = await _post_webhook(client, body, _sign(body))
    assert resp.status_code == 200
    assert resp.json() == {"status": "ignored"}


async def test_webhook_bad_signature_rejected(client, db_session, tenant):
    restaurant, customer = tenant
    order = _make_order(restaurant, customer, order_number="RZP2", payment_method=PaymentMethod.RAZORPAY)
    db_session.add(order)
    await db_session.commit()

    body = _razorpay_payload("payment_link.paid", order.id)
    resp = await _post_webhook(client, body, "deadbeef")
    assert resp.status_code == 401


# --- webhook: failure events ---------------------------------------------------------------


@pytest.mark.parametrize("event", ["payment_link.expired", "payment.failed"])
async def test_webhook_failure_events_mark_payment_failed(client, db_session, tenant, _fake_senders, event):
    restaurant, customer = tenant
    order = _make_order(restaurant, customer, order_number="RZP3", payment_method=PaymentMethod.RAZORPAY)
    db_session.add(order)
    await db_session.commit()
    order_id = order.id

    body = _razorpay_payload(event, order_id)
    resp = await _post_webhook(client, body, _sign(body))
    assert resp.status_code == 200

    # populate_existing=True refreshes db_session's already-in-identity-map copy of this
    # row directly from this query's result, instead of expire_all() + a separate lazy
    # reload -- the latter can trigger a nested implicit query mid-row-processing that
    # SQLAlchemy's async/greenlet bridge doesn't support (MissingGreenlet), since the
    # order was actually written by a different session (the ASGI request's own).
    refreshed = (
        await db_session.execute(select(Order).where(Order.id == order_id).execution_options(populate_existing=True))
    ).scalar_one()
    assert refreshed.payment_status == PaymentStatus.FAILED

    assert len(_fake_senders["payments"].sent) == 1
    sent_body = _fake_senders["payments"].sent[0].payload["text"]["body"]
    assert "didn't go through" in sent_body


async def test_webhook_unrecognized_event_ignored_without_crashing(client, db_session, tenant, _fake_senders):
    restaurant, customer = tenant
    order = _make_order(restaurant, customer, order_number="RZP4", payment_method=PaymentMethod.RAZORPAY)
    db_session.add(order)
    await db_session.commit()

    body = _razorpay_payload("payment_link.created", order.id)
    resp = await _post_webhook(client, body, _sign(body))
    assert resp.status_code == 200

    # See the populate_existing() comment earlier in this file for why this isn't
    # expire_all() + a plain re-query.
    refreshed = (
        await db_session.execute(select(Order).where(Order.id == order.id).execution_options(populate_existing=True))
    ).scalar_one()
    assert refreshed.payment_status == PaymentStatus.PENDING
    assert _fake_senders["payments"].sent == []


# --- refund endpoint -------------------------------------------------------------------------


async def test_refund_rejects_non_paid_order(client, db_session, tenant):
    restaurant, customer = tenant
    order = _make_order(
        restaurant, customer, order_number="REF1", payment_method=PaymentMethod.RAZORPAY, payment_status=PaymentStatus.PENDING
    )
    db_session.add(order)
    await db_session.commit()

    headers = await _register_and_login(client, restaurant.id)
    resp = await client.post(f"/api/v1/restaurants/{restaurant.id}/orders/{order.id}/refund", headers=headers)
    assert resp.status_code == 400
    assert "paid" in resp.json()["detail"].lower()


async def test_refund_succeeds_for_paid_razorpay_order(client, db_session, tenant, monkeypatch):
    restaurant, customer = tenant
    order = _make_order(
        restaurant,
        customer,
        order_number="REF2",
        payment_method=PaymentMethod.RAZORPAY,
        payment_status=PaymentStatus.PAID,
        gateway_metadata={"payment_link_id": "plink_1", "payment_id": "pay_1"},
    )
    db_session.add(order)
    await db_session.commit()

    async def fake_refund(self, payment_id, amount):
        assert payment_id == "pay_1"
        assert amount == 250
        return {"refund_id": "rfnd_1", "status": "processed"}

    monkeypatch.setattr(RazorpayGateway, "refund", fake_refund, raising=False)

    headers = await _register_and_login(client, restaurant.id)
    resp = await client.post(f"/api/v1/restaurants/{restaurant.id}/orders/{order.id}/refund", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["payment_status"] == "refunded"
    assert body["status"] == "refunded"

    # See the populate_existing() comment earlier in this file for why this isn't
    # expire_all() + a plain re-query.
    refreshed = (
        await db_session.execute(select(Order).where(Order.id == order.id).execution_options(populate_existing=True))
    ).scalar_one()
    assert refreshed.payment_status == PaymentStatus.REFUNDED


async def test_refund_fails_cleanly_when_gateway_call_fails(client, db_session, tenant, monkeypatch):
    restaurant, customer = tenant
    order = _make_order(
        restaurant,
        customer,
        order_number="REF3",
        payment_method=PaymentMethod.RAZORPAY,
        payment_status=PaymentStatus.PAID,
        gateway_metadata={"payment_id": "pay_2"},
    )
    db_session.add(order)
    await db_session.commit()

    async def failing_refund(self, payment_id, amount):
        raise RuntimeError("razorpay 500")

    monkeypatch.setattr(RazorpayGateway, "refund", failing_refund, raising=False)

    headers = await _register_and_login(client, restaurant.id)
    resp = await client.post(f"/api/v1/restaurants/{restaurant.id}/orders/{order.id}/refund", headers=headers)
    assert resp.status_code == 502

    # payment_status must NOT have flipped to REFUNDED ahead of a failed gateway call.
    # See the populate_existing() comment earlier in this file for why this isn't
    # expire_all() + a plain re-query.
    refreshed = (
        await db_session.execute(select(Order).where(Order.id == order.id).execution_options(populate_existing=True))
    ).scalar_one()
    assert refreshed.payment_status == PaymentStatus.PAID


async def test_refund_forbidden_for_cashier_role(client, db_session, tenant):
    restaurant, customer = tenant
    order = _make_order(
        restaurant, customer, order_number="REF4", payment_method=PaymentMethod.RAZORPAY, payment_status=PaymentStatus.PAID
    )
    db_session.add(order)
    await db_session.commit()

    headers = await _register_and_login(client, restaurant.id, role="cashier", email="cashier@payment-test.dev")
    resp = await client.post(f"/api/v1/restaurants/{restaurant.id}/orders/{order.id}/refund", headers=headers)
    assert resp.status_code == 403


async def test_refund_of_cod_order_returns_clear_error(client, db_session, tenant):
    restaurant, customer = tenant
    order = _make_order(
        restaurant, customer, order_number="REF5", payment_method=PaymentMethod.COD, payment_status=PaymentStatus.PAID
    )
    db_session.add(order)
    await db_session.commit()

    headers = await _register_and_login(client, restaurant.id)
    resp = await client.post(f"/api/v1/restaurants/{restaurant.id}/orders/{order.id}/refund", headers=headers)
    assert resp.status_code == 400
    assert "cash" in resp.json()["detail"].lower()


# --- status transition guard -----------------------------------------------------------------


async def test_illegal_status_transition_rejected(client, db_session, tenant):
    restaurant, customer = tenant
    order = _make_order(restaurant, customer, order_number="ST1", status=OrderStatus.PENDING)
    db_session.add(order)
    await db_session.commit()

    headers = await _register_and_login(client, restaurant.id)
    resp = await client.patch(
        f"/api/v1/restaurants/{restaurant.id}/orders/{order.id}/status", json={"status": "ready"}, headers=headers
    )
    assert resp.status_code == 400
    assert "cannot transition" in resp.json()["detail"].lower()


async def test_refunded_not_settable_via_generic_status_endpoint(client, db_session, tenant):
    restaurant, customer = tenant
    order = _make_order(restaurant, customer, order_number="ST2", status=OrderStatus.READY)
    db_session.add(order)
    await db_session.commit()

    headers = await _register_and_login(client, restaurant.id)
    resp = await client.patch(
        f"/api/v1/restaurants/{restaurant.id}/orders/{order.id}/status", json={"status": "refunded"}, headers=headers
    )
    assert resp.status_code == 400


async def test_legal_transition_chain_succeeds(client, db_session, tenant):
    restaurant, customer = tenant
    order = _make_order(restaurant, customer, order_number="ST3", status=OrderStatus.PENDING)
    db_session.add(order)
    await db_session.commit()

    headers = await _register_and_login(client, restaurant.id)
    for next_status in ("accepted", "preparing", "ready", "completed"):
        resp = await client.patch(
            f"/api/v1/restaurants/{restaurant.id}/orders/{order.id}/status",
            json={"status": next_status},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text


# --- coupon / loyalty reversal on cancellation ------------------------------------------------


async def test_cancel_reverses_coupon_redemption_and_loyalty_points(client, db_session, tenant):
    restaurant, customer = tenant
    # Customer already has 30 points (see `tenant` fixture) representing the post-spend
    # balance after redeeming 20 points for this order -- cancelling should give them back.
    coupon = Coupon(restaurant_id=restaurant.id, code="CANCELTEST", type=CouponType.FLAT, value=10)
    db_session.add(coupon)
    await db_session.flush()

    order = _make_order(restaurant, customer, order_number="CANCEL1", status=OrderStatus.PENDING, coupon_id=coupon.id)
    db_session.add(order)
    await db_session.flush()

    db_session.add(
        CouponRedemption(coupon_id=coupon.id, order_id=order.id, customer_id=customer.id, discount_amount=10)
    )
    db_session.add(
        LoyaltyTransaction(
            restaurant_id=restaurant.id,
            customer_id=customer.id,
            order_id=order.id,
            points_delta=-20,
            reason=LoyaltyReason.REDEEMED,
        )
    )
    await db_session.commit()

    headers = await _register_and_login(client, restaurant.id)
    resp = await client.patch(
        f"/api/v1/restaurants/{restaurant.id}/orders/{order.id}/status", json={"status": "cancelled"}, headers=headers
    )
    assert resp.status_code == 200, resp.text

    remaining_redemptions = (
        await db_session.execute(select(CouponRedemption).where(CouponRedemption.order_id == order.id))
    ).scalars().all()
    assert remaining_redemptions == []

    refreshed_customer = (
        await db_session.execute(
            select(Customer).where(Customer.id == customer.id).execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert refreshed_customer.loyalty_points == 50  # 30 + 20 restored


async def test_cancel_without_coupon_or_loyalty_is_a_noop(client, db_session, tenant):
    restaurant, customer = tenant
    order = _make_order(restaurant, customer, order_number="CANCEL2", status=OrderStatus.PENDING)
    db_session.add(order)
    await db_session.commit()

    headers = await _register_and_login(client, restaurant.id)
    resp = await client.patch(
        f"/api/v1/restaurants/{restaurant.id}/orders/{order.id}/status", json={"status": "cancelled"}, headers=headers
    )
    assert resp.status_code == 200

    refreshed_customer = (
        await db_session.execute(
            select(Customer).where(Customer.id == customer.id).execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert refreshed_customer.loyalty_points == 30  # unchanged


# --- COD completion accuracy -------------------------------------------------------------------


async def test_cod_completion_marks_payment_paid(client, db_session, tenant):
    restaurant, customer = tenant
    order = _make_order(
        restaurant,
        customer,
        order_number="COD1",
        status=OrderStatus.READY,
        payment_method=PaymentMethod.COD,
        payment_status=PaymentStatus.PENDING,
    )
    db_session.add(order)
    await db_session.commit()

    headers = await _register_and_login(client, restaurant.id)
    resp = await client.patch(
        f"/api/v1/restaurants/{restaurant.id}/orders/{order.id}/status", json={"status": "completed"}, headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["payment_status"] == "paid"


async def test_razorpay_completion_does_not_touch_payment_status(client, db_session, tenant):
    restaurant, customer = tenant
    order = _make_order(
        restaurant,
        customer,
        order_number="RZP5",
        status=OrderStatus.READY,
        payment_method=PaymentMethod.RAZORPAY,
        payment_status=PaymentStatus.PENDING,
    )
    db_session.add(order)
    await db_session.commit()

    headers = await _register_and_login(client, restaurant.id)
    resp = await client.patch(
        f"/api/v1/restaurants/{restaurant.id}/orders/{order.id}/status", json={"status": "completed"}, headers=headers
    )
    assert resp.status_code == 200
    # Razorpay orders' payment_status is only ever changed by the webhook -- completion
    # alone must not silently mark it paid.
    assert resp.json()["payment_status"] == "pending"


# --- customer-facing WhatsApp notifications -----------------------------------------------------


async def test_customer_notified_on_status_change(client, db_session, tenant, _fake_senders):
    restaurant, customer = tenant
    order = _make_order(restaurant, customer, order_number="NOTIFY1", status=OrderStatus.PENDING)
    db_session.add(order)
    await db_session.commit()

    headers = await _register_and_login(client, restaurant.id)
    resp = await client.patch(
        f"/api/v1/restaurants/{restaurant.id}/orders/{order.id}/status", json={"status": "accepted"}, headers=headers
    )
    assert resp.status_code == 200

    sent = _fake_senders["orders"].sent
    assert len(sent) == 1
    assert sent[0].to == CUSTOMER_PHONE
    assert order.order_number in sent[0].payload["text"]["body"]
    assert "accepted" in sent[0].payload["text"]["body"].lower()


async def test_pickup_ready_message_says_pickup_not_delivery(client, db_session, tenant, _fake_senders):
    restaurant, customer = tenant
    order = _make_order(
        restaurant, customer, order_number="NOTIFY2", status=OrderStatus.PREPARING, fulfillment_type=FulfillmentType.PICKUP
    )
    db_session.add(order)
    await db_session.commit()

    headers = await _register_and_login(client, restaurant.id)
    resp = await client.patch(
        f"/api/v1/restaurants/{restaurant.id}/orders/{order.id}/status", json={"status": "ready"}, headers=headers
    )
    assert resp.status_code == 200

    body = _fake_senders["orders"].sent[-1].payload["text"]["body"].lower()
    assert "pickup" in body
    assert "delivery" not in body


async def test_whatsapp_send_failure_does_not_break_status_update(client, db_session, tenant, monkeypatch):
    restaurant, customer = tenant
    order = _make_order(restaurant, customer, order_number="NOTIFY3", status=OrderStatus.PENDING)
    db_session.add(order)
    await db_session.commit()

    async def boom(self, phone_number_id, access_token, message):
        raise RuntimeError("whatsapp api down")

    monkeypatch.setattr(InMemoryWhatsAppSender, "send", boom)

    headers = await _register_and_login(client, restaurant.id)
    resp = await client.patch(
        f"/api/v1/restaurants/{restaurant.id}/orders/{order.id}/status", json={"status": "accepted"}, headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "accepted"


# --- OrderRead customer_name/customer_phone -----------------------------------------------------


async def test_order_read_includes_customer_name_and_phone(client, db_session, tenant):
    restaurant, customer = tenant
    order = _make_order(restaurant, customer, order_number="CUST1", status=OrderStatus.PENDING)
    db_session.add(order)
    await db_session.commit()

    headers = await _register_and_login(client, restaurant.id)
    resp = await client.get(f"/api/v1/restaurants/{restaurant.id}/orders/{order.id}", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["customer_name"] == "Jane Doe"
    assert body["customer_phone"] == CUSTOMER_PHONE

    list_resp = await client.get(f"/api/v1/restaurants/{restaurant.id}/orders", headers=headers)
    assert list_resp.status_code == 200
    assert list_resp.json()[0]["customer_name"] == "Jane Doe"


# --- dashboard: paid_revenue vs revenue -----------------------------------------------------------


async def test_dashboard_stats_paid_revenue_only_counts_paid_orders(db_session, tenant):
    from datetime import datetime, timedelta, timezone

    restaurant, customer = tenant
    since = datetime.now(timezone.utc) - timedelta(days=1)

    paid = _make_order(restaurant, customer, order_number="DASH1", payment_status=PaymentStatus.PAID, total=100)
    unpaid = _make_order(restaurant, customer, order_number="DASH2", payment_status=PaymentStatus.PENDING, total=50)
    db_session.add_all([paid, unpaid])
    await db_session.commit()

    stats = await OrderRepository(db_session).dashboard_stats(restaurant.id, since)
    assert stats["revenue"] == 150  # gross, regardless of payment_status
    assert stats["paid_revenue"] == 100  # only the PAID order
