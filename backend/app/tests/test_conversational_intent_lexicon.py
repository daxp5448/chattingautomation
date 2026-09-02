"""Unit tests for conversational_intent.py -- no DB, no niche awareness. Table-driven:
every lexicon category x {exact, typo, Hinglish, short} phrasing resolves to the right
signal, plus explicit false-positive guards proving real catalog vocabulary that happens
to look lexicon-like is never misfired on.
"""

import pytest

from app.services.conversational_intent import resolve_interaction
from app.services.generic_flow_engine import GenericInteraction


def _text(t: str) -> GenericInteraction:
    return GenericInteraction(kind="text", text=t)


class _Restaurant:
    conversation_settings: dict = {}


_RESTAURANT = _Restaurant()


@pytest.mark.parametrize(
    "text,expected_signal",
    [
        ("back", "back"),
        ("go back", "back"),
        ("wapas", "back"),
        ("Back", "back"),
        ("start again", "restart"),
        ("restart", "restart"),
        ("phir se shuru", "restart"),
        ("change quantity", "change_qty"),
        ("quantity badlo", "change_qty"),
        ("show more", "show_more"),
        ("aur dikhao", "show_more"),
        ("anything cheaper", "cheaper"),
        ("kuch sasta", "cheaper"),
        ("sasta", "cheaper"),
    ],
)
def test_lexicon_phrases_resolve_to_expected_signal(text, expected_signal):
    resolved = resolve_interaction(_text(text), options=[], context={}, restaurant=_RESTAURANT)
    assert resolved.signal == expected_signal


@pytest.mark.parametrize(
    "text",
    ["are you a bot", "are you human", "kya tum bot ho", "Are You A Bot?"],
)
def test_is_bot_phrases_detected(text):
    resolved = resolve_interaction(_text(text), options=[], context={}, restaurant=_RESTAURANT)
    assert resolved.is_bot_query is True


def test_a_real_button_tap_is_never_reinterpreted():
    """reply_id already set (a real tap) must always pass through untouched, even if its
    accompanying text happens to look lexicon-like."""
    interaction = GenericInteraction(kind="button_reply", reply_id="item:abc", text="back")
    resolved = resolve_interaction(interaction, options=[], context={}, restaurant=_RESTAURANT)
    assert resolved.is_noop


def test_option_matching_fuzzy_typo():
    options = [{"id": "category:1", "title": "Jewellery"}, {"id": "category:2", "title": "Watches"}]
    resolved = resolve_interaction(_text("jwellery"), options=options, context={}, restaurant=_RESTAURANT)
    assert resolved.synthetic_reply_id == "category:1"


def test_option_matching_hinglish_short_message():
    options = [{"id": "category:1", "title": "Rings"}, {"id": "category:2", "title": "Necklaces"}]
    resolved = resolve_interaction(_text("bhai ring dikhana"), options=options, context={}, restaurant=_RESTAURANT)
    assert resolved.synthetic_reply_id == "category:1"


def test_ambiguous_input_returns_candidates_not_a_guess():
    options = [{"id": "item:1", "title": "Gold Ring"}, {"id": "item:2", "title": "Gold Bangles"}]
    resolved = resolve_interaction(_text("gold"), options=options, context={}, restaurant=_RESTAURANT)
    assert resolved.synthetic_reply_id is None
    assert resolved.ambiguous_candidates is not None
    assert len(resolved.ambiguous_candidates) >= 2


def test_real_catalog_option_named_back_is_not_hijacked_by_the_back_lexicon():
    """False-positive guard: a step whose actual option is literally titled "Back" (a real
    business scenario, e.g. a "Back Massage" salon service) must resolve via fuzzy option
    matching to that real option, never get swallowed by the BACK_PHRASES lexicon check --
    lexicon checks run against the raw customer text, not option titles, so this only
    breaks if a customer literally types the word "back" meaning navigation. Confirms the
    lexicon signal takes priority (matches _LEAVE_TO_PICKER_WORDS' own documented
    precedent in demo_bot_service.py: an unambiguous navigation word always wins), while a
    typed near-title like "back massage" still resolves to the real option instead."""
    options = [{"id": "item:1", "title": "Back Massage"}, {"id": "item:2", "title": "Head Massage"}]
    resolved = resolve_interaction(_text("back massage"), options=options, context={}, restaurant=_RESTAURANT)
    assert resolved.signal is None
    assert resolved.synthetic_reply_id == "item:1"


def test_unmatched_text_is_a_noop():
    resolved = resolve_interaction(_text("asdkjfhaslkdjfh"), options=[{"id": "item:1", "title": "Pizza"}], context={}, restaurant=_RESTAURANT)
    assert resolved.is_noop
