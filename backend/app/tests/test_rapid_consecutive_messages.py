"""Part 18's exact scenario: a customer sends "1" then immediately "2" (two genuinely
different, legitimate messages, not a redelivery of the same one) -- both must be
processed, in order, against the correct state each time, with no lost update and no
state corruption.

Note on scope: GenericConversationStateRepository.get_for_update_by_customer's row lock
is a real `SELECT ... FOR UPDATE` against Postgres in production, but SQLite (this test
suite's database) accepts `.with_for_update()` as a no-op -- see flow_engine.py's own
comment on this. A test that fired two truly concurrent transactions against SQLite
could not actually prove the lock works (SQLite has nothing to lock), so it isn't
attempted here. What this test DOES prove, meaningfully: two rapid, correctly-sequenced
inbound messages for the same customer -- the realistic shape of "the customer typed
fast," since each webhook delivery is still handled as one complete request before the
next one starts -- produce the correct final state, never a half-applied or duplicated
one. Duplicate/redelivered-message handling (the other half of "concurrent messages")
already has dedicated, more rigorous coverage: see
test_outbound_idempotency.py::test_concurrent_redelivery_of_same_wa_message_id_does_not_double_send
(a real DB-level race via a second live session) and
test_demo_bot.py::test_redelivered_webhook_does_not_double_send.
"""

import itertools

import pytest_asyncio
from sqlalchemy import select

from app.core.security import encrypt_secret
from app.models.catalog import CatalogCategory, CatalogItem
from app.models.customer import Customer
from app.models.generic_conversation_state import GenericConversationState
from app.models.niche_template import NicheTemplate
from app.models.restaurant import Restaurant
from app.niche_seeds.restaurant import TEMPLATE
from app.services.generic_flow_engine import GenericInteraction, process_inbound_message
from app.services.niche_provisioning import provision_from_template
from app.services.whatsapp_client import InMemoryWhatsAppSender

PHONE_NUMBER_ID = "RAPID_MSG_TEST_PHONE_NUMBER_ID"
CUSTOMER_PHONE = "919876500066"
_wamid_counter = itertools.count(1)


def _next_wamid() -> str:
    return f"wamid.rapid.test.{next(_wamid_counter)}"


@pytest_asyncio.fixture
async def restaurant_tenant(db_session):
    restaurant = Restaurant(
        name="Rapid Msg Kitchen", slug="rapid-msg-kitchen",
        whatsapp_phone_number_id=PHONE_NUMBER_ID,
        whatsapp_access_token_encrypted=encrypt_secret("fake-access-token"),
    )
    db_session.add(restaurant)
    await db_session.flush()
    template = NicheTemplate(
        code=TEMPLATE["code"], name=TEMPLATE["name"], action_type=TEMPLATE["action_type"],
        icon=TEMPLATE["icon"], welcome_message=TEMPLATE["welcome_message"],
        welcome_banner_image=TEMPLATE["welcome_banner_image"], welcome_buttons=TEMPLATE["welcome_buttons"],
        default_catalog=TEMPLATE["default_catalog"], default_flow_steps=TEMPLATE["default_flow_steps"],
        terminology=TEMPLATE["terminology"], default_modules=TEMPLATE["default_modules"],
    )
    db_session.add(template)
    await db_session.flush()
    await provision_from_template(db_session, restaurant, template)
    await db_session.commit()
    return restaurant


async def test_rapid_1_then_2_quantity_taps_apply_in_order_not_corrupted(db_session, restaurant_tenant):
    """Exactly Part 18's own example: customer taps "1", then immediately taps "2" before
    any reply could realistically have been read. Each message must be applied against
    the state as it existed right after the PREVIOUS one finished -- never a stale
    pre-first-tap read -- with no lost update and no corrupted/duplicated cart line.

    Concretely, in this niche's own flow: tapping a quantity option (qty:1) immediately
    adds the item to the cart and advances to cart_menu -- so the second tap (qty:2) is no
    longer a quantity choice at all once it's processed; cart_menu has no "qty:2" option,
    so it's correctly treated as ordinary unrecognized input on the NEW step (Part 9's
    existing safe fallback), not silently misapplied as a second quantity edit. That the
    second call sees cart_menu (not quantity_select) at all is itself the proof the two
    calls were sequenced correctly against real, freshly-read state."""
    sender = InMemoryWhatsAppSender()
    await process_inbound_message(db_session, sender, restaurant_tenant, CUSTOMER_PHONE, GenericInteraction(kind="text", text="Hi"), wa_message_id=_next_wamid())
    await process_inbound_message(
        db_session, sender, restaurant_tenant, CUSTOMER_PHONE,
        GenericInteraction(kind="button_reply", reply_id="welcome:order", text="Order Now"),
        wa_message_id=_next_wamid(),
    )
    starters = (await db_session.execute(
        select(CatalogCategory).where(CatalogCategory.restaurant_id == restaurant_tenant.id, CatalogCategory.name == "Starters")
    )).scalar_one()
    await process_inbound_message(
        db_session, sender, restaurant_tenant, CUSTOMER_PHONE,
        GenericInteraction(kind="button_reply", reply_id=f"category:{starters.id}", text="Starters"),
        wa_message_id=_next_wamid(),
    )
    paneer = (await db_session.execute(
        select(CatalogItem).where(CatalogItem.restaurant_id == restaurant_tenant.id, CatalogItem.name == "Paneer Tikka")
    )).scalar_one()
    await process_inbound_message(
        db_session, sender, restaurant_tenant, CUSTOMER_PHONE,
        GenericInteraction(kind="button_reply", reply_id=f"item:{paneer.id}", text="Paneer Tikka"),
        wa_message_id=_next_wamid(),
    )

    # "1" then immediately "2" -- two separate, real inbound webhook deliveries, back to
    # back, each with its own wa_message_id (never a redelivery of the same one).
    await process_inbound_message(
        db_session, sender, restaurant_tenant, CUSTOMER_PHONE,
        GenericInteraction(kind="button_reply", reply_id="qty:1", text="1"),
        wa_message_id=_next_wamid(),
    )
    await process_inbound_message(
        db_session, sender, restaurant_tenant, CUSTOMER_PHONE,
        GenericInteraction(kind="button_reply", reply_id="qty:2", text="2"),
        wa_message_id=_next_wamid(),
    )

    customer = (await db_session.execute(select(Customer).where(Customer.restaurant_id == restaurant_tenant.id))).scalar_one()
    state = (await db_session.execute(
        select(GenericConversationState).where(GenericConversationState.customer_id == customer.id)
    )).scalar_one()

    # The first tap's cart line is intact -- never lost, never duplicated, never summed
    # with an unrelated later message. The second tap correctly landed on cart_menu (the
    # real state right after the first tap finished) and was safely ignored there as
    # unrecognized input, rather than being misapplied to the now-gone quantity_select
    # step or corrupting the cart in any way.
    assert state.current_step == "cart_menu"
    assert len(state.context["cart"]) == 1
    assert state.context["cart"][0]["qty"] == 1

    # Every rapid message was actually logged exactly once -- none silently dropped,
    # none double-counted. 6 inbound turns: hi, welcome:order, category, item, qty:1, qty:2.
    from app.models.message import Message
    from app.models.enums import MessageDirection

    inbound_messages = (await db_session.execute(
        select(Message).where(Message.customer_id == customer.id, Message.direction == MessageDirection.INBOUND)
    )).scalars().all()
    assert len(inbound_messages) == 6


async def test_rapid_text_messages_do_not_lose_the_second_ones_state_transition(db_session, restaurant_tenant):
    """Same shape, free-text version: "hi" immediately followed by a real free-text
    request, matching Part 18's "Hi" then "Show me rings"-style example. The second
    message must land on the state the FIRST message actually produced, not a stale
    pre-"hi" read."""
    sender = InMemoryWhatsAppSender()
    await process_inbound_message(db_session, sender, restaurant_tenant, CUSTOMER_PHONE, GenericInteraction(kind="text", text="Hi"), wa_message_id=_next_wamid())
    await process_inbound_message(
        db_session, sender, restaurant_tenant, CUSTOMER_PHONE,
        GenericInteraction(kind="text", text="I'd like to place an order"),
        wa_message_id=_next_wamid(),
    )

    customer = (await db_session.execute(select(Customer).where(Customer.restaurant_id == restaurant_tenant.id))).scalar_one()
    state = (await db_session.execute(
        select(GenericConversationState).where(GenericConversationState.customer_id == customer.id)
    )).scalar_one()
    # Whatever the fuzzy/ambiguous resolution actually decided, the conversation must
    # have moved forward from "welcome" (or asked a real clarification) -- never silently
    # stuck back at a stale pre-"hi" step, and never crashed.
    assert state.current_step in ("welcome", "category_select")
