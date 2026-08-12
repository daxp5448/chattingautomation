"""End-to-end proof that the Electronics & Mobile Store niche template
(app/niche_seeds/electronics.py, action_type="order") drives a real conversation through
the real app/services/generic_flow_engine.py -- a re-skin of the proven Restaurant
"order" niche (cart + quantity + checkout + payment-link) among the platform's
action-type niches.

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
from app.niche_seeds.electronics import TEMPLATE
from app.services.generic_flow_engine import GenericInteraction, process_inbound_message
from app.services.niche_provisioning import provision_from_template
from app.services.whatsapp_client import InMemoryWhatsAppSender, OutboundMessage

PHONE_NUMBER_ID = "ELECTRONICS_TEST_PHONE_NUMBER_ID"
CUSTOMER_PHONE = "919876543311"
CUSTOMER_PROFILE_NAME = "Aditya Rao"

_wamid_counter = itertools.count(1)


def _next_wamid() -> str:
    return f"wamid.electronics.test.{next(_wamid_counter)}"


# --- fixtures -----------------------------------------------------------------------------


@pytest_asyncio.fixture
async def sender():
    return InMemoryWhatsAppSender()


@pytest_asyncio.fixture
async def electronics_tenant(db_session):
    restaurant = Restaurant(
        name="Gadget Galaxy",
        slug="gadget-galaxy",
        whatsapp_phone_number_id=PHONE_NUMBER_ID,
        whatsapp_access_token_encrypted=encrypt_secret("fake-access-token"),
        staff_notification_number="919876500102",
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


async def _location(session, sender, restaurant, phone, lat, lng, text=None):
    await process_inbound_message(
        session, sender, restaurant, phone,
        GenericInteraction(kind="location", text=text, latitude=lat, longitude=lng),
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


# --- the main end-to-end proof (real engine; cart + quantity + checkout + back-nav) -----


async def test_full_order_flow_with_cart_and_back_navigation(db_session, electronics_tenant, sender):
    restaurant = electronics_tenant
    smartphones_category_id = await _get_category_id(db_session, restaurant.id, "Smartphones")
    accessories_category_id = await _get_category_id(db_session, restaurant.id, "Accessories")
    smartphone_x100 = await _get_item(db_session, restaurant.id, "Smartphone X100")
    earbuds = await _get_item(db_session, restaurant.id, "Wireless Earbuds")

    assert float(smartphone_x100.price) == 15999
    assert float(earbuds.price) == 1999

    # --- 1. "Hi" -> welcome + 5 options, entry point, no Back -----------------------------
    await _send_text(db_session, sender, restaurant, CUSTOMER_PHONE, "Hi", profile_name=CUSTOMER_PROFILE_NAME)
    welcome_options = _extract_options(_last_interactive(sender))
    assert [o["id"] for o in welcome_options] == [
        "welcome:shop", "welcome:catalog", "welcome:offers", "welcome:store", "welcome:contact",
    ]
    # Button titles stay under WhatsApp's 20-char quick-reply truncation limit.
    assert all(len(o["title"]) <= 20 for o in welcome_options)
    customer = await _get_customer(db_session, restaurant.id)
    assert customer.name == CUSTOMER_PROFILE_NAME  # auto-pulled from the WhatsApp profile
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "welcome"

    # --- 1b. Side-branch info leaves off welcome, each [Back -> Welcome] ------------------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "welcome:offers")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "offers_info"
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, generic_flow_engine.BACK_REPLY_ID)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "welcome"

    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "welcome:store")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "store_info"
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, generic_flow_engine.BACK_REPLY_ID)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "welcome"

    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "welcome:contact")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "contact_info"
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, generic_flow_engine.BACK_REPLY_ID)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "welcome"

    # --- 2. "Shop Now" -> category list [Back -> Welcome] ---------------------------------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "welcome:shop")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "category_select"
    category_titles = {o["title"] for o in _extract_options(_last_interactive(sender))}
    assert {"Smartphones", "Laptops", "Accessories", "Home Appliances"} <= category_titles

    #     Back -> Welcome, then forward again -----------------------------------------------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, generic_flow_engine.BACK_REPLY_ID)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "welcome"
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "welcome:shop")

    # --- 3. Category tapped -> item list [Back -> Category list] --------------------------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"category:{smartphones_category_id}")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "item_select"
    assert state.context["category_id"] == smartphones_category_id
    item_titles = {o["title"] for o in _extract_options(_last_interactive(sender)) if o["id"] != generic_flow_engine.BACK_REPLY_ID}
    assert item_titles == {"Smartphone X100", "Smartphone Lite"}

    #     Back -> Category list, category_id survives, then forward again -------------------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, generic_flow_engine.BACK_REPLY_ID)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "category_select"
    assert state.context["category_id"] == smartphones_category_id
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"category:{smartphones_category_id}")

    # --- 4. Item tapped -> quantity buttons [Back -> item list] ---------------------------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"item:{smartphone_x100.id}")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "quantity_select"
    assert state.context["pending_item"]["item_id"] == str(smartphone_x100.id)
    qty_body = _body_text(_last_interactive(sender))
    assert "Smartphone X100" in qty_body
    qty_options = _extract_options(_last_interactive(sender))
    assert {o["id"] for o in qty_options} == {"qty:1", "qty:2", "qty:3", "qty:custom", generic_flow_engine.BACK_REPLY_ID}

    #     Back -> item list, then forward again ----------------------------------------------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, generic_flow_engine.BACK_REPLY_ID)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "item_select"
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"item:{smartphone_x100.id}")

    # --- 5. Quantity "1" -> added to cart -> cart menu [Back -> Category list] ------------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "qty:1")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "cart_menu"
    assert state.context["cart"] == [{"item_id": str(smartphone_x100.id), "name": "Smartphone X100", "price": 15999.0, "qty": 1}]
    assert state.context["cart_total"] == "15999"
    cart_body = _body_text(_last_interactive(sender))
    assert "Smartphone X100" in cart_body and "15999" in cart_body

    #     cart_menu itself: Back -> category_select, cart survives -----------------------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, generic_flow_engine.BACK_REPLY_ID)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "category_select"
    assert len(state.context["cart"]) == 1  # cart not reset by navigating back

    # --- 5b. Add a second item (continuing forward from category_select reached above,
    #         same landing "cart:add_more" routes to from cart_menu) -----------------------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"category:{accessories_category_id}")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"item:{earbuds.id}")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "qty:2")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "cart_menu"
    assert len(state.context["cart"]) == 2
    assert state.context["cart_total"] == "19997"  # 15999*1 + 1999*2

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
    await _send_text(db_session, sender, restaurant, CUSTOMER_PHONE, "42 MG Road, Koramangala")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "order_confirm"
    assert state.context["delivery_address"] == "42 MG Road, Koramangala"
    confirm_body = _body_text(_last_interactive(sender))
    assert "Smartphone X100" in confirm_body
    assert "Wireless Earbuds" in confirm_body
    assert "19997" in confirm_body
    assert "42 MG Road, Koramangala" in confirm_body
    confirm_options = _extract_options(_last_interactive(sender))
    assert {o["id"] for o in confirm_options} == {"order:confirm", generic_flow_engine.BACK_REPLY_ID}

    #     Back -> address capture, address survives, then forward again ----------------------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, generic_flow_engine.BACK_REPLY_ID)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "address_capture"
    assert state.context["delivery_address"] == "42 MG Road, Koramangala"
    await _send_text(db_session, sender, restaurant, CUSTOMER_PHONE, "42 MG Road, Koramangala")
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
    assert float(engagement.subtotal) == 19997
    assert float(engagement.total) == 19997
    assert engagement.details["delivery_address"] == "42 MG Road, Koramangala"

    items = (await db_session.execute(select(EngagementItem).where(EngagementItem.engagement_id == engagement.id))).scalars().all()
    assert len(items) == 2
    by_name = {i.name_snapshot: i.quantity for i in items}
    assert by_name == {"Smartphone X100": 1, "Wireless Earbuds": 2}

    # Customer-facing terminal confirmation message.
    confirmed_message = _last_message_to(sender, CUSTOMER_PHONE)
    confirmed_body = _body_text(confirmed_message)
    assert "Order placed" in confirmed_body
    assert engagement.reference_number in confirmed_body
    assert "19997" in confirmed_body
    # No Razorpay keys configured for this tenant -- the confirmation must never claim a
    # payment succeeded (see app/services/payment/generic_razorpay.py's module docstring).
    assert "successful" not in confirmed_body.lower()
    assert "None" not in confirmed_body  # payment_link_url renders as empty, not "None"

    # Staff notified via notify_business() at restaurant.staff_notification_number.
    staff_message = _last_message_to(sender, restaurant.staff_notification_number)
    staff_body = _body_text(staff_message)
    assert "New order" in staff_body or "order" in staff_body.lower()
    assert engagement.reference_number in staff_body


async def test_address_skip_and_native_location_share(db_session, electronics_tenant, sender):
    """Confirms the two "genuinely optional text field" affordances per the global spec
    rule: a Skip button, and a real native WhatsApp location share (handled by the
    `accepts_location` branch of _process_input, distinct from free-text)."""
    restaurant = electronics_tenant
    smartphones_category_id = await _get_category_id(db_session, restaurant.id, "Smartphones")
    smartphone_x100 = await _get_item(db_session, restaurant.id, "Smartphone X100")

    # --- Skip path ---
    await _send_text(db_session, sender, restaurant, CUSTOMER_PHONE, "hi", profile_name=CUSTOMER_PROFILE_NAME)
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "welcome:shop")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"category:{smartphones_category_id}")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"item:{smartphone_x100.id}")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "qty:1")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "cart:checkout")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, generic_flow_engine.SKIP_REPLY_ID)

    customer = await _get_customer(db_session, restaurant.id)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "order_confirm"
    assert state.context["delivery_address"] is None

    # --- Native location-share path (second customer) ---
    second_phone = "919876500197"
    await _send_text(db_session, sender, restaurant, second_phone, "hi", profile_name="Second Customer")
    await _tap(db_session, sender, restaurant, second_phone, "welcome:shop")
    await _tap(db_session, sender, restaurant, second_phone, f"category:{smartphones_category_id}")
    await _tap(db_session, sender, restaurant, second_phone, f"item:{smartphone_x100.id}")
    await _tap(db_session, sender, restaurant, second_phone, "qty:1")
    await _tap(db_session, sender, restaurant, second_phone, "cart:checkout")
    await _location(db_session, sender, restaurant, second_phone, 12.9352, 77.6245, text="Koramangala Office")

    second_customer = await _get_customer(db_session, restaurant.id, phone=second_phone)
    second_state = await _get_state(db_session, second_customer.id)
    assert second_state.current_step == "order_confirm"
    assert second_state.context["delivery_address"] == "Koramangala Office"
    assert second_state.context["delivery_address_coords"] == {"lat": 12.9352, "lng": 77.6245}


async def test_sold_out_item_blocks_checkout_with_friendly_message(db_session, electronics_tenant, sender):
    """Atomic stock-decrement path: an item with stock_quantity=0 must block order
    creation with a customer-facing sold-out message rather than oversell (same
    guarantee the legacy engine's menu_repository.py::decrement_stock provides)."""
    restaurant = electronics_tenant
    smartphones_category_id = await _get_category_id(db_session, restaurant.id, "Smartphones")
    smartphone_x100 = await _get_item(db_session, restaurant.id, "Smartphone X100")
    smartphone_x100.stock_quantity = 0
    await db_session.commit()

    await _send_text(db_session, sender, restaurant, CUSTOMER_PHONE, "hi", profile_name=CUSTOMER_PROFILE_NAME)
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "welcome:shop")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"category:{smartphones_category_id}")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"item:{smartphone_x100.id}")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "qty:1")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "cart:checkout")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, generic_flow_engine.SKIP_REPLY_ID)
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "order:confirm")

    engagements = (await db_session.execute(select(Engagement).where(Engagement.restaurant_id == restaurant.id))).scalars().all()
    assert len(engagements) == 0  # blocked, not created

    customer = await _get_customer(db_session, restaurant.id)
    sold_out_message = _last_message_to(sender, CUSTOMER_PHONE)
    assert "sold out" in _body_text(sold_out_message).lower()
