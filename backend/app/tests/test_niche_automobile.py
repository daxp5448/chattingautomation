"""End-to-end proof that the Automobile Service & Showroom niche template
(app/niche_seeds/automobile.py, action_type="appointment") actually drives a real
conversation through the real app/services/generic_flow_engine.py.

Drives the flow via direct calls to generic_flow_engine.process_inbound_message (same
function app/api/v1/routers/webhook.py's routing switch calls for any
Restaurant.uses_generic_engine=True business), inspecting the InMemoryWhatsAppSender's
`.sent` list and the GenericConversationState/Engagement rows the engine writes -- the
same pattern app/tests/test_niche_salon.py uses for the salon "appointment" proof niche
this file is modeled on.

## The staff_selection-off default -- a real provisioning-layer gap, documented here rather
## than "fixed" (this file must not, and does not, touch generic_flow_engine.py or
## niche_provisioning.py)

This niche's whole reason for existing (besides being a real niche) is to be the first
niche whose `default_modules` sets `staff_selection: False` (every other appointment
niche built so far -- salon, clinic, gym -- defaults it True), exercising the
`staff_select` step's `skip_if_module_off="staff_selection"` branch in
`_Engine._advance` for real, not just by code-reading.

Tracing that branch (`if module_flag and not (restaurant.loyalty_settings or
{}).get("modules", {}).get(module_flag, True): skip`) against
`app/services/niche_provisioning.py::provision_from_template` turns up a real gap:
provisioning never copies `NicheTemplate.default_modules` onto the new business's
`Restaurant.loyalty_settings` at all (app/tests/test_niche_salon.py's fixture already
flags the mirror-image of this same gap -- salon needs `staff_selection: True` forced
onto `loyalty_settings` directly because leaving it unset would still happen to render
correctly there, since the engine's own fallback for an *unset* module flag is True).
For automobile, an unset `loyalty_settings` module flag means `staff_selection` reads as
**True** (module ON, step NOT skipped) -- the exact opposite of what this niche's
`default_modules` says. So, same as salon's fixture, the test restaurant below sets
`loyalty_settings={"modules": {"staff_selection": False}}` explicitly to reflect this
niche's *intended* runtime default -- proving the skip branch itself works correctly,
while the fact that a truly out-of-the-box provisioned business currently would NOT get
that default automatically is a provisioning-layer gap out of this file's scope to fix.
`test_staff_selection_module_when_explicitly_enabled_still_works` below flips the module
back on (the reverse scenario, matching how every other appointment niche's business
would actually be provisioned today) and proves the staff_select step itself still works
correctly when it does render.
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
from app.niche_seeds.automobile import TEMPLATE
from app.services.generic_flow_engine import GenericInteraction, process_inbound_message
from app.services.niche_provisioning import provision_from_template
from app.services.whatsapp_client import InMemoryWhatsAppSender, OutboundMessage

PHONE_NUMBER_ID = "AUTOMOBILE_TEST_PHONE_NUMBER_ID"
CUSTOMER_PHONE = "919876543211"
CUSTOMER_PROFILE_NAME = "Rahul Mehta"

_wamid_counter = itertools.count(1)


def _next_wamid() -> str:
    return f"wamid.automobile.test.{next(_wamid_counter)}"


# --- fixtures -----------------------------------------------------------------------------


@pytest_asyncio.fixture
async def sender():
    return InMemoryWhatsAppSender()


async def _make_template(db_session) -> NicheTemplate:
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
    return template


@pytest_asyncio.fixture
async def automobile_tenant(db_session):
    """The main-scenario tenant: staff_selection explicitly OFF, matching this niche's
    intended default (see module docstring for why this must be set explicitly rather
    than left unset)."""
    restaurant = Restaurant(
        name="Turbo Motors Service Center",
        slug="turbo-motors-service",
        whatsapp_phone_number_id=PHONE_NUMBER_ID,
        whatsapp_access_token_encrypted=encrypt_secret("fake-access-token"),
        staff_notification_number="919876500002",
        loyalty_settings={"modules": {"staff_selection": False}},
    )
    db_session.add(restaurant)
    await db_session.flush()

    template = await _make_template(db_session)
    await provision_from_template(db_session, restaurant, template)

    # A business could turn staff_selection on later, so seed a couple of Service
    # Advisors even though the main scenario never routes through staff_select.
    ramesh = StaffMember(restaurant_id=restaurant.id, name="Ramesh", title="Senior Service Advisor", active=True, working_hours={})
    vikram = StaffMember(restaurant_id=restaurant.id, name="Vikram", title="Service Advisor", active=True, working_hours={})
    db_session.add_all([ramesh, vikram])
    await db_session.commit()

    return restaurant


@pytest_asyncio.fixture
async def automobile_tenant_staff_on(db_session):
    """Reverse-scenario tenant: staff_selection explicitly ON, proving the staff_select
    step itself still functions correctly when a business does turn the module on."""
    restaurant = Restaurant(
        name="Deluxe Auto Works",
        slug="deluxe-auto-works",
        whatsapp_phone_number_id="AUTOMOBILE_TEST_PHONE_NUMBER_ID_2",
        whatsapp_access_token_encrypted=encrypt_secret("fake-access-token"),
        staff_notification_number="919876500003",
        loyalty_settings={"modules": {"staff_selection": True}},
    )
    db_session.add(restaurant)
    await db_session.flush()

    template = await _make_template(db_session)
    await provision_from_template(db_session, restaurant, template)

    ramesh = StaffMember(restaurant_id=restaurant.id, name="Ramesh", title="Senior Service Advisor", active=True, working_hours={})
    db_session.add(ramesh)
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


async def _get_item(session, restaurant_id, name: str, category_name: str | None = None) -> CatalogItem:
    stmt = select(CatalogItem).where(CatalogItem.restaurant_id == restaurant_id, CatalogItem.name == name)
    if category_name is not None:
        category_id = await _get_category_id(session, restaurant_id, category_name)
        stmt = stmt.where(CatalogItem.category_id == category_id)
    result = await session.execute(stmt)
    return result.scalars().first()


async def _get_staff_id(session, restaurant_id, name: str) -> str:
    result = await session.execute(
        select(StaffMember).where(StaffMember.restaurant_id == restaurant_id, StaffMember.name == name)
    )
    return str(result.scalar_one().id)


# --- the main end-to-end proof: full happy path with staff_selection OFF ------------------


async def test_full_appointment_booking_flow_with_back_navigation_staff_selection_off(db_session, automobile_tenant, sender):
    restaurant = automobile_tenant
    car_service_category_id = await _get_category_id(db_session, restaurant.id, "Car Service")
    general_service_item = await _get_item(db_session, restaurant.id, "General Service", "Car Service")
    oil_change_item = await _get_item(db_session, restaurant.id, "Oil Change", "Car Service")
    general_service_item_id = str(general_service_item.id)

    assert float(general_service_item.price) == 1500
    assert general_service_item.attributes["duration_minutes"] == 90
    assert float(oil_change_item.price) == 800
    assert oil_change_item.attributes["duration_minutes"] == 30

    # --- 1. "Hi" -> welcome + 5 options, entry point, no Back -----------------------------
    await _send_text(db_session, sender, restaurant, CUSTOMER_PHONE, "Hi", profile_name=CUSTOMER_PROFILE_NAME)
    welcome_options = _extract_options(_last_interactive(sender))
    assert [o["id"] for o in welcome_options] == [
        "welcome:book", "welcome:testdrive", "welcome:offers", "welcome:showroom", "welcome:contact",
    ]
    customer = await _get_customer(db_session, restaurant.id)
    assert customer.name == CUSTOMER_PROFILE_NAME  # auto-pulled from the WhatsApp profile
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "welcome"

    # --- 2. "Book Service" -> category list [Back -> Welcome] ------------------------------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "welcome:book")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "category_select"
    category_options = _extract_options(_last_interactive(sender))
    category_ids = {o["id"] for o in category_options}
    assert f"category:{car_service_category_id}" in category_ids
    assert {"Car Service", "Bike Service", "Test Drive", "Car Wash"} <= {o["title"] for o in category_options}

    #     Back-nav check 1: Back -> Welcome, then forward again --------------------------------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, generic_flow_engine.BACK_REPLY_ID)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "welcome"
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "welcome:book")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "category_select"

    # --- 3. Category tapped -> service list, tap=select [Back -> Category list] -----------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"category:{car_service_category_id}")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "service_select"
    assert state.context["category_id"] == car_service_category_id
    assert state.context["category_id_label"] == "Car Service"
    service_options = _extract_options(_last_interactive(sender))
    by_title = {o["title"]: o["id"] for o in service_options if o["id"] != generic_flow_engine.BACK_REPLY_ID}
    assert by_title == {
        "General Service": f"item:{general_service_item_id}",
        "Oil Change": f"item:{oil_change_item.id}",
    }

    # Price + duration surface in the preceding image caption for this step.
    caption = _last_image_caption(sender)
    assert "1500" in caption and "1h" in caption and "30min" in caption
    assert "800" in caption

    #     Back-nav check 2: Back -> Category list, category_id survives, then forward again ---
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, generic_flow_engine.BACK_REPLY_ID)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "category_select"
    assert state.context["category_id"] == car_service_category_id  # not popped
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"category:{car_service_category_id}")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "service_select"

    # --- 4. Service tapped -> staff_selection is OFF for this business, so the engine
    #        must auto-skip staff_select entirely and land straight on date_select. This
    #        is the specific behavior this niche exists to exercise. ---------------------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"item:{general_service_item_id}")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "date_select"  # never staff_select
    assert state.current_step != "staff_select"
    assert "staff_id" not in state.context
    assert "staff_id_label" not in state.context
    assert state.context["item_id"] == general_service_item_id
    assert state.context["item_id_label"] == "General Service"
    date_options = _extract_options(_last_interactive(sender))
    date_titles = [o["title"] for o in date_options]
    assert date_titles[0] == "Today"
    assert date_titles[1] == "Tomorrow"
    today_iso = date.today().isoformat()
    today_reply_id = f"date:{today_iso}"
    assert date_options[0]["id"] == today_reply_id

    # --- 5. Time slot buttons, no staff selected -> falls back to the default
    #        09:00-18:00 window (no staff_id in context at all). [Back -> date buttons] --
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, today_reply_id)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "time_select"
    assert "staff_id" not in state.context
    assert state.context["date"] == today_iso
    assert state.context["date_label"] == "Today"
    time_options = _extract_options(_last_interactive(sender))
    assert time_options[0]["id"] == "time:09:00"  # default window, no bookings yet

    #     Back-nav check 3: Back -> date buttons, date survives, then forward again -----------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, generic_flow_engine.BACK_REPLY_ID)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "date_select"
    assert state.context["date"] == today_iso
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, today_reply_id)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "time_select"

    # --- 6. Name confirmation, auto-pulled + editable [Back -> time slot] -----------------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "time:09:00")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "name_confirm"
    assert "staff_id" not in state.context
    assert state.context["time"] == "09:00"
    assert state.context["time_label"] == "09:00"
    name_confirm_body = _body_text(_last_interactive(sender))
    assert "Please confirm the name for this booking" in name_confirm_body
    assert CUSTOMER_PROFILE_NAME in name_confirm_body
    name_confirm_options = _extract_options(_last_interactive(sender))
    assert {o["id"] for o in name_confirm_options if o["id"] != generic_flow_engine.BACK_REPLY_ID} == {
        "name:confirm", "name:edit",
    }

    #     Back-nav check 4: Back -> time slot, time survives, then forward again --------------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, generic_flow_engine.BACK_REPLY_ID)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "time_select"
    assert state.context["time"] == "09:00"
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "time:09:00")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "name_confirm"

    # --- 7. Booking confirmation card -> "Confirm Booking" [Back -> name confirmation] ----
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "name:confirm")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "booking_confirm"
    confirm_body = _body_text(_last_interactive(sender))
    assert "General Service" in confirm_body
    assert "Today" in confirm_body
    assert "09:00" in confirm_body
    confirm_options = _extract_options(_last_interactive(sender))
    assert {o["id"] for o in confirm_options} == {"booking:confirm", generic_flow_engine.BACK_REPLY_ID}

    #     Back-nav check 5: Back -> name confirmation, then forward again ----------------------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, generic_flow_engine.BACK_REPLY_ID)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "name_confirm"
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "name:confirm")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "booking_confirm"

    # --- 8. Confirmed -> confirmation message + staff notified [terminal, no Back] --------
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
    assert engagement.details["category_id"] == car_service_category_id
    assert engagement.details["item_id"] == general_service_item_id
    assert "staff_id" not in engagement.details  # never captured -- module was off throughout
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


async def test_name_edit_branch_captures_override_and_continues(db_session, automobile_tenant, sender):
    """The "Edit Name" side-branch off the name_confirm step: free-text capture into
    customer_name_override, with its own Back -> name_confirm, then continuing on to the
    same booking_confirm step as "Looks Good" would -- all still with staff_selection off
    (no staff_id ever appears in context)."""
    restaurant = automobile_tenant
    bike_category_id = await _get_category_id(db_session, restaurant.id, "Bike Service")
    bike_item = await _get_item(db_session, restaurant.id, "Bike Service", "Bike Service")

    await _send_text(db_session, sender, restaurant, CUSTOMER_PHONE, "hello", profile_name=CUSTOMER_PROFILE_NAME)
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "welcome:book")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"category:{bike_category_id}")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"item:{bike_item.id}")

    customer = await _get_customer(db_session, restaurant.id)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "date_select"  # skipped straight past staff_select
    assert "staff_id" not in state.context

    today_reply_id = f"date:{date.today().isoformat()}"
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, today_reply_id)
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "time:09:00")

    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "name:edit")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "name_edit"

    # Back -> name_confirm, then re-enter edit.
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, generic_flow_engine.BACK_REPLY_ID)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "name_confirm"
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "name:edit")

    await _send_text(db_session, sender, restaurant, CUSTOMER_PHONE, "Rahul M.")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "booking_confirm"
    assert state.context["customer_name_override"] == "Rahul M."
    assert "staff_id" not in state.context


async def test_free_test_drive_item_price_label(db_session, automobile_tenant, sender):
    """The Test Drive category's item is price=0/price_type="free" -- confirms the
    catalog seed content renders correctly through the real "items" data provider."""
    restaurant = automobile_tenant
    test_drive_category_id = await _get_category_id(db_session, restaurant.id, "Test Drive")
    test_drive_item = await _get_item(db_session, restaurant.id, "Test Drive Booking", "Test Drive")
    assert float(test_drive_item.price) == 0
    assert test_drive_item.price_type == "free"
    assert test_drive_item.attributes["duration_minutes"] == 30

    await _send_text(db_session, sender, restaurant, CUSTOMER_PHONE, "hi", profile_name=CUSTOMER_PROFILE_NAME)
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "welcome:testdrive")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"category:{test_drive_category_id}")

    caption = _last_image_caption(sender)
    assert "Free" in caption
    assert "30min" in caption

    customer = await _get_customer(db_session, restaurant.id)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "service_select"
    service_options = _extract_options(_last_interactive(sender))
    assert {o["title"] for o in service_options if o["id"] != generic_flow_engine.BACK_REPLY_ID} == {"Test Drive Booking"}


# --- reverse scenario: staff_selection explicitly ON still works correctly ---------------


async def test_staff_selection_module_when_explicitly_enabled_still_works(db_session, automobile_tenant_staff_on, sender):
    """Proves the staff_select step's own config (not just the skip branch) is correct:
    when a business turns staff_selection on, the step renders "Any Available" + named
    Service Advisors, captures staff_id on tap, and proceeds to date_select exactly like
    every other appointment niche's staff_select step does."""
    restaurant = automobile_tenant_staff_on
    car_service_category_id = await _get_category_id(db_session, restaurant.id, "Car Service")
    oil_change_item = await _get_item(db_session, restaurant.id, "Oil Change", "Car Service")
    ramesh_id = await _get_staff_id(db_session, restaurant.id, "Ramesh")

    await _send_text(db_session, sender, restaurant, CUSTOMER_PHONE, "hi", profile_name=CUSTOMER_PROFILE_NAME)
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "welcome:book")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"category:{car_service_category_id}")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"item:{oil_change_item.id}")

    customer = await _get_customer(db_session, restaurant.id)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "staff_select"  # rendered this time, module is on
    staff_options = _extract_options(_last_interactive(sender))
    staff_titles = {o["title"] for o in staff_options if o["id"] != generic_flow_engine.BACK_REPLY_ID}
    assert staff_titles == {"Any Available", "Ramesh"}

    #     Back -> service_select, then forward again -- staff_select's own back_target,
    #     only reachable at all when the module is on (this is the ONLY appointment niche
    #     with the module off by default, so this edge needs its own dedicated on-module
    #     test rather than the main flow) ---------------------------------------------------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, generic_flow_engine.BACK_REPLY_ID)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "service_select"
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"item:{oil_change_item.id}")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "staff_select"

    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"staff:{ramesh_id}")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "date_select"
    assert state.context["staff_id"] == ramesh_id
    assert state.context["staff_id_label"] == "Ramesh"

    #     Back -> staff_select, staff_id survives, then forward again ------------------------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, generic_flow_engine.BACK_REPLY_ID)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "staff_select"
    assert state.context["staff_id"] == ramesh_id
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"staff:{ramesh_id}")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "date_select"


async def test_side_branch_messages_return_to_welcome(db_session, automobile_tenant, sender):
    """The three "message"-type info steps reachable from the welcome menu (offers_info,
    showroom_info, contact_info) -- the last 3 of the 11 total back_target edges in this
    niche's flow -- must each land back on welcome, with forward re-entry working again
    afterwards."""
    restaurant = automobile_tenant
    await _send_text(db_session, sender, restaurant, CUSTOMER_PHONE, "hi", profile_name=CUSTOMER_PROFILE_NAME)
    customer = await _get_customer(db_session, restaurant.id)

    for welcome_option, info_step in [
        ("welcome:offers", "offers_info"),
        ("welcome:showroom", "showroom_info"),
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
