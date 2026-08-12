import pytest
from sqlalchemy import select

from app.models.conversation_state import ConversationState
from app.models.coupon import Coupon, CouponRedemption
from app.models.customer import Customer
from app.models.enums import ConversationStep, CouponType
from app.models.faq import FaqEntry
from app.models.order import Order
from app.tests.test_flow_engine import (  # noqa: F401 -- reuse fixtures/helpers
    PHONE_NUMBER_ID,
    _button_reply,
    _list_reply,
    _message_value,
    _post_webhook,
    _text,
    _use_in_memory_sender,
    demo_tenant,
)


async def _register_and_login(client, restaurant_id, email="phase2-owner@kelviontech.dev"):
    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "TestPass123!", "role": "owner", "restaurant_id": str(restaurant_id)},
    )
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": "TestPass123!"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _drive_to_coupon_step(client, demo_tenant):
    category, product = demo_tenant["category"], demo_tenant["product"]
    await _post_webhook(client, _message_value(_text("hi")))
    await _post_webhook(client, _message_value(_button_reply("button:order_food")))
    await _post_webhook(client, _message_value(_list_reply(f"category:{category.id}")))
    await _post_webhook(client, _message_value(_list_reply(f"product:{product.id}")))
    await _post_webhook(client, _message_value(_text("2")))  # 2 x 150 = 300 subtotal
    await _post_webhook(client, _message_value(_button_reply("cart:checkout")))
    await _post_webhook(client, _message_value(_button_reply("fulfillment:delivery")))


async def test_coupon_code_applies_discount_to_order(client, db_session, demo_tenant):
    restaurant = demo_tenant["restaurant"]
    coupon = Coupon(restaurant_id=restaurant.id, code="SAVE30", type=CouponType.FLAT, value=30)
    db_session.add(coupon)
    await db_session.commit()

    await _drive_to_coupon_step(client, demo_tenant)
    await _post_webhook(client, _message_value(_text("SAVE30")))
    await _post_webhook(client, _message_value(_text("123 Test Street")))
    await _post_webhook(client, _message_value(_button_reply("order:confirm")))

    result = await db_session.execute(select(Order))
    order = result.scalar_one()
    assert order.discount == 30
    assert order.total == 300 + 15 + 20 - 30  # subtotal + tax + delivery - discount
    assert order.coupon_id == coupon.id

    redemption = (await db_session.execute(select(CouponRedemption))).scalar_one()
    assert redemption.discount_amount == 30


async def test_invalid_coupon_code_reprompts_without_advancing(client, db_session, demo_tenant):
    await _drive_to_coupon_step(client, demo_tenant)
    await _post_webhook(client, _message_value(_text("NOTREAL")))

    result = await db_session.execute(select(ConversationState))
    state = result.scalar_one()
    assert state.current_step == ConversationStep.COLLECT_COUPON


async def test_skip_coupon_proceeds_to_address(client, db_session, demo_tenant):
    await _drive_to_coupon_step(client, demo_tenant)
    await _post_webhook(client, _message_value(_text("skip")))

    result = await db_session.execute(select(ConversationState))
    state = result.scalar_one()
    assert state.current_step == ConversationStep.COLLECT_ADDRESS


async def test_redeem_loyalty_points_applies_discount(client, db_session, demo_tenant):
    restaurant = demo_tenant["restaurant"]
    restaurant.loyalty_settings = {"points_per_currency_unit": 0.1, "redemption_value_per_point": 1.0}

    # Pre-seed a customer with points under the same phone the webhook will use.
    from app.tests.test_flow_engine import CUSTOMER_PHONE

    customer = Customer(restaurant_id=restaurant.id, phone=CUSTOMER_PHONE, loyalty_points=100)
    db_session.add(customer)
    await db_session.commit()

    await _drive_to_coupon_step(client, demo_tenant)
    await _post_webhook(client, _message_value(_text("REDEEM 40")))
    await _post_webhook(client, _message_value(_text("123 Test Street")))
    await _post_webhook(client, _message_value(_button_reply("order:confirm")))

    order = (await db_session.execute(select(Order))).scalar_one()
    assert order.discount == 40

    await db_session.refresh(customer)
    assert customer.loyalty_points == 60


async def test_faq_match_answers_without_handover(client, db_session, demo_tenant):
    restaurant = demo_tenant["restaurant"]
    db_session.add(FaqEntry(restaurant_id=restaurant.id, trigger_keywords=["delivery time"], answer="We deliver in 30-45 minutes."))
    await db_session.commit()

    await _post_webhook(client, _message_value(_text("what's your delivery time?")))

    state = (await db_session.execute(select(ConversationState))).scalar_one()
    assert state.current_step == ConversationStep.WELCOME  # stayed put, no handover


async def test_unmatched_free_text_triggers_handover(client, db_session, demo_tenant):
    await _post_webhook(client, _message_value(_text("completely unrelated gibberish question")))

    state = (await db_session.execute(select(ConversationState))).scalar_one()
    assert state.current_step == ConversationStep.HANDED_OVER


async def test_staff_can_reply_and_resolve_handed_over_conversation(client, db_session, demo_tenant):
    restaurant = demo_tenant["restaurant"]
    await _post_webhook(client, _message_value(_text("agent please")))

    state = (await db_session.execute(select(ConversationState))).scalar_one()
    assert state.current_step == ConversationStep.HANDED_OVER
    customer_id = state.customer_id

    headers = await _register_and_login(client, restaurant.id)

    conversations = await client.get(f"/api/v1/restaurants/{restaurant.id}/conversations", headers=headers)
    assert conversations.status_code == 200
    assert any(c["customer_id"] == str(customer_id) for c in conversations.json())

    reply = await client.post(
        f"/api/v1/restaurants/{restaurant.id}/conversations/{customer_id}/messages",
        json={"body": "Hi, how can I help?"},
        headers=headers,
    )
    assert reply.status_code == 201

    resolve = await client.post(f"/api/v1/restaurants/{restaurant.id}/conversations/{customer_id}/resolve", headers=headers)
    assert resolve.status_code == 204

    await db_session.refresh(state)
    assert state.current_step == ConversationStep.WELCOME


async def test_order_completion_awards_loyalty_points(client, db_session, demo_tenant):
    restaurant = demo_tenant["restaurant"]
    restaurant.loyalty_settings = {"points_per_currency_unit": 0.1, "redemption_value_per_point": 1.0}
    await db_session.commit()

    await _drive_to_coupon_step(client, demo_tenant)
    await _post_webhook(client, _message_value(_text("skip")))
    await _post_webhook(client, _message_value(_text("123 Test Street")))
    await _post_webhook(client, _message_value(_button_reply("order:confirm")))

    order = (await db_session.execute(select(Order))).scalar_one()
    headers = await _register_and_login(client, restaurant.id, email="loyalty-owner@kelviontech.dev")

    # The generic status endpoint now enforces a legal transition graph (pending -> accepted
    # -> preparing -> ready -> completed); walk through it instead of jumping straight to
    # "completed".
    for next_status in ("accepted", "preparing", "ready", "completed"):
        resp = await client.patch(
            f"/api/v1/restaurants/{restaurant.id}/orders/{order.id}/status",
            json={"status": next_status},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text

    customer = (await db_session.execute(select(Customer))).scalar_one()
    assert customer.loyalty_points > 0
