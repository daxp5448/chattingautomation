"""Covers items 4-6 of the flow_engine/order_service/menu_repository change set:
stock enforcement at order-confirm time (including the atomic check-and-decrement race),
zero-total orders skipping Razorpay, and Razorpay payment-link failures leaving the order
retryable instead of half-created.
"""
import itertools

import pytest
from sqlalchemy import select

from app.models.conversation_state import ConversationState
from app.models.coupon import Coupon
from app.models.enums import ConversationStep, CouponType
from app.models.order import Order
from app.repositories.menu_repository import ProductRepository
from app.services.payment.razorpay import RazorpayGateway
from app.tests.test_flow_engine import (  # noqa: F401 -- reuse fixtures/helpers
    PHONE_NUMBER_ID,
    _button_reply,
    _message_value,
    _post_webhook,
    _text,
    _use_in_memory_sender,
    demo_tenant,
)

_counter = itertools.count(9000)


def _message_value_for(phone: str, message: dict) -> dict:
    """Like `test_flow_engine._message_value`, but for a caller-chosen phone number so two
    independent customer conversations can be driven in the same test (needed to simulate
    two near-simultaneous confirms racing for the same product's last unit)."""
    wa_message_id = f"wamid.stocktest.{next(_counter)}"
    return {
        "messaging_product": "whatsapp",
        "metadata": {"phone_number_id": PHONE_NUMBER_ID},
        "contacts": [{"wa_id": phone}],
        "messages": [{"from": phone, "id": wa_message_id, **message}],
    }


async def _drive_to_confirm(client, demo_tenant, phone: str, qty: str = "1"):
    category = demo_tenant["category"]
    product = demo_tenant["product"]
    await _post_webhook(client, _message_value_for(phone, _text("hi")))
    await _post_webhook(client, _message_value_for(phone, _button_reply("button:order_food")))
    await _post_webhook(client, _message_value_for(phone, {"type": "interactive", "interactive": {"type": "list_reply", "list_reply": {"id": f"category:{category.id}", "title": "x"}}}))
    await _post_webhook(client, _message_value_for(phone, {"type": "interactive", "interactive": {"type": "list_reply", "list_reply": {"id": f"product:{product.id}", "title": "x"}}}))
    await _post_webhook(client, _message_value_for(phone, _text(qty)))
    await _post_webhook(client, _message_value_for(phone, _button_reply("cart:checkout")))
    await _post_webhook(client, _message_value_for(phone, _button_reply("fulfillment:pickup")))
    await _post_webhook(client, _message_value_for(phone, _text("skip")))  # no coupon
    await _post_webhook(client, _message_value_for(phone, _text("skip")))  # no notes -- lands on CONFIRM_ORDER


# --- Atomic check-and-decrement (repository level, mirrors loyalty_service's test) -------


async def test_decrement_stock_atomic_rejects_overselling(db_session, demo_tenant):
    product = demo_tenant["product"]
    product.stock_quantity = 1
    await db_session.commit()

    repo = ProductRepository(db_session)
    assert await repo.decrement_stock(product.id, 1) is True
    await db_session.refresh(product)
    assert product.stock_quantity == 0

    # A second decrement attempt for the same (now depleted) product must be rejected using
    # the DB's current value, not a stale in-memory one -- and must not go negative.
    assert await repo.decrement_stock(product.id, 1) is False
    await db_session.refresh(product)
    assert product.stock_quantity == 0


async def test_decrement_stock_unlimited_when_quantity_none(db_session, demo_tenant):
    product = demo_tenant["product"]
    assert product.stock_quantity is None
    repo = ProductRepository(db_session)
    # decrement_stock itself only operates on rows satisfying `stock_quantity >= qty`; NULL
    # never satisfies that, so unlimited-stock products are the caller's job to skip (see
    # FlowEngine._reserve_cart_stock) rather than this method's.
    assert await repo.decrement_stock(product.id, 1) is False


# --- Flow-level stock enforcement ---------------------------------------------------------


async def test_confirm_succeeds_and_decrements_stock_when_sufficient(client, db_session, demo_tenant):
    product = demo_tenant["product"]
    product.stock_quantity = 5
    await db_session.commit()

    await _drive_to_confirm(client, demo_tenant, "911000000001", qty="2")
    await _post_webhook(client, _message_value_for("911000000001", _button_reply("order:confirm")))

    orders = list((await db_session.execute(select(Order))).scalars().all())
    assert len(orders) == 1

    await db_session.refresh(product)
    assert product.stock_quantity == 3


async def test_confirm_rejected_and_returns_to_cart_when_insufficient(client, db_session, demo_tenant):
    product = demo_tenant["product"]
    product.stock_quantity = 1
    await db_session.commit()

    await _drive_to_confirm(client, demo_tenant, "911000000002", qty="2")  # wants 2, only 1 in stock
    await _post_webhook(client, _message_value_for("911000000002", _button_reply("order:confirm")))

    orders = list((await db_session.execute(select(Order))).scalars().all())
    assert len(orders) == 0

    state = (await db_session.execute(select(ConversationState))).scalar_one()
    assert state.current_step == ConversationStep.CART

    await db_session.refresh(product)
    assert product.stock_quantity == 1  # untouched -- the failed attempt didn't decrement anything


async def test_concurrent_confirms_for_last_unit_only_one_succeeds(client, db_session, demo_tenant):
    """Two different customers both order the last remaining unit of the same product and
    both reach "Confirm Order". Simulates the near-simultaneous-confirm race: the first
    "order:confirm" to actually execute wins the atomic stock decrement, the second is
    rejected -- exactly one order is created, and stock never goes negative.
    """
    product = demo_tenant["product"]
    product.stock_quantity = 1
    await db_session.commit()

    phone_a, phone_b = "911000000003", "911000000004"
    await _drive_to_confirm(client, demo_tenant, phone_a, qty="1")
    await _drive_to_confirm(client, demo_tenant, phone_b, qty="1")

    await _post_webhook(client, _message_value_for(phone_a, _button_reply("order:confirm")))
    await _post_webhook(client, _message_value_for(phone_b, _button_reply("order:confirm")))

    orders = list((await db_session.execute(select(Order))).scalars().all())
    assert len(orders) == 1

    await db_session.refresh(product)
    assert product.stock_quantity == 0


# --- Zero-total orders skip Razorpay -------------------------------------------------------


async def test_zero_total_order_skips_razorpay_and_confirms_directly(client, db_session, demo_tenant, monkeypatch):
    restaurant = demo_tenant["restaurant"]
    restaurant.payment_methods = ["cod", "razorpay"]
    restaurant.default_payment_method = "razorpay"
    restaurant.delivery_charge = 0
    product = demo_tenant["product"]
    product.gst_percent = 0
    coupon = Coupon(restaurant_id=restaurant.id, code="FREEBIE", type=CouponType.FLAT, value=150)  # == 1 x product price
    db_session.add(coupon)
    await db_session.commit()

    async def _must_not_be_called(self, order):
        raise AssertionError("Razorpay must not be called for a zero-total order")

    monkeypatch.setattr(RazorpayGateway, "create_payment", _must_not_be_called)

    phone = "911000000005"
    category = demo_tenant["category"]
    await _post_webhook(client, _message_value_for(phone, _text("hi")))
    await _post_webhook(client, _message_value_for(phone, _button_reply("button:order_food")))
    await _post_webhook(client, _message_value_for(phone, {"type": "interactive", "interactive": {"type": "list_reply", "list_reply": {"id": f"category:{category.id}", "title": "x"}}}))
    await _post_webhook(client, _message_value_for(phone, {"type": "interactive", "interactive": {"type": "list_reply", "list_reply": {"id": f"product:{product.id}", "title": "x"}}}))
    await _post_webhook(client, _message_value_for(phone, _text("1")))
    await _post_webhook(client, _message_value_for(phone, _button_reply("cart:checkout")))
    await _post_webhook(client, _message_value_for(phone, _button_reply("fulfillment:pickup")))
    await _post_webhook(client, _message_value_for(phone, _text("FREEBIE")))
    await _post_webhook(client, _message_value_for(phone, _text("skip")))  # no notes
    await _post_webhook(client, _message_value_for(phone, _button_reply("order:confirm")))

    order = (await db_session.execute(select(Order))).scalar_one()
    assert order.total == 0
    assert not order.gateway_metadata.get("payment_link_url")

    state = (await db_session.execute(select(ConversationState))).scalar_one()
    assert state.current_step == ConversationStep.COMPLETED


# --- Razorpay failure leaves the order retryable, doesn't destroy anything ----------------


async def test_razorpay_failure_is_retryable_and_does_not_duplicate(client, db_session, demo_tenant, monkeypatch):
    restaurant = demo_tenant["restaurant"]
    restaurant.payment_methods = ["cod", "razorpay"]
    restaurant.default_payment_method = "razorpay"
    await db_session.commit()

    async def _boom(self, order):
        raise RuntimeError("Razorpay API unreachable")

    monkeypatch.setattr(RazorpayGateway, "create_payment", _boom)

    phone = "911000000006"
    await _drive_to_confirm(client, demo_tenant, phone, qty="1")
    await _post_webhook(client, _message_value_for(phone, _button_reply("order:confirm")))

    orders = list((await db_session.execute(select(Order))).scalars().all())
    assert len(orders) == 0  # rolled back, nothing half-created

    state = (await db_session.execute(select(ConversationState))).scalar_one()
    assert state.current_step == ConversationStep.CONFIRM_ORDER  # still retryable
    assert state.context.get("cart")  # cart/context untouched

    async def _works(self, order):
        return {"payment_link_id": "plink_123", "payment_link_url": "https://razorpay.test/plink_123"}

    monkeypatch.setattr(RazorpayGateway, "create_payment", _works)
    await _post_webhook(client, _message_value_for(phone, _button_reply("order:confirm")))

    orders = list((await db_session.execute(select(Order))).scalars().all())
    assert len(orders) == 1
    assert orders[0].gateway_metadata.get("payment_link_url") == "https://razorpay.test/plink_123"

    await db_session.refresh(state)
    assert state.current_step == ConversationStep.COMPLETED
