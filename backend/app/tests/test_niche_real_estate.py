"""End-to-end proof that the Real Estate niche template (app/niche_seeds/real_estate.py,
action_type="inquiry") actually drives a real conversation through the real
app/services/generic_flow_engine.py -- the "inquiry" proof niche (lead capture, no cart,
no payment) among the platform's 4 action-type niches.

Same driving pattern as app/tests/test_niche_salon.py and
app/tests/test_niche_restaurant.py: direct calls to
generic_flow_engine.process_inbound_message (the exact function
app/api/v1/routers/webhook.py's routing switch calls for any
Restaurant.uses_generic_engine=True business), inspecting the InMemoryWhatsAppSender's
`.sent` list and the GenericConversationState/Engagement rows the engine writes.

Every `back_target` in the flow is exercised at least once: category_select->welcome,
item_select->category_select, budget_capture->item_select,
requirements_capture->budget_capture, name_confirm->requirements_capture,
name_edit->name_confirm, inquiry_confirm->name_confirm, and the four side-branch message
steps (list_property_info/offers_info/location_info/contact_info) -> welcome.
"""

import itertools

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
from app.niche_seeds.real_estate import TEMPLATE
from app.services.generic_flow_engine import GenericInteraction, process_inbound_message
from app.services.niche_provisioning import provision_from_template
from app.services.whatsapp_client import InMemoryWhatsAppSender, OutboundMessage

PHONE_NUMBER_ID = "REAL_ESTATE_TEST_PHONE_NUMBER_ID"
CUSTOMER_PHONE = "919876543212"
CUSTOMER_PROFILE_NAME = "Neha Kapoor"

_wamid_counter = itertools.count(1)


def _next_wamid() -> str:
    return f"wamid.real_estate.test.{next(_wamid_counter)}"


# --- fixtures -----------------------------------------------------------------------------


@pytest_asyncio.fixture
async def sender():
    return InMemoryWhatsAppSender()


@pytest_asyncio.fixture
async def real_estate_tenant(db_session):
    restaurant = Restaurant(
        name="Skyline Realty",
        slug="skyline-realty",
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


def _last_text_message(sender: InMemoryWhatsAppSender) -> OutboundMessage:
    for message in reversed(sender.sent):
        if message.payload.get("type") == "text":
            return message
    raise AssertionError("No text message was sent")


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


# --- side-branch message steps off the welcome menu, each [Back -> Welcome] -------------


async def test_side_branch_messages_return_to_welcome(db_session, real_estate_tenant, sender):
    restaurant = real_estate_tenant
    await _send_text(db_session, sender, restaurant, CUSTOMER_PHONE, "hi", profile_name=CUSTOMER_PROFILE_NAME)
    customer = await _get_customer(db_session, restaurant.id)

    cases = [
        ("welcome:list_property", "list_property_info", "list your property"),
        ("welcome:offers", "offers_info", "offers"),
        ("welcome:office", "location_info", "office"),
        ("welcome:contact", "contact_info", "sales team"),
    ]
    for button_id, step_id, expected_snippet in cases:
        await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, button_id)
        state = await _get_state(db_session, customer.id)
        assert state.current_step == step_id
        body = _body_text(_last_text_message(sender))
        assert expected_snippet.lower() in body.lower()

        # Back -> welcome, then forward again lands back on the same side-branch step.
        await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, generic_flow_engine.BACK_REPLY_ID)
        state = await _get_state(db_session, customer.id)
        assert state.current_step == "welcome"
        await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, button_id)
        state = await _get_state(db_session, customer.id)
        assert state.current_step == step_id

        # Return to welcome before the next case -- a message step (like this one) can't
        # process a fresh "welcome:*" button tap itself (it expects no input), so the
        # engine would just treat it as "start over" rather than route it.
        await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, generic_flow_engine.BACK_REPLY_ID)
        state = await _get_state(db_session, customer.id)
        assert state.current_step == "welcome"


# --- the main end-to-end proof (real engine; lead capture + back-nav, no cart/payment) ---


async def test_full_inquiry_flow_with_back_navigation(db_session, real_estate_tenant, sender):
    restaurant = real_estate_tenant
    apartments_category_id = await _get_category_id(db_session, restaurant.id, "Apartments")
    sea_view_item = await _get_item(db_session, restaurant.id, "Sea View 2BHK")
    garden_view_item = await _get_item(db_session, restaurant.id, "Garden View 3BHK")
    sea_view_item_id = str(sea_view_item.id)

    assert float(sea_view_item.price) == 8500000
    assert sea_view_item.attributes["bedrooms"] == 2
    assert float(garden_view_item.price) == 12500000

    # --- 1. "Hi" -> welcome + 5 options, entry point, no Back -----------------------------
    await _send_text(db_session, sender, restaurant, CUSTOMER_PHONE, "Hi", profile_name=CUSTOMER_PROFILE_NAME)
    welcome_options = _extract_options(_last_interactive(sender))
    assert [o["id"] for o in welcome_options] == [
        "welcome:browse", "welcome:list_property", "welcome:offers", "welcome:office", "welcome:contact",
    ]
    customer = await _get_customer(db_session, restaurant.id)
    assert customer.name == CUSTOMER_PROFILE_NAME  # auto-pulled from the WhatsApp profile
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "welcome"

    # --- 2. "Browse Properties" -> category list [Back -> Welcome] ------------------------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "welcome:browse")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "category_select"
    category_options = _extract_options(_last_interactive(sender))
    category_ids = {o["id"] for o in category_options}
    assert f"category:{apartments_category_id}" in category_ids
    assert {"Apartments", "Villas", "Plots", "Commercial Spaces"} <= {o["title"] for o in category_options}

    #     Back -> Welcome, then forward again -----------------------------------------------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, generic_flow_engine.BACK_REPLY_ID)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "welcome"
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "welcome:browse")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "category_select"

    # --- 3. Category tapped -> listing list, tap=select [Back -> Category list] -----------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"category:{apartments_category_id}")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "item_select"
    assert state.context["category_id"] == apartments_category_id
    assert state.context["category_id_label"] == "Apartments"
    listing_options = _extract_options(_last_interactive(sender))
    by_title = {o["title"]: o["id"] for o in listing_options if o["id"] != generic_flow_engine.BACK_REPLY_ID}
    assert by_title == {
        "Sea View 2BHK": f"item:{sea_view_item_id}",
        "Garden View 3BHK": f"item:{garden_view_item.id}",
    }

    #     Back -> Category list, category_id survives, then forward again -------------------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, generic_flow_engine.BACK_REPLY_ID)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "category_select"
    assert state.context["category_id"] == apartments_category_id  # not popped
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"category:{apartments_category_id}")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "item_select"

    # --- 4. Listing tapped -> budget note [Back -> Listing list] --------------------------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"item:{sea_view_item_id}")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "budget_capture"
    assert state.context["item_id"] == sea_view_item_id
    assert state.context["item_id_label"] == "Sea View 2BHK"
    # capture_pending_item's action also ran alongside capture_key on this step.
    assert state.context["pending_item"]["item_id"] == sea_view_item_id
    assert state.context["pending_item_name"] == "Sea View 2BHK"
    budget_body = _body_text(_last_interactive(sender))
    assert "Sea View 2BHK" in budget_body
    budget_options = _extract_options(_last_interactive(sender))
    assert {o["id"] for o in budget_options} == {generic_flow_engine.SKIP_REPLY_ID, generic_flow_engine.BACK_REPLY_ID}

    #     Back -> listing list, item_id survives, then forward again ------------------------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, generic_flow_engine.BACK_REPLY_ID)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "item_select"
    assert state.context["item_id"] == sea_view_item_id
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"item:{sea_view_item_id}")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "budget_capture"

    # --- 5. Budget typed as free text -> requirements note [Back -> budget note] ----------
    await _send_text(db_session, sender, restaurant, CUSTOMER_PHONE, "80 lakh to 90 lakh")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "requirements_capture"
    assert state.context["budget_range"] == "80 lakh to 90 lakh"
    requirements_options = _extract_options(_last_interactive(sender))
    assert {o["id"] for o in requirements_options} == {generic_flow_engine.SKIP_REPLY_ID, generic_flow_engine.BACK_REPLY_ID}

    #     Back -> budget note, budget survives, then forward again --------------------------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, generic_flow_engine.BACK_REPLY_ID)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "budget_capture"
    assert state.context["budget_range"] == "80 lakh to 90 lakh"
    await _send_text(db_session, sender, restaurant, CUSTOMER_PHONE, "80 lakh to 90 lakh")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "requirements_capture"

    # --- 6. Requirements typed -> name confirmation [Back -> requirements note] -----------
    await _send_text(db_session, sender, restaurant, CUSTOMER_PHONE, "Ground floor preferred, ready to move")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "name_confirm"
    assert state.context["requirements"] == "Ground floor preferred, ready to move"
    name_confirm_body = _body_text(_last_interactive(sender))
    assert "Please confirm the name for this inquiry" in name_confirm_body or "confirm the name" in name_confirm_body
    assert CUSTOMER_PROFILE_NAME in name_confirm_body
    name_confirm_options = _extract_options(_last_interactive(sender))
    assert {o["id"] for o in name_confirm_options if o["id"] != generic_flow_engine.BACK_REPLY_ID} == {
        "name:confirm", "name:edit",
    }

    #     Back -> requirements note, requirements survives, then forward again -------------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, generic_flow_engine.BACK_REPLY_ID)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "requirements_capture"
    assert state.context["requirements"] == "Ground floor preferred, ready to move"
    await _send_text(db_session, sender, restaurant, CUSTOMER_PHONE, "Ground floor preferred, ready to move")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "name_confirm"

    # --- 7. "Looks Good" -> inquiry review card [Back -> name confirmation] ---------------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "name:confirm")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "inquiry_confirm"
    confirm_body = _body_text(_last_interactive(sender))
    assert "Sea View 2BHK" in confirm_body
    assert "80 lakh to 90 lakh" in confirm_body
    assert "Ground floor preferred, ready to move" in confirm_body
    confirm_options = _extract_options(_last_interactive(sender))
    assert {o["id"] for o in confirm_options} == {"inquiry:submit", generic_flow_engine.BACK_REPLY_ID}

    #     Back -> name confirmation, then forward again --------------------------------------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, generic_flow_engine.BACK_REPLY_ID)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "name_confirm"
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "name:confirm")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "inquiry_confirm"

    # --- 8. "Submit Inquiry" -> submitted, no payment, staff notified [terminal, no Back] --
    engagements_before = (await db_session.execute(select(Engagement))).scalars().all()
    assert len(engagements_before) == 0

    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "inquiry:submit")

    state = await _get_state(db_session, customer.id)
    assert state.current_step == "inquiry_confirmed"

    engagements = (await db_session.execute(select(Engagement).where(Engagement.restaurant_id == restaurant.id))).scalars().all()
    assert len(engagements) == 1
    engagement = engagements[0]
    assert engagement.type == EngagementType.INQUIRY
    assert engagement.status == EngagementStatus.NEW
    assert engagement.customer_id == customer.id
    assert engagement.requires_payment is False  # a lead, never a purchase
    assert float(engagement.total or 0) == 0
    assert engagement.details["category_id"] == apartments_category_id
    assert engagement.details["item_id"] == sea_view_item_id
    assert engagement.details["budget_range"] == "80 lakh to 90 lakh"
    assert engagement.details["requirements"] == "Ground floor preferred, ready to move"

    # Customer-facing terminal confirmation message -- "agent will contact you", not a
    # purchase confirmation.
    confirmed_message = _last_message_to(sender, CUSTOMER_PHONE)
    confirmed_body = _body_text(confirmed_message)
    assert "submitted" in confirmed_body.lower()
    assert "agent" in confirmed_body.lower()
    assert engagement.reference_number in confirmed_body
    assert "Sea View 2BHK" in confirmed_body

    # Staff notified via notify_business() at restaurant.staff_notification_number.
    staff_message = _last_message_to(sender, restaurant.staff_notification_number)
    staff_body = _body_text(staff_message)
    assert "New inquiry" in staff_body
    assert engagement.reference_number in staff_body
    assert CUSTOMER_PROFILE_NAME in staff_body  # customer.name, read directly (not via context)


async def test_name_edit_branch_captures_override_and_continues(db_session, real_estate_tenant, sender):
    """The "Edit Name" side-branch off the name_confirm step: free-text capture into
    customer_name_override, with its own Back -> name_confirm, then continuing on to the
    same inquiry_confirm step "Looks Good" would.
    """
    restaurant = real_estate_tenant
    apartments_category_id = await _get_category_id(db_session, restaurant.id, "Apartments")
    sea_view_item = await _get_item(db_session, restaurant.id, "Sea View 2BHK")

    await _send_text(db_session, sender, restaurant, CUSTOMER_PHONE, "hello", profile_name=CUSTOMER_PROFILE_NAME)
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "welcome:browse")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"category:{apartments_category_id}")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"item:{sea_view_item.id}")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, generic_flow_engine.SKIP_REPLY_ID)  # skip budget
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, generic_flow_engine.SKIP_REPLY_ID)  # skip requirements

    customer = await _get_customer(db_session, restaurant.id)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "name_confirm"
    assert state.context["budget_range"] is None
    assert state.context["requirements"] is None

    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "name:edit")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "name_edit"

    # Back -> name_confirm, then re-enter edit.
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, generic_flow_engine.BACK_REPLY_ID)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "name_confirm"
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "name:edit")

    await _send_text(db_session, sender, restaurant, CUSTOMER_PHONE, "Neha K.")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "inquiry_confirm"
    assert state.context["customer_name_override"] == "Neha K."

    # The skipped free-text fields render as empty, not the literal string "None".
    confirm_body = _body_text(_last_interactive(sender))
    assert "None" not in confirm_body

    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "inquiry:submit")
    engagement = (await db_session.execute(select(Engagement).where(Engagement.restaurant_id == restaurant.id))).scalars().one()
    assert engagement.details["customer_name_override"] == "Neha K."
    assert engagement.details["budget_range"] is None
    assert engagement.details["requirements"] is None
