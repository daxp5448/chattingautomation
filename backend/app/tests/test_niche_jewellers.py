"""End-to-end proof that the Jewellers niche template (app/niche_seeds/jewellers.py,
action_type="inquiry") drives a real conversation through the real
app/services/generic_flow_engine.py.

RESTRUCTURED (see niche_seeds/jewellers.py's module docstring): this niche used to be a
cart/checkout "order" flow, a straight re-skin of Restaurant. It is now an enquiry/
appointment-led "inquiry" niche, sharing Real Estate's inquiry flow shape instead --
high-value jewellery purchases are enquiry-driven, not one-tap-checkout. This test file
replaces the old cart/checkout-flow test entirely; there is no cart/quantity/checkout/
payment path left to test in this niche.

Same driving pattern as app/tests/test_niche_real_estate.py: direct calls to
generic_flow_engine.process_inbound_message (the exact function
app/api/v1/routers/webhook.py's routing switch calls for any
Restaurant.uses_generic_engine=True business), inspecting the InMemoryWhatsAppSender's
`.sent` list and the GenericConversationState/Engagement rows the engine writes.

Every `back_target` in the flow is exercised at least once: category_select->welcome,
item_select->category_select, piece_details->item_select, visit_capture->piece_details,
requirements_capture->visit_capture, name_confirm->requirements_capture,
name_edit->name_confirm, inquiry_confirm->name_confirm, and the four side-branch message
steps (offers_info/location_info/contact_info/human_handoff) -> welcome.
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
from app.niche_seeds.jewellers import TEMPLATE
from app.services.generic_flow_engine import GenericInteraction, process_inbound_message
from app.services.niche_provisioning import provision_from_template
from app.services.whatsapp_client import InMemoryWhatsAppSender, OutboundMessage

PHONE_NUMBER_ID = "JEWELLERS_TEST_PHONE_NUMBER_ID"
CUSTOMER_PHONE = "919876544321"
CUSTOMER_PROFILE_NAME = "Ananya Sharma"

_wamid_counter = itertools.count(1)


def _next_wamid() -> str:
    return f"wamid.jewellers.test.{next(_wamid_counter)}"


# --- fixtures -----------------------------------------------------------------------------


@pytest_asyncio.fixture
async def sender():
    return InMemoryWhatsAppSender()


@pytest_asyncio.fixture
async def jewellers_tenant(db_session):
    restaurant = Restaurant(
        name="Kanchan Jewellers",
        slug="kanchan-jewellers",
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


async def test_side_branch_messages_return_to_welcome(db_session, jewellers_tenant, sender):
    restaurant = jewellers_tenant
    await _send_text(db_session, sender, restaurant, CUSTOMER_PHONE, "hi", profile_name=CUSTOMER_PROFILE_NAME)
    customer = await _get_customer(db_session, restaurant.id)

    cases = [
        ("welcome:offers", "offers_info", "offers"),
        ("welcome:store", "location_info", "directions"),
        ("welcome:contact", "contact_info", "team"),
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

        await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, generic_flow_engine.BACK_REPLY_ID)
        state = await _get_state(db_session, customer.id)
        assert state.current_step == "welcome"


# --- the main end-to-end proof (real engine; enquiry lead capture + back-nav, no cart) ---


async def test_full_enquiry_flow_with_back_navigation(db_session, jewellers_tenant, sender):
    restaurant = jewellers_tenant
    gold_category_id = await _get_category_id(db_session, restaurant.id, "Gold Jewellery")
    diamond_category_id = await _get_category_id(db_session, restaurant.id, "Diamond Jewellery")
    gold_necklace = await _get_item(db_session, restaurant.id, "Gold Necklace")
    diamond_ring = await _get_item(db_session, restaurant.id, "Diamond Ring")
    gold_necklace_id = str(gold_necklace.id)

    assert float(gold_necklace.price) == 85000
    assert float(diamond_ring.price) == 65000

    # --- 1. "Hi" -> welcome + 6 options, entry point, no Back ------------------------------
    # "welcome:explore_design" (-> the isolated jewellery visual carousel, see
    # test_jewellery_carousel.py) is first -- the old "welcome:explore"/"Explore
    # Collection" button was removed as a redundant duplicate of it. "Book Appointment"
    # is now the sole entry point into the enquiry flow below, which is otherwise
    # unchanged.
    await _send_text(db_session, sender, restaurant, CUSTOMER_PHONE, "Hi", profile_name=CUSTOMER_PROFILE_NAME)
    welcome_options = _extract_options(_last_interactive(sender))
    assert [o["id"] for o in welcome_options] == [
        "welcome:explore_design", "welcome:appointment", "welcome:offers", "welcome:store", "welcome:contact", "welcome:human",
    ]
    customer = await _get_customer(db_session, restaurant.id)
    assert customer.name == CUSTOMER_PROFILE_NAME  # auto-pulled from the WhatsApp profile
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "welcome"

    # --- 2. "Book Appointment" -> category list [Back -> Welcome] -------------------------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "welcome:appointment")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "category_select"
    category_options = _extract_options(_last_interactive(sender))
    category_ids = {o["id"] for o in category_options}
    assert f"category:{gold_category_id}" in category_ids
    assert {"Gold Jewellery", "Diamond Jewellery", "Silver Jewellery", "Bridal Collection"} <= {
        o["title"] for o in category_options
    }

    #     Back -> Welcome, then forward again -----------------------------------------------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, generic_flow_engine.BACK_REPLY_ID)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "welcome"
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "welcome:appointment")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "category_select"

    # --- 2b. "Book Appointment" leads into the exact same category list -------------------
    second_phone = "919876500094"
    await _send_text(db_session, sender, restaurant, second_phone, "hi", profile_name="Second Customer")
    await _tap(db_session, sender, restaurant, second_phone, "welcome:appointment")
    second_customer = await _get_customer(db_session, restaurant.id, phone=second_phone)
    second_state = await _get_state(db_session, second_customer.id)
    assert second_state.current_step == "category_select"

    # --- 3. Category tapped -> piece list, tap=select [Back -> Category list] -------------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"category:{gold_category_id}")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "item_select"
    assert state.context["category_id"] == gold_category_id
    assert state.context["category_id_label"] == "Gold Jewellery"
    item_options = _extract_options(_last_interactive(sender))
    by_title = {o["title"]: o["id"] for o in item_options if o["id"] != generic_flow_engine.BACK_REPLY_ID}
    assert by_title == {"Gold Necklace": f"item:{gold_necklace_id}", "Gold Bangles": f"item:{(await _get_item(db_session, restaurant.id, 'Gold Bangles')).id}"}

    #     Back -> Category list, category_id survives, then forward again -------------------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, generic_flow_engine.BACK_REPLY_ID)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "category_select"
    assert state.context["category_id"] == gold_category_id  # not popped
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"category:{gold_category_id}")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "item_select"

    # --- 4. Piece tapped -> piece detail (full photo gallery) [Back -> Piece list] ---------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"item:{gold_necklace_id}")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "piece_details"
    assert state.context["item_id"] == gold_necklace_id
    assert state.context["item_id_label"] == "Gold Necklace"
    # capture_pending_item's action also ran alongside capture_key on this step.
    assert state.context["pending_item"]["item_id"] == gold_necklace_id
    assert state.context["pending_item_name"] == "Gold Necklace"
    detail_body = _body_text(_last_interactive(sender))
    assert "Gold Necklace" in detail_body
    detail_options = _extract_options(_last_interactive(sender))
    assert {o["id"] for o in detail_options} == {"piece:enquire", generic_flow_engine.BACK_REPLY_ID}

    #     Back -> piece list, item_id survives, then forward again --------------------------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, generic_flow_engine.BACK_REPLY_ID)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "item_select"
    assert state.context["item_id"] == gold_necklace_id
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"item:{gold_necklace_id}")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "piece_details"

    # --- 4b. "Enquire About This Piece" -> visit-preference note [Back -> Piece details] ---
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "piece:enquire")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "visit_capture"
    visit_body = _body_text(_last_interactive(sender))
    assert "Gold Necklace" in visit_body
    visit_options = _extract_options(_last_interactive(sender))
    assert {o["id"] for o in visit_options} == {generic_flow_engine.SKIP_REPLY_ID, generic_flow_engine.BACK_REPLY_ID}

    #     Back -> piece details, then forward again ------------------------------------------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, generic_flow_engine.BACK_REPLY_ID)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "piece_details"
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "piece:enquire")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "visit_capture"

    # --- 5. Visit preference typed -> requirements note [Back -> visit note] --------------
    await _send_text(db_session, sender, restaurant, CUSTOMER_PHONE, "This Saturday afternoon")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "requirements_capture"
    assert state.context["preferred_visit"] == "This Saturday afternoon"
    requirements_options = _extract_options(_last_interactive(sender))
    assert {o["id"] for o in requirements_options} == {generic_flow_engine.SKIP_REPLY_ID, generic_flow_engine.BACK_REPLY_ID}

    #     Back -> visit note, preference survives, then forward again -----------------------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, generic_flow_engine.BACK_REPLY_ID)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "visit_capture"
    assert state.context["preferred_visit"] == "This Saturday afternoon"
    await _send_text(db_session, sender, restaurant, CUSTOMER_PHONE, "This Saturday afternoon")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "requirements_capture"

    # --- 6. Requirements typed -> name confirmation [Back -> requirements note] -----------
    await _send_text(db_session, sender, restaurant, CUSTOMER_PHONE, "Prefer 22K, budget around 90000")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "name_confirm"
    assert state.context["requirements"] == "Prefer 22K, budget around 90000"
    name_confirm_body = _body_text(_last_interactive(sender))
    assert "confirm the name" in name_confirm_body.lower()
    assert CUSTOMER_PROFILE_NAME in name_confirm_body
    name_confirm_options = _extract_options(_last_interactive(sender))
    assert {o["id"] for o in name_confirm_options if o["id"] != generic_flow_engine.BACK_REPLY_ID} == {
        "name:confirm", "name:edit",
    }

    #     Back -> requirements note, requirements survives, then forward again -------------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, generic_flow_engine.BACK_REPLY_ID)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "requirements_capture"
    assert state.context["requirements"] == "Prefer 22K, budget around 90000"
    await _send_text(db_session, sender, restaurant, CUSTOMER_PHONE, "Prefer 22K, budget around 90000")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "name_confirm"

    # --- 7. "Looks Good" -> enquiry review card [Back -> name confirmation] ---------------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "name:confirm")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "inquiry_confirm"
    confirm_body = _body_text(_last_interactive(sender))
    assert "Gold Necklace" in confirm_body
    assert "This Saturday afternoon" in confirm_body
    assert "Prefer 22K, budget around 90000" in confirm_body
    confirm_options = _extract_options(_last_interactive(sender))
    assert {o["id"] for o in confirm_options} == {"inquiry:submit", generic_flow_engine.BACK_REPLY_ID}

    #     Back -> name confirmation, then forward again --------------------------------------
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, generic_flow_engine.BACK_REPLY_ID)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "name_confirm"
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "name:confirm")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "inquiry_confirm"

    # --- 8. "Submit Enquiry" -> submitted, no payment, staff notified [terminal, no Back] --
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
    assert engagement.details["category_id"] == gold_category_id
    assert engagement.details["item_id"] == gold_necklace_id
    assert engagement.details["preferred_visit"] == "This Saturday afternoon"
    assert engagement.details["requirements"] == "Prefer 22K, budget around 90000"

    # Customer-facing terminal confirmation message -- an enquiry acknowledgment, not a
    # purchase confirmation.
    confirmed_message = _last_message_to(sender, CUSTOMER_PHONE)
    confirmed_body = _body_text(confirmed_message)
    assert "submitted" in confirmed_body.lower()
    assert "expert" in confirmed_body.lower()
    assert engagement.reference_number in confirmed_body
    assert "Gold Necklace" in confirmed_body

    # Staff notified via notify_business() at restaurant.staff_notification_number.
    staff_message = _last_message_to(sender, restaurant.staff_notification_number)
    staff_body = _body_text(staff_message)
    assert "New inquiry" in staff_body
    assert engagement.reference_number in staff_body
    assert CUSTOMER_PROFILE_NAME in staff_body  # customer.name, read directly (not via context)


async def test_visit_skip_goes_straight_to_requirements(db_session, jewellers_tenant, sender):
    """The Skip button on visit_capture -- a genuinely optional text field per the global
    spec rule -- must proceed straight to requirements_capture with no preference set."""
    restaurant = jewellers_tenant
    diamond_category_id = await _get_category_id(db_session, restaurant.id, "Diamond Jewellery")
    diamond_ring = await _get_item(db_session, restaurant.id, "Diamond Ring")

    await _send_text(db_session, sender, restaurant, CUSTOMER_PHONE, "hi", profile_name=CUSTOMER_PROFILE_NAME)
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "welcome:appointment")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"category:{diamond_category_id}")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"item:{diamond_ring.id}")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "piece:enquire")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, generic_flow_engine.SKIP_REPLY_ID)

    customer = await _get_customer(db_session, restaurant.id)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "requirements_capture"
    assert state.context["preferred_visit"] is None


async def test_name_edit_branch_captures_override_and_continues(db_session, jewellers_tenant, sender):
    """The "Edit Name" side-branch off the name_confirm step: free-text capture into
    customer_name_override, with its own Back -> name_confirm, then continuing on to the
    same inquiry_confirm step "Looks Good" would.
    """
    restaurant = jewellers_tenant
    gold_category_id = await _get_category_id(db_session, restaurant.id, "Gold Jewellery")
    gold_necklace = await _get_item(db_session, restaurant.id, "Gold Necklace")

    await _send_text(db_session, sender, restaurant, CUSTOMER_PHONE, "hello", profile_name=CUSTOMER_PROFILE_NAME)
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "welcome:appointment")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"category:{gold_category_id}")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"item:{gold_necklace.id}")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "piece:enquire")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, generic_flow_engine.SKIP_REPLY_ID)  # skip visit
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, generic_flow_engine.SKIP_REPLY_ID)  # skip requirements

    customer = await _get_customer(db_session, restaurant.id)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "name_confirm"

    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "name:edit")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "name_edit"

    # Back -> name_confirm, then re-enter edit.
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, generic_flow_engine.BACK_REPLY_ID)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "name_confirm"
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "name:edit")

    await _send_text(db_session, sender, restaurant, CUSTOMER_PHONE, "Ananya S.")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "inquiry_confirm"
    assert state.context["customer_name_override"] == "Ananya S."

    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "inquiry:submit")
    engagement = (await db_session.execute(select(Engagement).where(Engagement.restaurant_id == restaurant.id))).scalars().one()
    assert engagement.details["customer_name_override"] == "Ananya S."


async def test_talk_to_human_hands_off_and_pauses_automation(db_session, jewellers_tenant, sender):
    """The welcome menu's new "Talk to a Human" entry (human_handoff step type) must set
    is_handed_over and stop the automated flow from advancing on further messages."""
    restaurant = jewellers_tenant
    await _send_text(db_session, sender, restaurant, CUSTOMER_PHONE, "hi", profile_name=CUSTOMER_PROFILE_NAME)
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "welcome:human")

    customer = await _get_customer(db_session, restaurant.id)
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "human_handoff"
    assert state.is_handed_over is True
    handoff_message = _last_message_to(sender, CUSTOMER_PHONE)
    assert "connecting" in _body_text(handoff_message).lower()

    # Automation stays paused -- a further message doesn't advance the flow.
    await _send_text(db_session, sender, restaurant, CUSTOMER_PHONE, "hello?")
    state = await _get_state(db_session, customer.id)
    assert state.current_step == "human_handoff"
