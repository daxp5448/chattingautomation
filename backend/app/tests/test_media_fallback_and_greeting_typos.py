"""Proof for two real, isolated gaps found while investigating an "intent router"
request (see generic_flow_engine.py's _MEDIA_FALLBACK_MESSAGES / _FUZZY_GREETING_WORDS
docstrings for the full rationale, and _extract_generic_interaction in webhook.py):

  1. Before this, _extract_generic_interaction returned None for image/video/audio/
     document/sticker/native-catalog-order messages, and the webhook silently dropped
     them -- a customer sending a photo or voice note got zero reply. Now they get a
     polite, type-appropriate acknowledgement and their conversation state is untouched.
  2. _looks_like_greeting was exact-word-match only, so "heyy"/"halo" (both explicit,
     unambiguous typos) failed to reset a stuck/finished conversation. Now handled --
     "heyy"/"halo" as literal additions (zero ambiguity risk), plus a narrow,
     explicitly-scoped Levenshtein fallback for "hello"/"namaste" typos specifically
     (single-word messages only, and deliberately NOT "start", which collides with real
     words like "smart" at edit-distance 1 -- see that constant's own docstring).
"""

from app.api.v1.routers.webhook import _extract_generic_interaction
from app.core.security import encrypt_secret
from app.models.enums import EngagementType
from app.models.flow_definition import FlowDefinition
from app.models.restaurant import Restaurant
from app.services.generic_flow_engine import (
    GenericInteraction,
    _looks_like_greeting,
    process_inbound_message,
)
from app.services.whatsapp_client import InMemoryWhatsAppSender
from sqlalchemy import select

PHONE = "919999911122"


def _steps():
    return [
        {
            "step_id": "welcome", "type": "menu_select", "prompt": "Hi! Welcome.", "buttons_from": "static",
            "static_options": [{"id": "welcome:a", "title": "Option A"}],
            "routes": {"welcome:a": "picked"}, "next": "picked", "back_target": None, "show_image": False,
        },
        {
            "step_id": "picked", "type": "message", "terminal": True, "back_target": None,
            "prompt": "You picked it.",
        },
    ]


async def _make_restaurant(db_session) -> Restaurant:
    restaurant = Restaurant(
        name="Media Fallback Test", slug="media-fallback-test", uses_generic_engine=True,
        niche_type="restaurant", whatsapp_phone_number_id="MFT_TEST_PNID",
        whatsapp_access_token_encrypted=encrypt_secret("fake-token"),
    )
    db_session.add(restaurant)
    await db_session.flush()
    db_session.add(FlowDefinition(restaurant_id=restaurant.id, niche_code="restaurant", action_type=EngagementType.ORDER, steps=_steps()))
    await db_session.commit()
    return restaurant


# --- webhook payload parsing --------------------------------------------------------


def test_image_message_is_parsed_as_unhandled_media():
    message = {"type": "image", "image": {"id": "MEDIA123", "mime_type": "image/jpeg"}}
    interaction = _extract_generic_interaction(message, profile_name="Test Customer")
    assert interaction.kind == "unhandled_media"
    assert interaction.media_kind == "image"


def test_voice_note_and_native_catalog_order_are_also_parsed_not_dropped():
    audio = _extract_generic_interaction({"type": "audio", "audio": {"id": "A1"}}, profile_name=None)
    assert audio.kind == "unhandled_media" and audio.media_kind == "audio"

    order = _extract_generic_interaction(
        {"type": "order", "order": {"catalog_id": "C1", "product_items": [{"product_retailer_id": "P1", "quantity": 2}]}},
        profile_name=None,
    )
    assert order.kind == "unhandled_media" and order.media_kind == "order"


def test_genuinely_unknown_message_type_still_returns_none():
    # Anything NOT in the explicit media/order allowlist stays a silent no-op -- this
    # proves the fix is scoped, not a catch-all that changes unrelated behavior.
    assert _extract_generic_interaction({"type": "unsupported_future_type"}, profile_name=None) is None


# --- engine behavior: acknowledges without touching conversation state --------------


async def test_image_gets_a_polite_reply_and_does_not_move_the_conversation(db_session):
    restaurant = await _make_restaurant(db_session)
    sender = InMemoryWhatsAppSender()

    await process_inbound_message(db_session, sender, restaurant, PHONE, GenericInteraction(kind="text", text="hi"))
    sender.sent.clear()

    await process_inbound_message(db_session, sender, restaurant, PHONE, GenericInteraction(kind="unhandled_media", media_kind="image"))

    text_messages = [m for m in sender.sent if m.payload.get("type") == "text"]
    assert len(text_messages) == 1
    assert "image" in text_messages[0].payload["text"]["body"]

    from app.models.customer import Customer
    from app.models.generic_conversation_state import GenericConversationState

    customer = (await db_session.execute(select(Customer).where(Customer.restaurant_id == restaurant.id, Customer.phone == PHONE))).scalar_one()
    state = (await db_session.execute(select(GenericConversationState).where(GenericConversationState.customer_id == customer.id))).scalar_one()
    assert state.current_step == "welcome"  # unchanged -- still able to tap Option A next


async def test_unrecognized_media_kind_falls_back_to_the_default_message(db_session):
    restaurant = await _make_restaurant(db_session)
    sender = InMemoryWhatsAppSender()

    await process_inbound_message(db_session, sender, restaurant, PHONE, GenericInteraction(kind="text", text="hi"))
    sender.sent.clear()

    await process_inbound_message(db_session, sender, restaurant, PHONE, GenericInteraction(kind="unhandled_media", media_kind="carrier_pigeon"))

    text_messages = [m for m in sender.sent if m.payload.get("type") == "text"]
    assert text_messages[0].payload["text"]["body"] == "We received your message. Type *menu* any time to see our options."


async def test_media_during_human_handoff_gets_no_automated_reply(db_session):
    restaurant = await _make_restaurant(db_session)
    sender = InMemoryWhatsAppSender()

    await process_inbound_message(db_session, sender, restaurant, PHONE, GenericInteraction(kind="text", text="hi"))

    from app.models.customer import Customer
    from app.models.generic_conversation_state import GenericConversationState

    customer = (await db_session.execute(select(Customer).where(Customer.restaurant_id == restaurant.id, Customer.phone == PHONE))).scalar_one()
    state = (await db_session.execute(select(GenericConversationState).where(GenericConversationState.customer_id == customer.id))).scalar_one()
    state.is_handed_over = True
    await db_session.commit()
    sender.sent.clear()

    await process_inbound_message(db_session, sender, restaurant, PHONE, GenericInteraction(kind="unhandled_media", media_kind="image"))
    assert sender.sent == []


# --- typo-tolerant greeting matching -------------------------------------------------


def test_explicit_typo_variants_are_recognized_as_greetings():
    assert _looks_like_greeting("heyy") is True
    assert _looks_like_greeting("HALO") is True
    assert _looks_like_greeting("Halo") is True


def test_fuzzy_typos_of_hello_and_namaste_are_recognized():
    assert _looks_like_greeting("helo") is True  # distance 1 from "hello"
    assert _looks_like_greeting("hellllo") is False  # distance 2 -- outside tolerance
    assert _looks_like_greeting("namaste") is True  # exact
    assert _looks_like_greeting("namasta") is True  # distance 1 from "namaste"


def test_start_is_not_fuzzy_matched_to_avoid_colliding_with_real_words():
    # "start" itself still works (exact match) -- only the FUZZY neighborhood around it
    # is deliberately not matched, so real words like "smart" never accidentally reset
    # a customer's conversation.
    assert _looks_like_greeting("start") is True
    assert _looks_like_greeting("smart") is False


async def test_typo_greeting_resets_a_stuck_conversation_same_as_an_exact_one(db_session):
    restaurant = await _make_restaurant(db_session)
    sender = InMemoryWhatsAppSender()

    await process_inbound_message(db_session, sender, restaurant, PHONE, GenericInteraction(kind="text", text="hi"))
    await process_inbound_message(db_session, sender, restaurant, PHONE, GenericInteraction(kind="button_reply", reply_id="welcome:a"))

    from app.models.customer import Customer
    from app.models.generic_conversation_state import GenericConversationState

    customer = (await db_session.execute(select(Customer).where(Customer.restaurant_id == restaurant.id, Customer.phone == PHONE))).scalar_one()
    state = (await db_session.execute(select(GenericConversationState).where(GenericConversationState.customer_id == customer.id))).scalar_one()
    assert state.current_step == "picked"  # terminal -- nowhere left to go without a reset

    await process_inbound_message(db_session, sender, restaurant, PHONE, GenericInteraction(kind="text", text="heyy"))
    await db_session.refresh(state)
    assert state.current_step == "welcome"
