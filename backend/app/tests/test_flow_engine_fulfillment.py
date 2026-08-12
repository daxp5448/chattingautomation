from sqlalchemy import select

from app.models.enums import ConversationStep, FulfillmentType
from app.models.order import Order
from app.tests.test_flow_engine import (  # noqa: F401 -- reuse fixtures/helpers
    _button_reply,
    _list_reply,
    _location,
    _message_value,
    _post_webhook,
    _text,
    _use_in_memory_sender,
    demo_tenant,
)


async def _drive_to_cart(client, demo_tenant):
    category, product = demo_tenant["category"], demo_tenant["product"]
    await _post_webhook(client, _message_value(_text("hi")))
    await _post_webhook(client, _message_value(_button_reply("button:order_food")))
    await _post_webhook(client, _message_value(_list_reply(f"category:{category.id}")))
    await _post_webhook(client, _message_value(_list_reply(f"product:{product.id}")))
    await _post_webhook(client, _message_value(_text("2")))  # 2 x 150 = 300 subtotal
    await _post_webhook(client, _message_value(_button_reply("cart:checkout")))


async def test_pickup_skips_address_and_delivery_charge(client, db_session, demo_tenant):
    await _drive_to_cart(client, demo_tenant)
    await _post_webhook(client, _message_value(_button_reply("fulfillment:pickup")))
    await _post_webhook(client, _message_value(_text("skip")))  # no coupon
    await _post_webhook(client, _message_value(_text("skip")))  # no special instructions -- straight to confirm
    await _post_webhook(client, _message_value(_button_reply("order:confirm")))

    order = (await db_session.execute(select(Order))).scalar_one()
    assert order.fulfillment_type == FulfillmentType.PICKUP
    assert order.delivery_charge == 0
    assert order.subtotal == 300
    assert order.total == 315  # subtotal + 5% tax, no delivery charge
    assert order.notes is None


async def test_pickup_collects_cooking_notes(client, db_session, demo_tenant):
    await _drive_to_cart(client, demo_tenant)
    await _post_webhook(client, _message_value(_button_reply("fulfillment:pickup")))
    await _post_webhook(client, _message_value(_text("skip")))  # no coupon
    await _post_webhook(client, _message_value(_text("extra spicy please")))
    await _post_webhook(client, _message_value(_button_reply("order:confirm")))

    order = (await db_session.execute(select(Order))).scalar_one()
    assert order.fulfillment_type == FulfillmentType.PICKUP
    assert order.notes == "extra spicy please"


async def test_delivery_accepts_shared_location_as_address(client, db_session, demo_tenant):
    await _drive_to_cart(client, demo_tenant)
    await _post_webhook(client, _message_value(_button_reply("fulfillment:delivery")))
    await _post_webhook(client, _message_value(_text("skip")))
    await _post_webhook(client, _message_value(_location(23.0225, 72.5714, name="Home")))
    await _post_webhook(client, _message_value(_button_reply("order:confirm")))

    order = (await db_session.execute(select(Order))).scalar_one()
    assert order.fulfillment_type == FulfillmentType.DELIVERY
    assert order.delivery_charge == 20
    assert "Home" in order.delivery_address["address"]
    assert order.delivery_address["latitude"] == 23.0225
    assert order.delivery_address["longitude"] == 72.5714


async def test_pickup_prompt_shown_after_checkout(client, db_session, demo_tenant):
    await _drive_to_cart(client, demo_tenant)

    from app.models.conversation_state import ConversationState

    state = (await db_session.execute(select(ConversationState))).scalar_one()
    assert state.current_step == ConversationStep.SELECT_FULFILLMENT
