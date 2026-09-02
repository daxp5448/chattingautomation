"""Proof for the "quick customize" WhatsApp Flow integration (Flow id
1504663505025579, manually built in Meta's Flow Builder -- see
Restaurant.whatsapp_quick_customize_flow_id's docstring for the full architecture
rationale: a second, independent Flow slot distinct from the platform's own
auto-provisioned ordering Flow, single static screen, no data-exchange endpoint, final
submission arrives as a plain `nfm_reply` webhook message).

Covers:
  1. webhook.py's nfm_reply parsing -- correct field extraction, and malformed JSON
     never crashes the webhook.
  2. generic_flow_engine.py's send_quick_customize_flow step: falls back to `next` when
     no flow_id is configured (every pre-existing niche/business unaffected), sends the
     real Flow message with `mode="draft"` only when the restaurant's own draft-mode
     flag is set, and correctly resolves the flow_id via demo_sends_via_restaurant_id for
     a demo niche business (mirroring _media_message's existing resolution pattern).
  3. Processing a real flow_reply interaction captures item_id/qty/notes into context
     under the SAME keys quantity_input/free_text_input already use ({{quantity}},
     {{note}}), so a niche's own confirmation prompt can render them naturally.
  4. Any other kind of reply at this step re-renders as invalid, never crashes/advances.
"""

import json

from app.api.v1.routers.webhook import _extract_generic_interaction
from app.core.security import encrypt_secret
from app.models.enums import EngagementType
from app.models.flow_definition import FlowDefinition
from app.models.restaurant import Restaurant
from app.services.generic_flow_engine import GenericInteraction, process_inbound_message
from app.services.whatsapp_client import InMemoryWhatsAppSender
from sqlalchemy import select

PHONE = "919999966611"


def _nfm_reply_message(item_id="ITEM_2", qty="3", notes="No onions please") -> dict:
    return {
        "type": "interactive",
        "interactive": {
            "type": "nfm_reply",
            "nfm_reply": {
                "response_json": json.dumps({"item_id": item_id, "qty": qty, "notes": notes}),
                "body": "Sent",
                "name": "flow",
            },
        },
    }


def test_nfm_reply_is_parsed_into_a_flow_reply_interaction():
    interaction = _extract_generic_interaction(_nfm_reply_message(), profile_name="Test Customer")
    assert interaction.kind == "flow_reply"
    assert interaction.flow_response == {"item_id": "ITEM_2", "qty": "3", "notes": "No onions please"}
    assert interaction.profile_name == "Test Customer"


def test_malformed_nfm_reply_json_never_crashes_the_webhook():
    message = {
        "type": "interactive",
        "interactive": {"type": "nfm_reply", "nfm_reply": {"response_json": "{not valid json", "name": "flow"}},
    }
    interaction = _extract_generic_interaction(message, profile_name=None)
    assert interaction.kind == "flow_reply"
    assert interaction.flow_response == {}


def _steps():
    return [
        {
            "step_id": "welcome", "type": "menu_select", "prompt": "Hi!", "buttons_from": "static",
            "static_options": [{"id": "welcome:customize", "title": "Customize"}],
            "routes": {"welcome:customize": "ask"}, "next": "ask", "back_target": None, "show_image": False,
        },
        {
            "step_id": "ask", "type": "send_quick_customize_flow",
            "prompt": "🛍️ Customize your order below.", "cta": "Customize & Select Qty",
            "back_target": "welcome", "next": "confirmed", "fallback_next": "no_flow",
        },
        {
            "step_id": "confirmed", "type": "message", "terminal": True, "back_target": None,
            "prompt": "✅ Got it! {{quick_customize_item_label}} x {{quantity}}. Notes: {{note}}",
        },
        {
            "step_id": "no_flow", "type": "message", "terminal": True, "back_target": None,
            "prompt": "Quick customize isn't set up yet.",
        },
    ]


async def _make_restaurant(db_session, **flow_kwargs) -> Restaurant:
    restaurant = Restaurant(
        name="Quick Customize Test", slug="quick-customize-test", uses_generic_engine=True,
        niche_type="restaurant", whatsapp_phone_number_id="QCF_TEST_PNID",
        whatsapp_access_token_encrypted=encrypt_secret("fake-token"),
        **flow_kwargs,
    )
    db_session.add(restaurant)
    await db_session.flush()
    db_session.add(FlowDefinition(restaurant_id=restaurant.id, niche_code="restaurant", action_type=EngagementType.ORDER, steps=_steps()))
    await db_session.commit()
    return restaurant


async def test_step_falls_back_to_next_when_no_flow_id_configured(db_session):
    restaurant = await _make_restaurant(db_session)  # no flow_id set
    sender = InMemoryWhatsAppSender()

    await process_inbound_message(db_session, sender, restaurant, PHONE, GenericInteraction(kind="text", text="hi"))
    await process_inbound_message(db_session, sender, restaurant, PHONE, GenericInteraction(kind="button_reply", reply_id="welcome:customize"))

    text_messages = [m for m in sender.sent if m.payload.get("type") == "text"]
    assert any("isn't set up yet" in m.payload["text"]["body"] for m in text_messages)
    flow_messages = [m for m in sender.sent if m.payload.get("type") == "interactive" and m.payload["interactive"].get("type") == "flow"]
    assert flow_messages == []


async def test_step_sends_the_real_flow_message_with_draft_mode(db_session):
    restaurant = await _make_restaurant(
        db_session, whatsapp_quick_customize_flow_id="1504663505025579", whatsapp_quick_customize_flow_draft_mode=True,
    )
    sender = InMemoryWhatsAppSender()

    await process_inbound_message(db_session, sender, restaurant, PHONE, GenericInteraction(kind="text", text="hi"))
    await process_inbound_message(db_session, sender, restaurant, PHONE, GenericInteraction(kind="button_reply", reply_id="welcome:customize"))

    flow_messages = [m for m in sender.sent if m.payload.get("type") == "interactive" and m.payload["interactive"].get("type") == "flow"]
    assert len(flow_messages) == 1
    params = flow_messages[0].payload["interactive"]["action"]["parameters"]
    assert params["flow_id"] == "1504663505025579"
    assert params["flow_action_payload"]["screen"] == "ORDER_SCREEN"
    assert params["mode"] == "draft"
    assert params["flow_cta"] == "Customize & Select Qty"


async def test_step_omits_mode_once_flow_is_published(db_session):
    restaurant = await _make_restaurant(
        db_session, whatsapp_quick_customize_flow_id="1504663505025579", whatsapp_quick_customize_flow_draft_mode=False,
    )
    sender = InMemoryWhatsAppSender()

    await process_inbound_message(db_session, sender, restaurant, PHONE, GenericInteraction(kind="text", text="hi"))
    await process_inbound_message(db_session, sender, restaurant, PHONE, GenericInteraction(kind="button_reply", reply_id="welcome:customize"))

    flow_messages = [m for m in sender.sent if m.payload.get("type") == "interactive" and m.payload["interactive"].get("type") == "flow"]
    assert "mode" not in flow_messages[0].payload["interactive"]["action"]["parameters"]


async def test_completing_the_flow_captures_item_qty_notes_and_renders_confirmation(db_session):
    restaurant = await _make_restaurant(db_session, whatsapp_quick_customize_flow_id="1504663505025579")
    sender = InMemoryWhatsAppSender()

    await process_inbound_message(db_session, sender, restaurant, PHONE, GenericInteraction(kind="text", text="hi"))
    await process_inbound_message(db_session, sender, restaurant, PHONE, GenericInteraction(kind="button_reply", reply_id="welcome:customize"))
    sender.sent.clear()

    await process_inbound_message(
        db_session, sender, restaurant, PHONE,
        GenericInteraction(kind="flow_reply", flow_response={"item_id": "ITEM_2", "qty": "3", "notes": "No onions please"}),
    )

    text_messages = [m for m in sender.sent if m.payload.get("type") == "text"]
    body = text_messages[-1].payload["text"]["body"]
    assert "Premium Option" in body
    assert "3" in body
    assert "No onions please" in body

    from app.models.customer import Customer
    from app.models.generic_conversation_state import GenericConversationState

    customer = (await db_session.execute(select(Customer).where(Customer.restaurant_id == restaurant.id, Customer.phone == PHONE))).scalar_one()
    state = (await db_session.execute(select(GenericConversationState).where(GenericConversationState.customer_id == customer.id))).scalar_one()
    assert state.current_step == "confirmed"
    assert state.context["quantity"] == "3"
    assert state.context["note"] == "No onions please"
    assert state.context["quick_customize_item_label"] == "Premium Option"


async def test_unrelated_reply_at_this_step_is_treated_as_invalid_not_a_crash(db_session):
    restaurant = await _make_restaurant(db_session, whatsapp_quick_customize_flow_id="1504663505025579")
    sender = InMemoryWhatsAppSender()

    await process_inbound_message(db_session, sender, restaurant, PHONE, GenericInteraction(kind="text", text="hi"))
    await process_inbound_message(db_session, sender, restaurant, PHONE, GenericInteraction(kind="button_reply", reply_id="welcome:customize"))
    sender.sent.clear()

    await process_inbound_message(db_session, sender, restaurant, PHONE, GenericInteraction(kind="text", text="what's the price?"))

    from app.models.customer import Customer
    from app.models.generic_conversation_state import GenericConversationState

    customer = (await db_session.execute(select(Customer).where(Customer.restaurant_id == restaurant.id, Customer.phone == PHONE))).scalar_one()
    state = (await db_session.execute(select(GenericConversationState).where(GenericConversationState.customer_id == customer.id))).scalar_one()
    assert state.current_step == "ask"  # never advanced/crashed
