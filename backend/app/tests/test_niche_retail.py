"""End-to-end proof that the Retail & Fashion niche template (app/niche_seeds/retail.py,
action_type="order") drives a real conversation through the real
app/services/generic_flow_engine.py -- a straight re-skin of the proven Restaurant
order-flow template (cart + quantity + checkout + payment-link) onto apparel/footwear/
accessories catalog and copy.

Same driving pattern as app/tests/test_niche_restaurant.py: direct calls to
generic_flow_engine.process_inbound_message (the exact function
app/api/v1/routers/webhook.py's routing switch calls for any
Restaurant.uses_generic_engine=True business), inspecting the InMemoryWhatsAppSender's
`.sent` list and the GenericConversationState/Engagement/EngagementItem rows the engine
writes.
"""

import itertools

import pytest_asyncio
from sqlalchemy import select

import app.services.generic_flow_engine as generic_flow_engine
from app.core.security import encrypt_secret
from app.models.catalog import CatalogCategory, CatalogItem
from app.models.customer import Customer
from app.models.engagement import Engagement, EngagementItem
from app.models.enums import EngagementStatus, EngagementType
from app.models.generic_conversation_state import GenericConversationState
from app.models.niche_template import NicheTemplate
from app.models.restaurant import Restaurant
from app.niche_seeds.retail import TEMPLATE
from app.services.generic_flow_engine import GenericInteraction, process_inbound_message
from app.services.niche_provisioning import provision_from_template
from app.services.whatsapp_client import InMemoryWhatsAppSender, OutboundMessage

PHONE_NUMBER_ID = "RETAIL_TEST_PHONE_NUMBER_ID"
CUSTOMER_PHONE = "919876543311"
CUSTOMER_PROFILE_NAME = "Ananya Kapoor"

_wamid_counter = itertools.count(1)


def _next_wamid() -> str:
    return f"wamid.retail.test.{next(_wamid_counter)}"


# --- fixtures -----------------------------------------------------------------------------


@pytest_asyncio.fixture
async def sender():
    return InMemoryWhatsAppSender()


@pytest_asyncio.fixture
async def retail_tenant(db_session):
    restaurant = Restaurant(
        name="Urban Threads Boutique",
        slug="urban-threads-boutique",
        whatsapp_phone_number_id=PHONE_NUMBER_ID,
        whatsapp_access_token_encrypted=encrypt_secret("fake-access-token"),
        staff_notification_number="919876500003",
    )
    db_session.add(restaurant)
    await db_session.flush()

    template = NicheTemplate(
        code=TEMPLATE["code"],
        name=TEMPLATE["name"],
        action_type=EngagementType(TEMPLATE["action_type"]),
        icon=TEMPLATE["icon"],
        welcome_message=TEMPLATE["welcome_message"],
        welcome_banner_image=TEMPLATE["welcome_banner_image"],
        welcome_buttons=TEMPLATE["welcome_buttons"],
        default_catalog=TEMPLATE["default_catalog"],
        default_flow_steps=TEMPLATE["default_flow_steps"],
        terminology=TEMPLATE["terminology"],
        default_modules=TEMPLATE["default_modules"],
    )
    db_session.add(template)
    await db_session.flush()

    await provision_from_template(db_session, restaurant, template)
    await db_session.commit()

    return restaurant


# --- small driving/inspection helpers ------------------------------------------------------


async def _send_text(session, sender, restaurant, phone, text, profile_name=None):
    await process_inbound_message(
        session, sender, restaurant, phone,
        GenericInteraction(kind="text", text=text, profile_name=profile_name),
        wa_message_id=_next_wamid(),
    )


async def _tap(session, sender, restaurant, phone, reply_id):
    await process_inbound_message(
        session, sender, restaurant, phone,
        GenericInteraction(kind="button_reply", reply_id=reply_id, text=reply_id),
        wa_message_id=_next_wamid(),
    )


def _extract_options(message: OutboundMessage) -> list[dict]:
    interactive = message.payload.get("interactive", {})
    itype = interactive.get("type")
    if itype == "button":
        return [{"id": b["reply"]["id"], "title": b["reply"]["title"]} for b in interactive["action"]["buttons"]]
    if itype == "list":
        rows = interactive["action"]["sections"][0]["rows"]
        return [{"id": r["id"], "title": r["title"]} for r in rows]
    return []


def _body_text(message: OutboundMessage) -> str:
    payload = message.payload
    if payload.get("type") == "text":
        return payload["text"]["body"]
    if payload.get("type") == "image":
        return payload["image"].get("caption", "")
    interactive = payload.get("interactive", {})
    return interactive.get("body", {}).get("text", "")


def _last_interactive(sender: InMemoryWhatsAppSender) -> OutboundMessage:
    """The last button/list options message -- explicitly skips a trailing native
    location-request message (also type "interactive" but with no options of its own),
    since free_text_input steps with accepts_location send that as a second message
    right after the real button/skip/back prompt (see generic_flow_engine.py's
    _render_step: WhatsApp can't combine the two interactive types into one message)."""
    for message in reversed(sender.sent):
        if message.payload.get("type") != "interactive":
            continue
        if message.payload.get("interactive", {}).get("type") == "location_request_message":
            continue
        return message
    raise AssertionError("No interactive options message was sent")


def _last_message_to(sender: InMemoryWhatsAppSender, to: str) -> OutboundMessage:
    for message in reversed(sender.sent):
        if message.to == to:
            return message
    raise AssertionError(f"No message was sent to {to}")


async def _get_state(session, customer_id) -> GenericConversationState:
    result = await session.execute(
        select(GenericConversationState).where(GenericConversationState.customer_id == customer_id)
    )
    return result.scalar_one()


async def _get_customer(session, restaurant_id, phone=CUSTOMER_PHONE) -> Customer:
    result = await session.execute(
        select(Customer).where(Customer.restaurant_id == restaurant_id, Customer.phone == phone)
    )
    return result.scalar_one()


async def _get_category_id(session, restaurant_id, name: str) -> str:
    result = await session.execute(
        select(CatalogCategory).where(CatalogCategory.restaurant_id == restaurant_id, CatalogCategory.name == name)
    )
    return str(result.scalar_one().id)


async def _get_item(session, restaurant_id, name: str) -> CatalogItem:
    result = await session.execute(
        select(CatalogItem).where(CatalogItem.restaurant_id == restaurant_id, CatalogItem.name == name)
    )
    return result.scalar_one()


# --- button title length gotcha (WhatsApp truncates quick-reply buttons at 20 chars) -------


def test_all_catalog_item_and_button_titles_are_at_most_20_chars():
    for button in TEMPLATE["welcome_buttons"]:
        assert len(button["title"]) <= 20, button["title"]
    for category in TEMPLATE["default_catalog"]:
        assert len(category["name"]) <= 20, category["name"]
        for item in category["items"]:
            assert len(item["name"]) <= 20, item["name"]
    for step in TEMPLATE["default_flow_steps"]:
        for option in step.get("static_options", []):
            assert len(option["title"]) <= 20, option["title"]


# --- the main end-to-end proof (real engine; cart + quantity + checkout + back-nav) -----


async def test_full_order_flow_with_cart_and_back_navigation(db_session, retail_tenant, sender):
    restaurant = retail_tenant
    mens_category_id = await _get_category_id(db_session, restaurant.id, "Men's Wear")
    footwear_category_id = await _get_category_id(db_session, restaurant.id, "Footwear")
    shirt_item = await _get_item(db_session, restaurant.id, "Casual Shirt")
    sneakers_item = await _get_item(db_session, restaurant.id, "Sneakers")

    assert float(shirt_item.price) == 899
    assert float(sneakers_item.price) == 1999

    # --- 1. "Hi" -> welcome + 5 options, entry point, no Back -----------------------------
    await _send_text(db_session, sender, restaurant, CUSTOMER_PHONE, "Hi", profile_name=CUSTOMER_PROFILE_NAME)
    welcome_options = _extract_options(_last_interactive(sender))
    assert [o["id"] for o in welcome_options] == [
        "welcome:shop", "welcome:new", "welcome:offers", "welcome:store", "welcome:contact",
    ]
    customer = await _get_customer(db_session, restaurant.id)
    assert customer.name == CUSTOMER_PROFILE_NAME  # auto-pulled from the WhatsApp profile
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "welcome"

    # --- 2. "Shop Now" -> category list [Back -> Welcome] ---------------------------------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "welcome:shop")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "category_select"
    category_titles = {o["title"] for o in _extract_options(_last_interactive(sender))}
    assert {"Men's Wear", "Women's Wear", "Footwear", "Accessories"} <= category_titles

    #     Back -> Welcome, then forward again -----------------------------------------------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, generic_flow_engine.BACK_REPLY_ID)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "welcome"
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "welcome:shop")

    # --- 3. Category tapped -> item list [Back -> Category list] --------------------------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"category:{mens_category_id}")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "item_select"
    assert state.context["category_id"] == mens_category_id
    item_titles = {o["title"] for o in _extract_options(_last_interactive(sender)) if o["id"] != generic_flow_engine.BACK_REPLY_ID}
    assert item_titles == {"Casual Shirt", "Formal Trousers"}

    #     Back -> Category list, category_id survives, then forward again -------------------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, generic_flow_engine.BACK_REPLY_ID)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "category_select"
    assert state.context["category_id"] == mens_category_id
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"category:{mens_category_id}")

    # --- 4. Item tapped -> quantity buttons [Back -> item list] ---------------------------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"item:{shirt_item.id}")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "quantity_select"
    assert state.context["pending_item"]["item_id"] == str(shirt_item.id)
    qty_body = _body_text(_last_interactive(sender))
    assert "Casual Shirt" in qty_body
    qty_options = _extract_options(_last_interactive(sender))
    assert {o["id"] for o in qty_options} == {"qty:1", "qty:2", "qty:3", "qty:custom", generic_flow_engine.BACK_REPLY_ID}

    #     Back -> item list, then forward again ----------------------------------------------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, generic_flow_engine.BACK_REPLY_ID)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "item_select"
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"item:{shirt_item.id}")

    # --- 5. Quantity "2" -> added to cart -> cart menu [Back -> Category list] ------------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "qty:2")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "cart_menu"
    assert state.context["cart"] == [{"item_id": str(shirt_item.id), "name": "Casual Shirt", "price": 899.0, "qty": 2}]
    assert state.context["cart_total"] == "1798"
    cart_body = _body_text(_last_interactive(sender))
    assert "Casual Shirt" in cart_body and "1798" in cart_body

    # --- 5b. "Add More Items" -> category list again, add a second item -------------------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "cart:add_more")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "category_select"
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"category:{footwear_category_id}")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"item:{sneakers_item.id}")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "qty:1")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "cart_menu"
    assert len(state.context["cart"]) == 2
    assert state.context["cart_total"] == "3797"  # 899*2 + 1999*1

    # --- 6. "Checkout" -> delivery address (free text, Skip, or native location) ----------
    #        [Back -> Cart menu]
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "cart:checkout")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "address_capture"
    address_options = _extract_options(_last_interactive(sender))
    address_ids = {o["id"] for o in address_options}
    assert generic_flow_engine.SKIP_REPLY_ID in address_ids
    assert generic_flow_engine.BACK_REPLY_ID in address_ids
    # A native "share location" prompt is sent as a second message alongside the
    # text/button prompt (WhatsApp can't combine the two interactive types).
    location_prompt_sent = any(
        m.payload.get("type") == "interactive" and m.payload.get("interactive", {}).get("type") == "location_request_message"
        for m in sender.sent
    )
    assert location_prompt_sent

    #     Back -> cart menu, cart survives, then forward again --------------------------------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, generic_flow_engine.BACK_REPLY_ID)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "cart_menu"
    assert len(state.context["cart"]) == 2
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "cart:checkout")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "address_capture"

    # --- 6b. Address typed as free text -> order confirmation [Back -> address] -----------
    await _send_text(db_session, sender, restaurant, CUSTOMER_PHONE, "14 MG Road, Indiranagar, Bengaluru")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "order_confirm"
    assert state.context["delivery_address"] == "14 MG Road, Indiranagar, Bengaluru"
    confirm_body = _body_text(_last_interactive(sender))
    assert "Casual Shirt" in confirm_body
    assert "Sneakers" in confirm_body
    assert "3797" in confirm_body
    assert "14 MG Road, Indiranagar, Bengaluru" in confirm_body
    confirm_options = _extract_options(_last_interactive(sender))
    assert {o["id"] for o in confirm_options} == {"order:confirm", generic_flow_engine.BACK_REPLY_ID}

    #     Back -> address capture, address survives, then forward again ----------------------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, generic_flow_engine.BACK_REPLY_ID)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "address_capture"
    assert state.context["delivery_address"] == "14 MG Road, Indiranagar, Bengaluru"
    await _send_text(db_session, sender, restaurant, CUSTOMER_PHONE, "14 MG Road, Indiranagar, Bengaluru")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "order_confirm"

    # --- 7. "Place Order" -> confirmed, stock decremented, staff notified -----------------
    #        [terminal, no Back]
    engagements_before = (await db_session.execute(select(Engagement))).scalars().all()
    assert len(engagements_before) == 0

    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "order:confirm")

    state = await _get_state(db_session, customer.id)
    assert state.current_step == "order_confirmed"
    assert state.context["cart"] == []  # cart cleared after order placed

    engagements = (await db_session.execute(select(Engagement).where(Engagement.restaurant_id == restaurant.id))).scalars().all()
    assert len(engagements) == 1
    engagement = engagements[0]
    assert engagement.type == EngagementType.ORDER
    assert engagement.status == EngagementStatus.NEW
    assert engagement.customer_id == customer.id
    assert engagement.requires_payment is True  # non-empty cart
    assert float(engagement.subtotal) == 3797
    assert float(engagement.total) == 3797
    assert engagement.details["delivery_address"] == "14 MG Road, Indiranagar, Bengaluru"

    items = (await db_session.execute(select(EngagementItem).where(EngagementItem.engagement_id == engagement.id))).scalars().all()
    assert len(items) == 2
    by_name = {i.name_snapshot: i.quantity for i in items}
    assert by_name == {"Casual Shirt": 2, "Sneakers": 1}

    # Customer-facing terminal confirmation message.
    confirmed_message = _last_message_to(sender, CUSTOMER_PHONE)
    confirmed_body = _body_text(confirmed_message)
    assert "Order placed" in confirmed_body
    assert engagement.reference_number in confirmed_body
    assert "3797" in confirmed_body
    # No Razorpay keys configured for this tenant -- the confirmation must never claim a
    # payment succeeded (see app/services/payment/generic_razorpay.py's module docstring).
    assert "successful" not in confirmed_body.lower()
    assert "None" not in confirmed_body  # payment_link_url renders as empty, not "None"

    # Staff notified via notify_business() at restaurant.staff_notification_number.
    staff_message = _last_message_to(sender, restaurant.staff_notification_number)
    staff_body = _body_text(staff_message)
    assert "New order" in staff_body or "order" in staff_body.lower()
    assert engagement.reference_number in staff_body


async def test_address_skip_goes_straight_to_confirmation(db_session, retail_tenant, sender):
    """Confirms the "genuinely optional text field" affordance per the global spec rule:
    a Skip button for customers picking up in-store instead of delivery."""
    restaurant = retail_tenant
    accessories_category_id = await _get_category_id(db_session, restaurant.id, "Accessories")
    sunglasses_item = await _get_item(db_session, restaurant.id, "Sunglasses")

    await _send_text(db_session, sender, restaurant, CUSTOMER_PHONE, "hi", profile_name=CUSTOMER_PROFILE_NAME)
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "welcome:shop")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"category:{accessories_category_id}")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"item:{sunglasses_item.id}")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "qty:1")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "cart:checkout")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, generic_flow_engine.SKIP_REPLY_ID)

    customer = await _get_customer(db_session, restaurant.id)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "order_confirm"
    assert state.context["delivery_address"] is None


async def test_sold_out_item_blocks_checkout_with_friendly_message(db_session, retail_tenant, sender):
    """Atomic stock-decrement path: an item with stock_quantity=0 must block order
    creation with a customer-facing sold-out message rather than oversell (same
    guarantee the legacy engine's menu_repository.py::decrement_stock provides)."""
    restaurant = retail_tenant
    mens_category_id = await _get_category_id(db_session, restaurant.id, "Men's Wear")
    shirt_item = await _get_item(db_session, restaurant.id, "Casual Shirt")
    shirt_item.stock_quantity = 0
    await db_session.commit()

    await _send_text(db_session, sender, restaurant, CUSTOMER_PHONE, "hi", profile_name=CUSTOMER_PROFILE_NAME)
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "welcome:shop")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"category:{mens_category_id}")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"item:{shirt_item.id}")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "qty:1")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "cart:checkout")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, generic_flow_engine.SKIP_REPLY_ID)
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "order:confirm")

    engagements = (await db_session.execute(select(Engagement).where(Engagement.restaurant_id == restaurant.id))).scalars().all()
    assert len(engagements) == 0  # blocked, not created

    sold_out_message = _last_message_to(sender, CUSTOMER_PHONE)
    assert "sold out" in _body_text(sold_out_message).lower()


# --- exhaustive back-navigation: every remaining back_target edge not already covered -----
#
# The main flow test above already exercises 5 of this niche's 9 back_target edges
# (category_select->welcome, item_select->category_select, quantity_select->item_select,
# address_capture->cart_menu, order_confirm->address_capture). The remaining 4 --
# offers_info/store_info/contact_info -> welcome, and cart_menu -> category_select -- are
# covered here as standalone tests so their forward-again re-entry paths (adding cart
# items, re-entering an info step) don't disturb the main test's hard-coded totals.


async def test_back_navigation_from_info_message_steps_to_welcome(db_session, retail_tenant, sender):
    """The three "message"-type info steps reachable from the welcome menu (offers_info,
    store_info, contact_info) render with no button of their own (see
    generic_flow_engine.py::_render_step's `step["type"] in ("message",)` branch, which
    sends a bare text message and nothing else), but the reserved __back__ reply id is
    intercepted before normal dispatch regardless of whether a Back button was actually
    rendered on screen -- see the module docstring's "Back-navigation" section. Each of
    these steps' back_target must still land back on welcome, and forward re-entry must
    work again afterwards."""
    restaurant = retail_tenant
    await _send_text(db_session, sender, restaurant, CUSTOMER_PHONE, "hi", profile_name=CUSTOMER_PROFILE_NAME)
    customer = await _get_customer(db_session, restaurant.id)

    for welcome_option, info_step, expected_snippet in [
        ("welcome:offers", "offers_info", "discounts"),
        ("welcome:store", "store_info", "directions"),
        ("welcome:contact", "contact_info", "whatsapp"),
    ]:
        await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, welcome_option)
        state = await _get_state(db_session, customer.id)
        assert state.current_step == info_step
        info_message = _last_message_to(sender, CUSTOMER_PHONE)
        assert expected_snippet in _body_text(info_message).lower()

        #     Back -> Welcome, then forward again into the same info step ------------------
        await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, generic_flow_engine.BACK_REPLY_ID)
        state = await _get_state(db_session, customer.id)
        assert state.current_step == "welcome"
        await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, welcome_option)
        state = await _get_state(db_session, customer.id)
        assert state.current_step == info_step

        # Back to welcome again before the next iteration probes the next info step.
        await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, generic_flow_engine.BACK_REPLY_ID)
        state = await _get_state(db_session, customer.id)
        assert state.current_step == "welcome"


async def test_back_navigation_from_cart_menu_to_category_select(db_session, retail_tenant, sender):
    """cart_menu's back_target (distinct from its "Add More Items" button, which routes to
    the same category_select step via `routes`/`next`, not `back_target`) must also land on
    category_select with the cart preserved, and allow forward re-entry back into cart_menu
    without losing what's already in the bag."""
    restaurant = retail_tenant
    mens_category_id = await _get_category_id(db_session, restaurant.id, "Men's Wear")
    women_category_id = await _get_category_id(db_session, restaurant.id, "Women's Wear")
    shirt_item = await _get_item(db_session, restaurant.id, "Casual Shirt")
    kurti_item = await _get_item(db_session, restaurant.id, "Printed Kurti")

    await _send_text(db_session, sender, restaurant, CUSTOMER_PHONE, "hi", profile_name=CUSTOMER_PROFILE_NAME)
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "welcome:shop")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"category:{mens_category_id}")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"item:{shirt_item.id}")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "qty:1")

    customer = await _get_customer(db_session, restaurant.id)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "cart_menu"
    assert state.context["cart"] == [{"item_id": str(shirt_item.id), "name": "Casual Shirt", "price": 899.0, "qty": 1}]

    #     Back -> Category list, cart survives --------------------------------------------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, generic_flow_engine.BACK_REPLY_ID)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "category_select"
    assert state.context["cart"] == [{"item_id": str(shirt_item.id), "name": "Casual Shirt", "price": 899.0, "qty": 1}]

    #     Forward again -- add a second item, re-entering cart_menu with the bag intact ----
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"category:{women_category_id}")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"item:{kurti_item.id}")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "qty:1")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "cart_menu"
    assert len(state.context["cart"]) == 2
    assert state.context["cart_total"] == "1698"  # 899 (shirt) + 799 (kurti)
