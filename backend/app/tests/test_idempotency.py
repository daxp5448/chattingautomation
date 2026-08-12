import pytest
from sqlalchemy import select

from app.models.branch import Branch
from app.models.category import Category
from app.models.conversation_state import ConversationState
from app.models.enums import BranchStatus, ConversationStep
from app.models.message import Message
from app.models.order import Order
from app.models.product import Product
from app.models.restaurant import Restaurant
from app.services.flow_engine import InboundInteraction, process_inbound_message
from app.services.whatsapp_client import InMemoryWhatsAppSender

PHONE = "919999999999"


@pytest.fixture
async def tenant(db_session):
    restaurant = Restaurant(name="Idem Test", slug="idem-test", whatsapp_phone_number_id="IDEM_PHONE")
    db_session.add(restaurant)
    await db_session.flush()

    branch = Branch(restaurant_id=restaurant.id, name="Main", status=BranchStatus.OPEN)
    category = Category(restaurant_id=restaurant.id, name="Mains", display_order=1)
    db_session.add_all([branch, category])
    await db_session.flush()

    product = Product(restaurant_id=restaurant.id, category_id=category.id, name="Burger", price=100, gst_percent=0)
    db_session.add(product)
    await db_session.commit()

    return {"restaurant": restaurant, "branch": branch, "category": category, "product": product}


async def _send(db_session, sender, restaurant, interaction, wa_message_id):
    await process_inbound_message(db_session, sender, restaurant, PHONE, interaction, wa_message_id=wa_message_id)


async def _drive_to_confirm(db_session, sender, restaurant, category, product):
    """Direct calls into `process_inbound_message` (not the webhook route -- webhook.py
    isn't wired up to pass `wa_message_id` yet, see the report), driving one full order
    conversation up to (but not including) the final "confirm" tap.
    """
    steps = [
        (InboundInteraction(kind="text", text="hi"), "wamid.1"),
        (InboundInteraction(kind="button_reply", reply_id="button:order_food"), "wamid.2"),
        (InboundInteraction(kind="list_reply", reply_id=f"category:{category.id}"), "wamid.3"),
        (InboundInteraction(kind="list_reply", reply_id=f"product:{product.id}"), "wamid.4"),
        (InboundInteraction(kind="text", text="2"), "wamid.5"),
        (InboundInteraction(kind="button_reply", reply_id="cart:checkout"), "wamid.6"),
        (InboundInteraction(kind="button_reply", reply_id="fulfillment:delivery"), "wamid.7"),
        (InboundInteraction(kind="text", text="skip"), "wamid.8"),
        (InboundInteraction(kind="text", text="123 Test Street"), "wamid.9"),
    ]
    for interaction, wa_id in steps:
        await _send(db_session, sender, restaurant, interaction, wa_id)


async def test_replayed_confirm_message_id_does_not_duplicate_order(db_session, tenant):
    restaurant, category, product = tenant["restaurant"], tenant["category"], tenant["product"]
    sender = InMemoryWhatsAppSender()

    await _drive_to_confirm(db_session, sender, restaurant, category, product)

    confirm_interaction = InboundInteraction(kind="button_reply", reply_id="order:confirm")
    await _send(db_session, sender, restaurant, confirm_interaction, "wamid.confirm")

    orders = list((await db_session.execute(select(Order))).scalars().all())
    assert len(orders) == 1
    first_order_id = orders[0].id

    # Simulate the exact window an at-least-once webhook redelivery would hit: Meta
    # resends the identical payload (same message id) because it never saw our 200 for the
    # first delivery. Rewind the conversation state back to CONFIRM_ORDER with its
    # pre-confirm cart/address intact, as if the bot's transition to WELCOME "hadn't
    # happened yet" from Meta's point of view. Without the wa_message_id guard, replaying
    # "order:confirm" here would re-run _confirm_order and create a second order from the
    # same cart -- exactly the double-order bug this fix exists to prevent.
    state = (await db_session.execute(select(ConversationState))).scalar_one()
    state.current_step = ConversationStep.CONFIRM_ORDER
    state.context = {
        **state.context,
        "cart": [{"product_id": str(product.id), "name": product.name, "price": float(product.price), "gst_percent": 0.0, "qty": 2}],
        "address": "123 Test Street",
    }
    await db_session.commit()

    await _send(db_session, sender, restaurant, confirm_interaction, "wamid.confirm")

    orders = list((await db_session.execute(select(Order))).scalars().all())
    assert len(orders) == 1
    assert orders[0].id == first_order_id

    confirm_messages = list(
        (await db_session.execute(select(Message).where(Message.wa_message_id == "wamid.confirm"))).scalars().all()
    )
    assert len(confirm_messages) == 1


async def test_new_message_id_after_confirmed_order_is_processed_but_not_duplicated(db_session, tenant):
    restaurant, category, product = tenant["restaurant"], tenant["category"], tenant["product"]
    sender = InMemoryWhatsAppSender()

    await _drive_to_confirm(db_session, sender, restaurant, category, product)
    await _send(
        db_session, sender, restaurant, InboundInteraction(kind="button_reply", reply_id="order:confirm"), "wamid.confirm"
    )

    orders = list((await db_session.execute(select(Order))).scalars().all())
    assert len(orders) == 1

    # A genuinely new inbound message (its own, never-seen-before wa_message_id) after the
    # order is already confirmed must still be processed normally -- the idempotency guard
    # must not swallow legitimately distinct messages -- and, since it's just a plain "hi"
    # (not a repeat of the order-confirming flow), it must not itself create another order.
    await _send(db_session, sender, restaurant, InboundInteraction(kind="text", text="hi"), "wamid.new-and-different")

    orders = list((await db_session.execute(select(Order))).scalars().all())
    assert len(orders) == 1

    logged_ids = set(
        (await db_session.execute(select(Message.wa_message_id).where(Message.wa_message_id.isnot(None)))).scalars().all()
    )
    assert "wamid.new-and-different" in logged_ids
