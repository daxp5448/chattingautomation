"""End-to-end proof that the Salon & Spa niche template (app/niche_seeds/salon.py,
action_type="appointment") actually drives a real conversation through the real
app/services/generic_flow_engine.py -- the "appointment" proof niche (staff selection +
date + time-slot booking) among the platform's 4 action-type niches.

Drives the flow via direct calls to generic_flow_engine.process_inbound_message (same
function app/api/v1/routers/webhook.py's routing switch calls for any
Restaurant.uses_generic_engine=True business), inspecting the InMemoryWhatsAppSender's
`.sent` list and the GenericConversationState/Engagement rows the engine writes -- the
same "call the service function directly, assert on DB rows + the fake sender" pattern
app/tests/test_payment_and_order_lifecycle.py uses for the payment/order-lifecycle work.

This file previously documented 4 confirmed engine bugs (context mutations silently
dropped by a plain JSON column; category/date context values crashing on the id-prefix
that capture_key leaves on them; already-booked slots not actually excluded) plus a gap
(image captions/item descriptions omitting price and duration). All were fixed directly
in the shared engine/model:
  - app/models/generic_conversation_state.py: `context` now uses
    `MutableDict.as_mutable(JSON)`.
  - app/services/generic_flow_engine.py: capture_key now strips the data-provider's id
    prefix (`"category:<uuid>"` -> `"<uuid>"`) at capture time, so downstream
    `uuid.UUID(...)`/`date.fromisoformat(...)` calls receive bare values.
  - `_time_slot_options`'s booked-slot exclusion now matches on the same unprefixed
    value and is scoped to the specific staff member being booked.
  - `_send_options`'s image caption includes each option's description; the "items"
    data provider's description now includes duration (via `_price_label(...,
    include_attributes=True)`).
  - `_prompt_text` now threads `customer_name` (preferring an explicit
    `customer_name_override`) into every step's render context.

This file now exercises the real engine directly, with no monkeypatching or test-only
workarounds -- every assertion below is the actual, current behavior.
"""

import itertools
from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy import select

import app.services.generic_flow_engine as generic_flow_engine
from app.core.security import encrypt_secret
from app.models.catalog import CatalogCategory, CatalogItem
from app.models.customer import Customer
from app.models.engagement import Engagement
from app.models.enums import EngagementStatus, EngagementType
from app.models.generic_conversation_state import GenericConversationState
from app.models.niche_template import NicheTemplate
from app.models.restaurant import Restaurant
from app.models.staff_member import StaffMember
from app.niche_seeds.salon import TEMPLATE
from app.services.generic_flow_engine import GenericInteraction, process_inbound_message
from app.services.niche_provisioning import provision_from_template
from app.services.whatsapp_client import InMemoryWhatsAppSender, OutboundMessage

PHONE_NUMBER_ID = "SALON_TEST_PHONE_NUMBER_ID"
CUSTOMER_PHONE = "919876543210"
CUSTOMER_PROFILE_NAME = "Asha Verma"

_wamid_counter = itertools.count(1)


def _next_wamid() -> str:
    return f"wamid.salon.test.{next(_wamid_counter)}"


# --- fixtures -----------------------------------------------------------------------------


@pytest_asyncio.fixture
async def sender():
    return InMemoryWhatsAppSender()


@pytest_asyncio.fixture
async def salon_tenant(db_session):
    restaurant = Restaurant(
        name="Glow Salon & Spa",
        slug="glow-salon-spa",
        whatsapp_phone_number_id=PHONE_NUMBER_ID,
        whatsapp_access_token_encrypted=encrypt_secret("fake-access-token"),
        staff_notification_number="919876500001",
        # Redundant with template.default_modules (provision_from_template now copies it
        # onto the restaurant) but kept explicit here for clarity/robustness.
        loyalty_settings={"modules": {"staff_selection": True}},
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

    priya = StaffMember(restaurant_id=restaurant.id, name="Priya", title="Senior Stylist", active=True, working_hours={})
    ravi = StaffMember(restaurant_id=restaurant.id, name="Ravi", title="Stylist", active=True, working_hours={})
    db_session.add_all([priya, ravi])
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


async def _get_staff_id(session, restaurant_id, name: str) -> str:
    result = await session.execute(
        select(StaffMember).where(StaffMember.restaurant_id == restaurant_id, StaffMember.name == name)
    )
    return str(result.scalar_one().id)


# --- regression tests for the 4 previously-confirmed engine bugs, now fixed -------------


async def test_context_persists_across_separate_sessions(db_session, salon_tenant, sender):
    """Regression test for the fixed context-persistence bug: a category selection made
    in one process_inbound_message call must still be visible to a completely fresh
    session's read of the row afterward -- exactly the "next webhook request opens a new
    session" shape production actually has.
    """
    restaurant = salon_tenant
    haircut_category_id = await _get_category_id(db_session, restaurant.id, "Haircut & Styling")

    await _send_text(db_session, sender, restaurant, CUSTOMER_PHONE, "hi", profile_name=CUSTOMER_PROFILE_NAME)
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "welcome:book")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"category:{haircut_category_id}")

    customer = await _get_customer(db_session, restaurant.id)

    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as fresh_session:
        state = await _get_state(fresh_session, customer.id)
        assert state.current_step == "service_select"
        assert state.context["category_id"] == haircut_category_id


async def test_category_to_service_list_no_longer_crashes(db_session, salon_tenant, sender):
    """Regression test: selecting a category and landing on the service list must not
    raise -- capture_key now stores the bare uuid (no "category:" prefix), matching what
    the "items" buttons_from provider's uuid.UUID(category_id) call expects."""
    restaurant = salon_tenant
    haircut_category_id = await _get_category_id(db_session, restaurant.id, "Haircut & Styling")

    await _send_text(db_session, sender, restaurant, CUSTOMER_PHONE, "hi", profile_name=CUSTOMER_PROFILE_NAME)
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "welcome:book")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"category:{haircut_category_id}")

    customer = await _get_customer(db_session, restaurant.id)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "service_select"


async def test_time_slot_lookup_no_longer_crashes(db_session, salon_tenant, sender):
    """Regression test: selecting a date and landing on the time-slot list must not
    raise -- capture_key now stores the bare isoformat date (no "date:" prefix),
    matching what _time_slot_options's date.fromisoformat(date_key) call expects."""
    restaurant = salon_tenant
    haircut_category_id = await _get_category_id(db_session, restaurant.id, "Haircut & Styling")
    haircut_item = await _get_item(db_session, restaurant.id, "Haircut")
    priya_id = await _get_staff_id(db_session, restaurant.id, "Priya")

    await _send_text(db_session, sender, restaurant, CUSTOMER_PHONE, "hi", profile_name=CUSTOMER_PROFILE_NAME)
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "welcome:book")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"category:{haircut_category_id}")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"item:{haircut_item.id}")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"staff:{priya_id}")

    today_reply_id = f"date:{date.today().isoformat()}"
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, today_reply_id)

    customer = await _get_customer(db_session, restaurant.id)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "time_select"


async def test_already_booked_slot_is_excluded_and_staff_scoped(db_session, salon_tenant, sender):
    """Regression test: a slot already booked for a given staff member on a given date
    must be excluded from that same staff member's offered slots, but must NOT be
    excluded for a *different* staff member at the same date/time (booked-slot exclusion
    is staff-scoped, not global)."""
    restaurant = salon_tenant
    haircut_category_id = await _get_category_id(db_session, restaurant.id, "Haircut & Styling")
    haircut_item = await _get_item(db_session, restaurant.id, "Haircut")
    priya_id = await _get_staff_id(db_session, restaurant.id, "Priya")
    ravi_id = await _get_staff_id(db_session, restaurant.id, "Ravi")
    today_iso = date.today().isoformat()

    existing_customer = Customer(restaurant_id=restaurant.id, phone="919876500099", name="Earlier Customer")
    db_session.add(existing_customer)
    await db_session.flush()
    db_session.add(
        Engagement(
            restaurant_id=restaurant.id,
            customer_id=existing_customer.id,
            reference_number="GLOW-APT-000001",
            type=EngagementType.APPOINTMENT,
            status=EngagementStatus.NEW,
            details={
                "category_id": haircut_category_id,
                "item_id": str(haircut_item.id),
                "staff_id": priya_id,
                "date": today_iso,
                "time": "09:00",
            },
        )
    )
    await db_session.commit()

    # Second customer booking the SAME staff member (Priya) -> 09:00 must be excluded.
    second_phone = "919876500098"
    await _send_text(db_session, sender, restaurant, second_phone, "hi", profile_name="Second Customer")
    await _tap(db_session, sender, restaurant, second_phone, "welcome:book")
    await _tap(db_session, sender, restaurant, second_phone, f"category:{haircut_category_id}")
    await _tap(db_session, sender, restaurant, second_phone, f"item:{haircut_item.id}")
    await _tap(db_session, sender, restaurant, second_phone, f"staff:{priya_id}")
    await _tap(db_session, sender, restaurant, second_phone, f"date:{today_iso}")
    priya_time_ids = {o["id"] for o in _extract_options(_last_interactive(sender))}
    assert "time:09:00" not in priya_time_ids

    # Third customer booking a DIFFERENT staff member (Ravi) -> 09:00 must still be offered.
    third_phone = "919876500097"
    await _send_text(db_session, sender, restaurant, third_phone, "hi", profile_name="Third Customer")
    await _tap(db_session, sender, restaurant, third_phone, "welcome:book")
    await _tap(db_session, sender, restaurant, third_phone, f"category:{haircut_category_id}")
    await _tap(db_session, sender, restaurant, third_phone, f"item:{haircut_item.id}")
    await _tap(db_session, sender, restaurant, third_phone, f"staff:{ravi_id}")
    await _tap(db_session, sender, restaurant, third_phone, f"date:{today_iso}")
    ravi_time_ids = {o["id"] for o in _extract_options(_last_interactive(sender))}
    assert "time:09:00" in ravi_time_ids


# --- the main end-to-end proof (real engine, no workarounds; config verified correct) ---


async def test_full_appointment_booking_flow_with_back_navigation(db_session, salon_tenant, sender):
    restaurant = salon_tenant
    haircut_category_id = await _get_category_id(db_session, restaurant.id, "Haircut & Styling")
    haircut_item = await _get_item(db_session, restaurant.id, "Haircut")
    hairspa_item = await _get_item(db_session, restaurant.id, "Hair Spa")
    priya_id = await _get_staff_id(db_session, restaurant.id, "Priya")
    haircut_item_id = str(haircut_item.id)

    assert float(haircut_item.price) == 300
    assert haircut_item.attributes["duration_minutes"] == 30
    assert float(hairspa_item.price) == 800
    assert hairspa_item.attributes["duration_minutes"] == 45

    # --- 1. "Hi" -> welcome + 5 options, entry point, no Back -----------------------------
    await _send_text(db_session, sender, restaurant, CUSTOMER_PHONE, "Hi", profile_name=CUSTOMER_PROFILE_NAME)
    welcome_options = _extract_options(_last_interactive(sender))
    assert [o["id"] for o in welcome_options] == [
        "welcome:book", "welcome:services", "welcome:offers", "welcome:location", "welcome:contact",
    ]
    customer = await _get_customer(db_session, restaurant.id)
    assert customer.name == CUSTOMER_PROFILE_NAME  # auto-pulled from the WhatsApp profile
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "welcome"

    # --- 2. "Book Appointment" -> category list [Back -> Welcome] -------------------------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "welcome:book")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "category_select"
    category_options = _extract_options(_last_interactive(sender))
    category_ids = {o["id"] for o in category_options}
    assert f"category:{haircut_category_id}" in category_ids
    assert {"Haircut & Styling", "Facial & Skincare", "Bridal Packages", "Massage & Spa", "Nail Care", "Makeup"} <= {
        o["title"] for o in category_options
    }

    #     Back -> Welcome, then forward again -----------------------------------------------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, generic_flow_engine.BACK_REPLY_ID)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "welcome"
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "welcome:book")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "category_select"

    # --- 3. Category tapped -> service list, tap=select [Back -> Category list] -----------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"category:{haircut_category_id}")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "service_select"
    assert state.context["category_id"] == haircut_category_id
    assert state.context["category_id_label"] == "Haircut & Styling"
    service_options = _extract_options(_last_interactive(sender))
    by_title = {o["title"]: o["id"] for o in service_options if o["id"] != generic_flow_engine.BACK_REPLY_ID}
    assert by_title == {"Haircut": f"item:{haircut_item_id}", "Hair Spa": f"item:{hairspa_item.id}"}

    # Price + duration now surface in the preceding image caption for this step.
    caption = _last_image_caption(sender)
    assert "300" in caption and "30min" in caption
    assert "800" in caption and "45min" in caption

    #     Back -> Category list, category_id survives, then forward again -------------------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, generic_flow_engine.BACK_REPLY_ID)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "category_select"
    assert state.context["category_id"] == haircut_category_id  # not popped
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"category:{haircut_category_id}")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "service_select"

    # --- 4. Service tapped -> "Choose Staff" (Any Available / named), module-gated --------
    #        [Back -> Service list]
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"item:{haircut_item_id}")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "staff_select"
    assert state.context["item_id"] == haircut_item_id
    assert state.context["item_id_label"] == "Haircut"
    staff_options = _extract_options(_last_interactive(sender))
    staff_titles = {o["title"] for o in staff_options if o["id"] != generic_flow_engine.BACK_REPLY_ID}
    assert staff_titles == {"Any Available", "Priya", "Ravi"}

    #     Back -> Service list, item_id survives, then forward again ------------------------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, generic_flow_engine.BACK_REPLY_ID)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "service_select"
    assert state.context["item_id"] == haircut_item_id
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"item:{haircut_item_id}")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "staff_select"

    # --- 5. Date buttons: Today / Tomorrow / Pick a Date [Back -> staff selection] --------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"staff:{priya_id}")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "date_select"
    assert state.context["staff_id"] == priya_id
    assert state.context["staff_id_label"] == "Priya"
    date_options = _extract_options(_last_interactive(sender))
    date_titles = [o["title"] for o in date_options]
    assert date_titles[0] == "Today"
    assert date_titles[1] == "Tomorrow"
    today_iso = date.today().isoformat()
    today_reply_id = f"date:{today_iso}"
    assert date_options[0]["id"] == today_reply_id

    #     Back -> staff selection, staff_id survives, then forward again --------------------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, generic_flow_engine.BACK_REPLY_ID)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "staff_select"
    assert state.context["staff_id"] == priya_id
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"staff:{priya_id}")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "date_select"

    # --- 6. Time slot buttons from real availability [Back -> date buttons] ---------------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, today_reply_id)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "time_select"
    assert state.context["date"] == today_iso
    assert state.context["date_label"] == "Today"
    time_options = _extract_options(_last_interactive(sender))
    assert time_options[0]["id"] == "time:09:00"  # Priya's default 09:00-18:00 window, no bookings yet

    #     Back -> date buttons, date survives, then forward again ---------------------------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, generic_flow_engine.BACK_REPLY_ID)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "date_select"
    assert state.context["date"] == today_iso
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, today_reply_id)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "time_select"

    # --- 7. Name confirmation, auto-pulled + editable [Back -> time slot] -----------------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "time:09:00")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "name_confirm"
    assert state.context["time"] == "09:00"
    assert state.context["time_label"] == "09:00"
    name_confirm_body = _body_text(_last_interactive(sender))
    assert "Please confirm the name for this booking" in name_confirm_body
    # customer_name is now threaded into every step's render context.
    assert CUSTOMER_PROFILE_NAME in name_confirm_body
    name_confirm_options = _extract_options(_last_interactive(sender))
    assert {o["id"] for o in name_confirm_options if o["id"] != generic_flow_engine.BACK_REPLY_ID} == {
        "name:confirm", "name:edit",
    }

    #     Back -> time slot, time survives, then forward again ------------------------------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, generic_flow_engine.BACK_REPLY_ID)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "time_select"
    assert state.context["time"] == "09:00"
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "time:09:00")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "name_confirm"

    # --- 8. Booking confirmation card -> "Confirm Booking" [Back -> name confirmation] ----
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "name:confirm")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "booking_confirm"
    confirm_body = _body_text(_last_interactive(sender))
    assert "Haircut" in confirm_body
    assert "Priya" in confirm_body
    assert "Today" in confirm_body
    assert "09:00" in confirm_body
    confirm_options = _extract_options(_last_interactive(sender))
    assert {o["id"] for o in confirm_options} == {"booking:confirm", generic_flow_engine.BACK_REPLY_ID}

    #     Back -> name confirmation, then forward again --------------------------------------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, generic_flow_engine.BACK_REPLY_ID)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "name_confirm"
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "name:confirm")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "booking_confirm"

    # --- 9. Confirmed -> confirmation message + staff notified [terminal, no Back] --------
    engagements_before = (await db_session.execute(select(Engagement))).scalars().all()
    assert len(engagements_before) == 0

    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "booking:confirm")

    state = await _get_state(db_session, customer.id)
    assert state.current_step == "booking_confirmed"

    engagements = (await db_session.execute(select(Engagement).where(Engagement.restaurant_id == restaurant.id))).scalars().all()
    assert len(engagements) == 1
    engagement = engagements[0]
    assert engagement.type == EngagementType.APPOINTMENT
    assert engagement.status == EngagementStatus.NEW
    assert engagement.customer_id == customer.id
    assert engagement.requires_payment is False  # no cart/payment for an appointment
    assert engagement.details["category_id"] == haircut_category_id
    assert engagement.details["item_id"] == haircut_item_id
    assert engagement.details["staff_id"] == priya_id
    assert engagement.details["date"] == today_iso
    assert engagement.details["time"] == "09:00"

    # Customer-facing terminal confirmation message.
    confirmed_message = _last_message_to(sender, CUSTOMER_PHONE)
    confirmed_body = _body_text(confirmed_message)
    assert "confirmed" in confirmed_body.lower()
    assert "reminder" in confirmed_body.lower()
    assert engagement.reference_number in confirmed_body

    # Staff notified via notify_business() at restaurant.staff_notification_number.
    staff_message = _last_message_to(sender, restaurant.staff_notification_number)
    staff_body = _body_text(staff_message)
    assert "New appointment" in staff_body
    assert engagement.reference_number in staff_body
    assert CUSTOMER_PROFILE_NAME in staff_body  # customer.name, read directly (not via context)


async def test_name_edit_branch_captures_override_and_continues(db_session, salon_tenant, sender):
    """The "Edit Name" side-branch off step 7: free-text capture into
    customer_name_override, with its own Back -> name_confirm, then continuing on to the
    same booking_confirm step as "Looks Good" would.
    """
    restaurant = salon_tenant
    haircut_category_id = await _get_category_id(db_session, restaurant.id, "Haircut & Styling")
    haircut_item = await _get_item(db_session, restaurant.id, "Haircut")
    priya_id = await _get_staff_id(db_session, restaurant.id, "Priya")

    await _send_text(db_session, sender, restaurant, CUSTOMER_PHONE, "hello", profile_name=CUSTOMER_PROFILE_NAME)
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "welcome:book")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"category:{haircut_category_id}")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"item:{haircut_item.id}")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"staff:{priya_id}")
    today_reply_id = f"date:{date.today().isoformat()}"
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, today_reply_id)
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "time:09:00")

    customer = await _get_customer(db_session, restaurant.id)

    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "name:edit")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "name_edit"

    # Back -> name_confirm, then re-enter edit.
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, generic_flow_engine.BACK_REPLY_ID)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "name_confirm"
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "name:edit")

    await _send_text(db_session, sender, restaurant, CUSTOMER_PHONE, "Asha V.")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "booking_confirm"
    assert state.context["customer_name_override"] == "Asha V."
