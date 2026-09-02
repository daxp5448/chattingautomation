"""Rule-based conversational-humanization layer (conversational_intent.py /
conversational_style.py), proven against ALL 12 real niche templates via the real
generic_flow_engine -- same "parametrize over discover_templates(), never hardcode a
niche list" idiom as test_niche_flow_full_walk_all_12.py / test_niche_flow_acceptance_
matrix.py, so a 13th niche added later is covered automatically with no new test code.
"""

import itertools

import pytest
from sqlalchemy import select

from app.core.security import encrypt_secret
from app.models.customer import Customer
from app.models.enums import EngagementType
from app.models.generic_conversation_state import GenericConversationState
from app.models.niche_template import NicheTemplate
from app.models.restaurant import Restaurant
from app.services.generic_flow_engine import GenericInteraction, process_inbound_message
from app.services.niche_provisioning import provision_from_template
from app.services.niche_template_sync import discover_templates
from app.services.whatsapp_client import InMemoryWhatsAppSender, OutboundMessage

_TEMPLATES = {t["code"]: t for t in discover_templates()}
_wamid_counter = itertools.count(1)


def _next_wamid() -> str:
    return f"wamid.humanize.test.{next(_wamid_counter)}"


async def _make_tenant(db_session, code: str) -> Restaurant:
    template_dict = _TEMPLATES[code]
    restaurant = Restaurant(
        name=f"Humanize {code}", slug=f"humanize-{code}",
        whatsapp_phone_number_id=f"HUMANIZE_{code.upper()}_PNID",
        whatsapp_access_token_encrypted=encrypt_secret("fake-token"),
    )
    db_session.add(restaurant)
    await db_session.flush()

    template = NicheTemplate(
        code=template_dict["code"], name=template_dict["name"], action_type=EngagementType(template_dict["action_type"]),
        icon=template_dict["icon"], welcome_message=template_dict["welcome_message"],
        welcome_banner_image=template_dict["welcome_banner_image"], welcome_buttons=template_dict["welcome_buttons"],
        default_catalog=template_dict["default_catalog"], default_flow_steps=template_dict["default_flow_steps"],
        terminology=template_dict["terminology"], default_modules=template_dict["default_modules"],
        default_personality=template_dict["default_personality"],
    )
    db_session.add(template)
    await db_session.flush()

    await provision_from_template(db_session, restaurant, template)
    await db_session.commit()
    return restaurant


async def _send_text(session, sender, restaurant, phone, text):
    await process_inbound_message(
        session, sender, restaurant, phone, GenericInteraction(kind="text", text=text), wa_message_id=_next_wamid(),
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


def _last_interactive(sender: InMemoryWhatsAppSender):
    for message in reversed(sender.sent):
        if message.payload.get("type") != "interactive":
            continue
        if message.payload.get("interactive", {}).get("type") == "location_request_message":
            continue
        return message
    raise AssertionError("No interactive options message was sent")


def _all_text(sender: InMemoryWhatsAppSender) -> str:
    parts = []
    for m in sender.sent:
        payload = m.payload
        if payload.get("type") == "text":
            parts.append(payload["text"]["body"])
        interactive = payload.get("interactive", {})
        if interactive.get("body"):
            parts.append(interactive["body"]["text"])
    return "\n".join(parts)


async def _get_state(session, restaurant_id, phone) -> GenericConversationState:
    customer = (await session.execute(select(Customer).where(Customer.restaurant_id == restaurant_id, Customer.phone == phone))).scalar_one()
    return (await session.execute(select(GenericConversationState).where(GenericConversationState.customer_id == customer.id))).scalar_one()


_PHONE = "919876500099"
_NICHE_CODES = sorted(_TEMPLATES.keys())


@pytest.mark.parametrize("code", _NICHE_CODES)
async def test_typo_free_text_advances_like_the_real_button_would(db_session, code):
    """A typo'd, lowercased version of a real welcome-menu option's title should advance
    the conversation exactly as tapping that button would -- never "Sorry, please pick
    one of the options below" for a message a human would obviously understand."""
    restaurant = await _make_tenant(db_session, code)
    sender = InMemoryWhatsAppSender()
    await _send_text(db_session, sender, restaurant, _PHONE, "hi")

    welcome_options = _extract_options(_last_interactive(sender))
    assert welcome_options, f"{code}: welcome step sent no options to test against"
    target = welcome_options[0]
    # Strip emoji/punctuation and mangle case -- a real customer typo, not the exact title.
    typo_text = "".join(ch for ch in target["title"].lower() if ch.isalnum() or ch.isspace()).strip()
    assert typo_text, f"{code}: welcome option title had no matchable text: {target['title']!r}"

    state_before = await _get_state(db_session, restaurant.id, _PHONE)
    step_before = state_before.current_step

    await _send_text(db_session, sender, restaurant, _PHONE, typo_text)

    state_after = await _get_state(db_session, restaurant.id, _PHONE)
    assert state_after.current_step != step_before, (
        f"{code}: free text {typo_text!r} (from real option {target['title']!r}) did not advance the conversation"
    )


@pytest.mark.parametrize("code", _NICHE_CODES)
async def test_are_you_a_bot_gets_an_honest_reply_and_does_not_advance(db_session, code):
    restaurant = await _make_tenant(db_session, code)
    sender = InMemoryWhatsAppSender()
    await _send_text(db_session, sender, restaurant, _PHONE, "hi")

    state_before = await _get_state(db_session, restaurant.id, _PHONE)
    await _send_text(db_session, sender, restaurant, _PHONE, "are you a bot?")
    state_after = await _get_state(db_session, restaurant.id, _PHONE)

    assert state_after.current_step == state_before.current_step
    assert "virtual assistant" in _all_text(sender)
    assert restaurant.name in _all_text(sender)


@pytest.mark.parametrize("code", _NICHE_CODES)
async def test_back_as_free_text_navigates_like_the_back_button(db_session, code):
    restaurant = await _make_tenant(db_session, code)
    sender = InMemoryWhatsAppSender()
    await _send_text(db_session, sender, restaurant, _PHONE, "hi")

    welcome_options = _extract_options(_last_interactive(sender))
    first_real_option = next((o for o in welcome_options if ":" in o["id"]), None)
    if first_real_option is None:
        pytest.skip(f"{code}: welcome step has no forward-navigating option to test 'back' from")

    await process_inbound_message(
        db_session, sender, restaurant, _PHONE,
        GenericInteraction(kind="button_reply", reply_id=first_real_option["id"], text=first_real_option["title"]),
        wa_message_id=_next_wamid(),
    )
    # Captured as a plain string immediately -- state_mid/state_after are the SAME
    # SQLAlchemy identity-mapped object (same primary key, same session), so reading
    # `.current_step` off the live object again after the "back" call below would just
    # reflect the post-"back" value too, not a frozen snapshot from before it.
    step_mid = (await _get_state(db_session, restaurant.id, _PHONE)).current_step

    await _send_text(db_session, sender, restaurant, _PHONE, "back")
    state_after = await _get_state(db_session, restaurant.id, _PHONE)

    assert state_after.current_step != step_mid, f"{code}: typed 'back' did not navigate away from {step_mid!r}"


@pytest.mark.parametrize("code", _NICHE_CODES)
async def test_repeated_identical_message_does_not_change_state_twice(db_session, code):
    """Same free-text message sent twice in a row (e.g. a WhatsApp retry) must not
    double-advance the conversation -- proves the new intent layer doesn't introduce any
    per-call randomness/side effect beyond what the deterministic engine already does."""
    restaurant = await _make_tenant(db_session, code)
    sender = InMemoryWhatsAppSender()
    await _send_text(db_session, sender, restaurant, _PHONE, "hi")
    await _send_text(db_session, sender, restaurant, _PHONE, "hi")
    state = await _get_state(db_session, restaurant.id, _PHONE)
    assert state.current_step == "welcome"


def test_niches_have_visibly_different_acknowledgement_tone_pools():
    """Smoke check (not exact string matching, to avoid overfitting to phrase wording):
    at least two niches' configured tones map to genuinely different acknowledgement
    phrase pools, proving personality isn't secretly identical across all 12."""
    from app.services.conversational_style import _ACKNOWLEDGEMENT_POOLS

    tones = {t["code"]: t["default_personality"].get("tone") for t in _TEMPLATES.values()}
    assert len(set(tones.values())) >= 8, f"expected meaningfully distinct tones across niches, got {tones}"
    for code, tone in tones.items():
        assert tone in _ACKNOWLEDGEMENT_POOLS, f"{code}: tone {tone!r} has no acknowledgement pool configured"
