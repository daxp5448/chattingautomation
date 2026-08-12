"""End-to-end proof that the Clinic & Healthcare niche template
(app/niche_seeds/clinic.py, action_type="appointment") actually drives a real
conversation through the real app/services/generic_flow_engine.py. This is a re-skin of
the proven Salon & Spa pattern (app/tests/test_niche_salon.py) -- doctors instead of
stylists, consultations instead of services -- exercising the same
`action_type="appointment"` booking chain (staff selection + date + time-slot booking)
through the identical shared engine.

Drives the flow via direct calls to generic_flow_engine.process_inbound_message (same
function app/api/v1/routers/webhook.py's routing switch calls for any
Restaurant.uses_generic_engine=True business), inspecting the InMemoryWhatsAppSender's
`.sent` list and the GenericConversationState/Engagement rows the engine writes.

Scope: the full happy path from "Hi" through a confirmed appointment (category -> doctor
consultation -> staff -> date -> time -> name confirm -> booking confirm -> confirmed,
staff notified), PLUS an exhaustive Back-navigation check on every one of this niche's 11
back_target edges (matching the rigor of the 4 proof niches' own dedicated back-nav
coverage, e.g. test_niche_salon.py and test_niche_real_estate.py): each edge gets a
tap-forward -> tap-Back -> assert-landed-on-correct-step-with-prior-context-preserved ->
tap-forward-again sequence. The 3 simple side-branch message steps (offers_info,
location_info, contact_info -> welcome) get their own dedicated test, mirroring
test_niche_real_estate.py's test_side_branch_messages_return_to_welcome.
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
from app.niche_seeds.clinic import TEMPLATE
from app.services.generic_flow_engine import GenericInteraction, process_inbound_message
from app.services.niche_provisioning import provision_from_template
from app.services.whatsapp_client import InMemoryWhatsAppSender, OutboundMessage

PHONE_NUMBER_ID = "CLINIC_TEST_PHONE_NUMBER_ID"
CUSTOMER_PHONE = "919876543211"
CUSTOMER_PROFILE_NAME = "Rahul Mehta"

_wamid_counter = itertools.count(1)


def _next_wamid() -> str:
    return f"wamid.clinic.test.{next(_wamid_counter)}"


# --- fixtures -----------------------------------------------------------------------------


@pytest_asyncio.fixture
async def sender():
    return InMemoryWhatsAppSender()


@pytest_asyncio.fixture
async def clinic_tenant(db_session):
    restaurant = Restaurant(
        name="Wellness Clinic & Healthcare",
        slug="wellness-clinic",
        whatsapp_phone_number_id=PHONE_NUMBER_ID,
        whatsapp_access_token_encrypted=encrypt_secret("fake-access-token"),
        staff_notification_number="919876500002",
        # provision_from_template doesn't itself copy NicheTemplate.default_modules onto
        # the restaurant (documented gap, mirrors salon's test) -- set directly so the
        # staff_selection module-gated step renders, per spec.
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

    dr_asha = StaffMember(restaurant_id=restaurant.id, name="Dr. Asha", title="General Physician", active=True, working_hours={})
    dr_kumar = StaffMember(restaurant_id=restaurant.id, name="Dr. Kumar", title="Dentist", active=True, working_hours={})
    db_session.add_all([dr_asha, dr_kumar])
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


def _last_text_message(sender: InMemoryWhatsAppSender) -> OutboundMessage:
    for message in reversed(sender.sent):
        if message.payload.get("type") == "text":
            return message
    raise AssertionError("No text message was sent")


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


# --- the main end-to-end proof ------------------------------------------------------------


async def test_full_appointment_booking_flow_with_back_navigation(db_session, clinic_tenant, sender):
    restaurant = clinic_tenant
    dental_category_id = await _get_category_id(db_session, restaurant.id, "Dental")
    dental_checkup_item = await _get_item(db_session, restaurant.id, "Dental Checkup")
    teeth_cleaning_item = await _get_item(db_session, restaurant.id, "Teeth Cleaning")
    dr_kumar_id = await _get_staff_id(db_session, restaurant.id, "Dr. Kumar")
    dental_checkup_item_id = str(dental_checkup_item.id)

    assert float(dental_checkup_item.price) == 800
    assert dental_checkup_item.attributes["duration_minutes"] == 30
    assert float(teeth_cleaning_item.price) == 1200
    assert teeth_cleaning_item.attributes["duration_minutes"] == 45

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
    assert f"category:{dental_category_id}" in category_ids
    assert {"General Physician", "Dental", "Dermatology", "Gynecology", "Eye Care"} <= {
        o["title"] for o in category_options
    }

    #     Back -> Welcome, then forward again (representative Back check #1) ----------------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, generic_flow_engine.BACK_REPLY_ID)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "welcome"
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "welcome:book")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "category_select"

    # --- 3. Category tapped -> consultation list, tap=select [Back -> Category list] ------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"category:{dental_category_id}")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "service_select"
    assert state.context["category_id"] == dental_category_id
    assert state.context["category_id_label"] == "Dental"
    service_options = _extract_options(_last_interactive(sender))
    by_title = {o["title"]: o["id"] for o in service_options if o["id"] != generic_flow_engine.BACK_REPLY_ID}
    assert by_title == {
        "Dental Checkup": f"item:{dental_checkup_item_id}",
        "Teeth Cleaning": f"item:{teeth_cleaning_item.id}",
    }

    # Price + duration surface in the preceding image caption for this step.
    caption = _last_image_caption(sender)
    assert "800" in caption and "30min" in caption
    assert "1200" in caption and "45min" in caption

    #     Back -> Category list, category_id survives, then forward again (Back edge #2) ---
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, generic_flow_engine.BACK_REPLY_ID)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "category_select"
    assert state.context["category_id"] == dental_category_id  # not popped
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"category:{dental_category_id}")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "service_select"

    # --- 4. Consultation tapped -> "Choose Doctor", module-gated [Back -> Consult list] ---
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"item:{dental_checkup_item_id}")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "staff_select"
    assert state.context["item_id"] == dental_checkup_item_id
    assert state.context["item_id_label"] == "Dental Checkup"
    staff_options = _extract_options(_last_interactive(sender))
    staff_titles = {o["title"] for o in staff_options if o["id"] != generic_flow_engine.BACK_REPLY_ID}
    assert staff_titles == {"Any Available", "Dr. Asha", "Dr. Kumar"}

    #     Back -> Consultation list, item_id survives, then forward again (Back edge #3) ----
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, generic_flow_engine.BACK_REPLY_ID)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "service_select"
    assert state.context["item_id"] == dental_checkup_item_id
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"item:{dental_checkup_item_id}")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "staff_select"

    # --- 5. Date buttons: Today / Tomorrow / Pick a Date [Back -> doctor selection] -------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"staff:{dr_kumar_id}")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "date_select"
    assert state.context["staff_id"] == dr_kumar_id
    assert state.context["staff_id_label"] == "Dr. Kumar"
    date_options = _extract_options(_last_interactive(sender))
    date_titles = [o["title"] for o in date_options]
    assert date_titles[0] == "Today"
    assert date_titles[1] == "Tomorrow"
    today_iso = date.today().isoformat()
    today_reply_id = f"date:{today_iso}"
    assert date_options[0]["id"] == today_reply_id

    #     Back -> doctor selection, staff_id survives, then forward again (Back edge #4) ----
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, generic_flow_engine.BACK_REPLY_ID)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "staff_select"
    assert state.context["staff_id"] == dr_kumar_id
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"staff:{dr_kumar_id}")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "date_select"

    # --- 6. Time slot buttons from real availability [Back -> date buttons] --------------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, today_reply_id)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "time_select"
    assert state.context["date"] == today_iso
    assert state.context["date_label"] == "Today"
    time_options = _extract_options(_last_interactive(sender))
    assert time_options[0]["id"] == "time:09:00"  # default 09:00-18:00 window, no bookings yet

    #     Back -> date buttons, date survives, then forward again (Back edge #5) -----------
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
    name_confirm_body = _body_text(_last_interactive(sender))
    assert "Please confirm the name for this booking" in name_confirm_body
    assert CUSTOMER_PROFILE_NAME in name_confirm_body
    name_confirm_options = _extract_options(_last_interactive(sender))
    assert {o["id"] for o in name_confirm_options if o["id"] != generic_flow_engine.BACK_REPLY_ID} == {
        "name:confirm", "name:edit",
    }

    #     Back -> time slot, time survives, then forward again (Back edge #6) -------------
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
    assert "Dental Checkup" in confirm_body
    assert "Dr. Kumar" in confirm_body
    assert "Today" in confirm_body
    assert "09:00" in confirm_body
    confirm_options = _extract_options(_last_interactive(sender))
    assert {o["id"] for o in confirm_options} == {"booking:confirm", generic_flow_engine.BACK_REPLY_ID}

    #     Back -> name confirmation, then forward again (Back edge #7 -- last of 7 booking-\
    #     chain edges tested in this flow; 4 more are covered by
    #     test_side_branch_messages_return_to_welcome and
    #     test_name_edit_branch_captures_override_and_continues below) ---------------------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, generic_flow_engine.BACK_REPLY_ID)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "name_confirm"
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "name:confirm")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "booking_confirm"

    # --- 9. Confirmed -> confirmation message + doctor notified [terminal, no Back] -------
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
    assert engagement.details["category_id"] == dental_category_id
    assert engagement.details["item_id"] == dental_checkup_item_id
    assert engagement.details["staff_id"] == dr_kumar_id
    assert engagement.details["date"] == today_iso
    assert engagement.details["time"] == "09:00"

    # Customer-facing terminal confirmation message.
    confirmed_message = _last_message_to(sender, CUSTOMER_PHONE)
    confirmed_body = _body_text(confirmed_message)
    assert "confirmed" in confirmed_body.lower()
    assert "reminder" in confirmed_body.lower()
    assert engagement.reference_number in confirmed_body

    # Staff (front desk) notified via notify_business() at restaurant.staff_notification_number.
    staff_message = _last_message_to(sender, restaurant.staff_notification_number)
    staff_body = _body_text(staff_message)
    assert "New appointment" in staff_body
    assert engagement.reference_number in staff_body
    assert CUSTOMER_PROFILE_NAME in staff_body  # customer.name, read directly (not via context)


async def test_name_edit_branch_captures_override_and_continues(db_session, clinic_tenant, sender):
    """The "Edit Name" side-branch off step 7: free-text capture into
    customer_name_override, with its own Back -> name_confirm, then continuing on to the
    same booking_confirm step as "Looks Good" would.
    """
    restaurant = clinic_tenant
    eye_category_id = await _get_category_id(db_session, restaurant.id, "Eye Care")
    eye_checkup_item = await _get_item(db_session, restaurant.id, "Eye Checkup")
    dr_asha_id = await _get_staff_id(db_session, restaurant.id, "Dr. Asha")

    await _send_text(db_session, sender, restaurant, CUSTOMER_PHONE, "hello", profile_name=CUSTOMER_PROFILE_NAME)
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "welcome:book")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"category:{eye_category_id}")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"item:{eye_checkup_item.id}")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"staff:{dr_asha_id}")
    today_reply_id = f"date:{date.today().isoformat()}"
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, today_reply_id)
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "time:09:00")

    customer = await _get_customer(db_session, restaurant.id)

    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "name:edit")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "name_edit"

    #     Back -> name_confirm (Back edge #8), then re-enter edit ---------------------------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, generic_flow_engine.BACK_REPLY_ID)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "name_confirm"
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "name:edit")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "name_edit"

    await _send_text(db_session, sender, restaurant, CUSTOMER_PHONE, "R. Mehta")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "booking_confirm"
    assert state.context["customer_name_override"] == "R. Mehta"


async def test_side_branch_messages_return_to_welcome(db_session, clinic_tenant, sender):
    """The three "message"-type info steps reachable from the welcome menu (offers_info,
    location_info, contact_info) [Back edges #9, #10, #11 -- the last 3 of the 11 total
    back_target edges in this niche's flow] must each land back on welcome, with forward
    re-entry working again afterwards."""
    restaurant = clinic_tenant
    await _send_text(db_session, sender, restaurant, CUSTOMER_PHONE, "hi", profile_name=CUSTOMER_PROFILE_NAME)
    customer = await _get_customer(db_session, restaurant.id)

    for welcome_option, info_step in [
        ("welcome:offers", "offers_info"),
        ("welcome:location", "location_info"),
        ("welcome:contact", "contact_info"),
    ]:
        await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, welcome_option)
        state = await _get_state(db_session, customer.id)
        assert state.current_step == info_step

        await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, generic_flow_engine.BACK_REPLY_ID)
        state = await _get_state(db_session, customer.id)
        assert state.current_step == "welcome"

        await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, welcome_option)
        state = await _get_state(db_session, customer.id)
        assert state.current_step == info_step

        await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, generic_flow_engine.BACK_REPLY_ID)
        state = await _get_state(db_session, customer.id)
        assert state.current_step == "welcome"
