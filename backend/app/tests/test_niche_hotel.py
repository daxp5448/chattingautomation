"""End-to-end proof that the Hotel & Guesthouse niche template (app/niche_seeds/hotel.py,
action_type="booking") actually drives a real conversation through the real
app/services/generic_flow_engine.py -- the "booking" proof niche (date-range stay priced
by nights) among the platform's 4 action-type niches.

Same driving pattern as app/tests/test_niche_salon.py and test_niche_restaurant.py: direct
calls to generic_flow_engine.process_inbound_message (the exact function
app/api/v1/routers/webhook.py's routing switch calls for any
Restaurant.uses_generic_engine=True business), inspecting the InMemoryWhatsAppSender's
`.sent` list and the GenericConversationState/Engagement/EngagementItem rows the engine
writes.

Exercises every [Back -> X] step transition in the flow (tap forward, tap Back, assert
the landed step + preserved context, tap forward again), plus the two behaviors this
niche is the first to exercise in the real engine: the "dates" data provider's
`after_context_key` exclusion (checkout options never include check-in or earlier), and
the `add_to_cart_for_date_range` action verb (nights x per-night rate pricing).
"""

import itertools
from datetime import date, timedelta

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
from app.niche_seeds.hotel import TEMPLATE
from app.services.generic_flow_engine import GenericInteraction, process_inbound_message
from app.services.niche_provisioning import provision_from_template
from app.services.whatsapp_client import InMemoryWhatsAppSender, OutboundMessage

PHONE_NUMBER_ID = "HOTEL_TEST_PHONE_NUMBER_ID"
CUSTOMER_PHONE = "919876543212"
CUSTOMER_PROFILE_NAME = "Neha Kapoor"

_wamid_counter = itertools.count(1)


def _next_wamid() -> str:
    return f"wamid.hotel.test.{next(_wamid_counter)}"


# --- fixtures -----------------------------------------------------------------------------


@pytest_asyncio.fixture
async def sender():
    return InMemoryWhatsAppSender()


@pytest_asyncio.fixture
async def hotel_tenant(db_session):
    restaurant = Restaurant(
        name="Blue Horizon Hotel",
        slug="blue-horizon-hotel",
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
    for message in reversed(sender.sent):
        if message.payload.get("type") == "interactive":
            return message
    raise AssertionError("No interactive message was sent")


def _last_image_caption(sender: InMemoryWhatsAppSender) -> str:
    for message in reversed(sender.sent):
        if message.payload.get("type") == "image":
            return message.payload["image"].get("caption", "")
    raise AssertionError("No image message was sent")


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


# --- the main end-to-end proof (real engine; date-range booking + back-nav) --------------


async def test_full_hotel_booking_flow_with_back_navigation(db_session, hotel_tenant, sender):
    restaurant = hotel_tenant
    standard_category_id = await _get_category_id(db_session, restaurant.id, "Standard Rooms")
    deluxe_category_id = await _get_category_id(db_session, restaurant.id, "Deluxe Rooms")
    twin_room = await _get_item(db_session, restaurant.id, "Standard Twin Room")
    double_room = await _get_item(db_session, restaurant.id, "Standard Double Room")
    twin_room_id = str(twin_room.id)

    assert float(twin_room.price) == 2500
    assert twin_room.attributes["max_occupancy"] == 2
    assert float(double_room.price) == 2800

    today = date.today()
    checkin_iso = today.isoformat()
    checkout_date = today + timedelta(days=3)  # 3-night stay
    checkout_iso = checkout_date.isoformat()

    # --- 1. "Hi" -> welcome + 5 options, entry point, no Back -----------------------------
    await _send_text(db_session, sender, restaurant, CUSTOMER_PHONE, "Hi", profile_name=CUSTOMER_PROFILE_NAME)
    welcome_options = _extract_options(_last_interactive(sender))
    assert [o["id"] for o in welcome_options] == [
        "welcome:book", "welcome:rooms", "welcome:offers", "welcome:location", "welcome:contact",
    ]
    customer = await _get_customer(db_session, restaurant.id)
    assert customer.name == CUSTOMER_PROFILE_NAME  # auto-pulled from the WhatsApp profile
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "welcome"

    # --- 2. "Book a Room" -> category list [Back -> Welcome] ------------------------------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "welcome:book")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "category_select"
    category_options = _extract_options(_last_interactive(sender))
    category_ids = {o["id"] for o in category_options}
    assert f"category:{standard_category_id}" in category_ids
    assert {"Standard Rooms", "Deluxe Rooms", "Suites", "Family Rooms"} <= {o["title"] for o in category_options}

    #     Back -> Welcome, then forward again -----------------------------------------------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, generic_flow_engine.BACK_REPLY_ID)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "welcome"
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "welcome:book")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "category_select"

    # --- 3. Category tapped -> room list, tap = select pending room [Back -> Category] ----
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"category:{standard_category_id}")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "room_select"
    assert state.context["category_id"] == standard_category_id
    assert state.context["category_id_label"] == "Standard Rooms"
    room_options = _extract_options(_last_interactive(sender))
    by_title = {o["title"]: o["id"] for o in room_options if o["id"] != generic_flow_engine.BACK_REPLY_ID}
    assert by_title == {"Standard Twin Room": f"item:{twin_room_id}", "Standard Double Room": f"item:{double_room.id}"}

    # Price surfaces in the preceding image caption for this step.
    caption = _last_image_caption(sender)
    assert "2500" in caption and "2800" in caption

    #     Back -> Category list, category_id survives, then forward again -------------------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, generic_flow_engine.BACK_REPLY_ID)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "category_select"
    assert state.context["category_id"] == standard_category_id  # not popped
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"category:{standard_category_id}")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "room_select"

    # --- 4. Room tapped -> pending_item captured -> check-in dates [Back -> Room list] ----
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"item:{twin_room_id}")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "checkin_select"
    assert state.context["pending_item"]["item_id"] == twin_room_id
    assert state.context["pending_item"]["name"] == "Standard Twin Room"
    assert state.context["pending_item"]["price"] == 2500.0
    checkin_body = _body_text(_last_interactive(sender))
    assert "Standard Twin Room" in checkin_body
    checkin_options = _extract_options(_last_interactive(sender))
    checkin_titles = [o["title"] for o in checkin_options]
    assert checkin_titles[0] == "Today"
    assert checkin_titles[1] == "Tomorrow"
    checkin_reply_id = f"date:{checkin_iso}"
    assert checkin_options[0]["id"] == checkin_reply_id

    #     Back -> Room list, pending_item survives, then forward again -----------------------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, generic_flow_engine.BACK_REPLY_ID)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "room_select"
    assert state.context["pending_item"]["item_id"] == twin_room_id
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"item:{twin_room_id}")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "checkin_select"

    # --- 5. Check-in tapped -> check-out dates, EXCLUDING check-in and earlier -----------
    #        [Back -> check-in dates]
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, checkin_reply_id)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "checkout_select"
    assert state.context["check_in"] == checkin_iso
    assert state.context["check_in_label"] == "Today"
    checkout_options = _extract_options(_last_interactive(sender))
    checkout_option_ids = {o["id"] for o in checkout_options if o["id"] != generic_flow_engine.BACK_REPLY_ID}
    # The after_context_key exclusion: no offered checkout date is on or before check-in.
    for opt_id in checkout_option_ids:
        offered_iso = opt_id.split(":", 1)[1]
        assert date.fromisoformat(offered_iso) > today
    assert checkin_reply_id not in checkout_option_ids
    checkout_reply_id = f"date:{checkout_iso}"
    assert checkout_reply_id in checkout_option_ids

    #     Back -> check-in dates, check_in survives, then forward again ----------------------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, generic_flow_engine.BACK_REPLY_ID)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "checkin_select"
    assert state.context["check_in"] == checkin_iso
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, checkin_reply_id)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "checkout_select"

    # --- 6. Check-out tapped -> guest count; room is added to cart HERE, priced by
    #        nights (add_to_cart_for_date_range) [Back -> check-out dates] --------------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, checkout_reply_id)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "guests_select"
    assert state.context["check_out"] == checkout_iso
    guests_options = _extract_options(_last_interactive(sender))
    guests_ids = {o["id"] for o in guests_options if o["id"] != generic_flow_engine.BACK_REPLY_ID}
    assert guests_ids == {"guests:1", "guests:2", "guests:3", "guests:4plus"}

    #     Back -> check-out dates, check_out survives, then forward again -------------------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, generic_flow_engine.BACK_REPLY_ID)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "checkout_select"
    assert state.context["check_out"] == checkout_iso
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, checkout_reply_id)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "guests_select"

    # --- 7. Guests tapped -> cart built (nights x per-night rate), name confirm ----------
    #        [Back -> guest count]
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "guests:2")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "name_confirm"
    assert state.context["guests"] == "2"
    assert state.context["guests_label"] == "2 Guests"
    assert state.context["nights"] == 3
    assert state.context["cart"] == [{"item_id": twin_room_id, "name": "Standard Twin Room", "price": 2500.0, "qty": 3}]
    assert state.context["cart_total"] == "7500"  # 3 nights x 2500
    assert "pending_item" not in state.context or state.context.get("pending_item") is None
    name_confirm_body = _body_text(_last_interactive(sender))
    assert "Please confirm the name for this booking" in name_confirm_body
    assert CUSTOMER_PROFILE_NAME in name_confirm_body

    #     Back -> guest count, guests/cart survive, then forward again -----------------------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, generic_flow_engine.BACK_REPLY_ID)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "guests_select"
    assert state.context["cart"] == [{"item_id": twin_room_id, "name": "Standard Twin Room", "price": 2500.0, "qty": 3}]
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "guests:2")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "name_confirm"
    # Cart must not have been duplicated by re-running add_to_cart_for_date_range.
    assert len(state.context["cart"]) == 1

    # --- 8. Name confirmed -> booking review card [Back -> name confirmation] -------------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "name:confirm")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "booking_confirm"
    confirm_body = _body_text(_last_interactive(sender))
    assert "Standard Twin Room" in confirm_body
    assert "Today" in confirm_body  # check_in_label
    assert "3" in confirm_body  # nights
    assert "2 Guests" in confirm_body
    assert "7500" in confirm_body
    confirm_options = _extract_options(_last_interactive(sender))
    assert {o["id"] for o in confirm_options} == {"booking:confirm", generic_flow_engine.BACK_REPLY_ID}

    #     Back -> name confirmation, then forward again --------------------------------------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, generic_flow_engine.BACK_REPLY_ID)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "name_confirm"
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "name:confirm")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "booking_confirm"

    # --- 9. Confirmed -> Engagement + EngagementItem created, staff notified -------------
    #        [terminal, no Back]
    engagements_before = (await db_session.execute(select(Engagement))).scalars().all()
    assert len(engagements_before) == 0

    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "booking:confirm")

    state = await _get_state(db_session, customer.id)
    assert state.current_step == "booking_confirmed"

    engagements = (await db_session.execute(select(Engagement).where(Engagement.restaurant_id == restaurant.id))).scalars().all()
    assert len(engagements) == 1
    engagement = engagements[0]
    assert engagement.type == EngagementType.BOOKING
    assert engagement.status == EngagementStatus.NEW
    assert engagement.customer_id == customer.id
    assert engagement.requires_payment is True  # a booking always has a cart line
    assert float(engagement.subtotal) == 7500  # nights (3) x per-night rate (2500)
    assert float(engagement.total) == 7500
    assert engagement.details["category_id"] == standard_category_id
    assert engagement.details["check_in"] == checkin_iso
    assert engagement.details["check_out"] == checkout_iso
    assert engagement.details["guests"] == "2"

    items = (await db_session.execute(select(EngagementItem).where(EngagementItem.engagement_id == engagement.id))).scalars().all()
    assert len(items) == 1
    room_item = items[0]
    assert room_item.name_snapshot == "Standard Twin Room"
    assert float(room_item.price_snapshot) == 2500
    assert room_item.quantity == 3  # == nights

    # Customer-facing terminal confirmation message -- never claims payment succeeded.
    confirmed_message = _last_message_to(sender, CUSTOMER_PHONE)
    confirmed_body = _body_text(confirmed_message)
    assert "confirmed" in confirmed_body.lower()
    assert engagement.reference_number in confirmed_body
    assert "7500" in confirmed_body
    assert "successful" not in confirmed_body.lower()
    assert "None" not in confirmed_body  # payment_link_url renders as empty, not "None"

    # Staff notified via notify_business() at restaurant.staff_notification_number.
    staff_message = _last_message_to(sender, restaurant.staff_notification_number)
    staff_body = _body_text(staff_message)
    assert "New booking" in staff_body
    assert engagement.reference_number in staff_body
    assert CUSTOMER_PROFILE_NAME in staff_body  # customer.name, read directly (not via context)
    assert checkin_iso in staff_body and checkout_iso in staff_body


async def test_name_edit_branch_captures_override_and_continues(db_session, hotel_tenant, sender):
    """The "Edit Name" side-branch off the name confirmation step: free-text capture into
    customer_name_override, with its own Back -> name_confirm, then continuing on to the
    same booking_confirm step as "Looks Good" would.
    """
    restaurant = hotel_tenant
    standard_category_id = await _get_category_id(db_session, restaurant.id, "Standard Rooms")
    twin_room = await _get_item(db_session, restaurant.id, "Standard Twin Room")

    today = date.today()
    checkin_reply_id = f"date:{today.isoformat()}"
    checkout_reply_id = f"date:{(today + timedelta(days=2)).isoformat()}"

    await _send_text(db_session, sender, restaurant, CUSTOMER_PHONE, "hello", profile_name=CUSTOMER_PROFILE_NAME)
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "welcome:book")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"category:{standard_category_id}")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"item:{twin_room.id}")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, checkin_reply_id)
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, checkout_reply_id)
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "guests:1")

    customer = await _get_customer(db_session, restaurant.id)

    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "name:edit")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "name_edit"

    # Back -> name_confirm, then re-enter edit.
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, generic_flow_engine.BACK_REPLY_ID)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "name_confirm"
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "name:edit")

    await _send_text(db_session, sender, restaurant, CUSTOMER_PHONE, "N. Kapoor")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "booking_confirm"
    assert state.context["customer_name_override"] == "N. Kapoor"


async def test_checkout_dates_exclude_a_later_check_in_and_all_earlier_dates(db_session, hotel_tenant, sender):
    """Regression-shaped proof for the after_context_key contract with a check-in that is
    NOT today -- picking a later check-in date must still push every offered check-out
    date strictly after it (not just after "today")."""
    restaurant = hotel_tenant
    standard_category_id = await _get_category_id(db_session, restaurant.id, "Standard Rooms")
    twin_room = await _get_item(db_session, restaurant.id, "Standard Twin Room")

    await _send_text(db_session, sender, restaurant, CUSTOMER_PHONE, "hi", profile_name=CUSTOMER_PROFILE_NAME)
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "welcome:book")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"category:{standard_category_id}")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"item:{twin_room.id}")

    # Pick the 3rd offered check-in date (today + 2 days) rather than "Today".
    checkin_options = _extract_options(_last_interactive(sender))
    chosen_checkin = checkin_options[2]
    chosen_checkin_iso = chosen_checkin["id"].split(":", 1)[1]
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, chosen_checkin["id"])

    checkout_options = _extract_options(_last_interactive(sender))
    checkout_option_ids = {o["id"] for o in checkout_options if o["id"] != generic_flow_engine.BACK_REPLY_ID}
    checkin_date = date.fromisoformat(chosen_checkin_iso)
    for opt_id in checkout_option_ids:
        offered_iso = opt_id.split(":", 1)[1]
        assert date.fromisoformat(offered_iso) > checkin_date

    customer = await _get_customer(db_session, restaurant.id)
    state = await _get_state(db_session, customer.id)
    assert state.context["check_in"] == chosen_checkin_iso
