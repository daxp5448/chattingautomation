"""Conservative, rule-based (no LLM) safety classification for free-text customer
messages -- a small v1 safety net for the live WhatsApp bot conversation, not a general
content-moderation system. Sibling of conversational_intent.py (same "pure functions,
no DB access" shape), called from the same place in generic_flow_engine.py::handle().

Design principle, straight from the spec this exists for: "False positives are worse
than asking for clarification." Every category below is checked with a narrow,
conservative rule, and anything not confidently classified falls through untouched --
the caller's existing "I didn't understand that, please choose an option" fallback is
the correct, safe default, not a gap this module needs to fill.

What this deliberately does NOT try to do:
  - Detect "spam / repeated nonsense" (would need session-level message-history tracking,
    a genuinely new stateful mechanism -- out of scope for a v1 safety net).
  - Detect "completely unrelated" requests (e.g. "what's today's cricket score") as its
    own category -- these already fall through to the existing unmatched-input fallback
    (Part 12's own desired behavior), which requires no new detection logic at all.
  - Detect "requests the business cannot fulfill" as its own category -- same reasoning:
    anything that doesn't match a real option already gets the existing safe fallback.
  - Any kind of fuzzy/typo-tolerant matching, for any category -- word-boundary exact
    token matching only (see conversation_lexicon.py's own module docstring for a
    concrete false positive this deliberately avoids: fuzzy phrase-matching once scored
    "show me the menu" as a near-match for "show me the database" purely from their
    shared prefix). Exact tokens can miss an obfuscated/typo'd attempt, which is an
    accepted trade-off -- see the "false positives are worse" principle above.
"""

import re
from dataclasses import dataclass

from app.services import conversation_lexicon as lex

_WORD_TOKEN = re.compile(r"[a-z0-9]+")


class UnsafeCategory:
    """String constants, not an enum -- kept as plain strings so a niche-aware caller can
    log/branch on them without an extra import, matching ResolvedInteraction.signal's own
    plain-string convention in conversational_intent.py."""

    PROFANITY = "profanity"
    SEXUAL = "sexual"
    THREAT = "threat"
    PROMPT_INJECTION_OR_CREDENTIALS = "prompt_injection_or_credentials"
    OTHER_CUSTOMER_DATA = "other_customer_data"
    ILLEGAL_OR_DANGEROUS = "illegal_or_dangerous"


@dataclass
class SafetyResult:
    category: str | None = None

    @property
    def is_unsafe(self) -> bool:
        return self.category is not None


def _word_tokens(normalized_text: str) -> set[str]:
    return set(_WORD_TOKEN.findall(normalized_text))


def _contains_word(tokens: set[str], words: set[str]) -> bool:
    """Exact word-boundary membership only -- never `word in text` substring containment
    (that would misfire on e.g. "assemble"/"class"), never fuzzy (a short word fuzzy-
    matching a real product/food/medical term is exactly the false-positive risk this
    whole module exists to avoid)."""
    return not tokens.isdisjoint(words)


def _matches_any_combo(tokens: set[str], combos: list[set[str]]) -> bool:
    """A combo matches when EVERY token in it is present somewhere in the message (any
    order/position) -- exact word-boundary containment, no fuzzy scoring at all. This is
    what replaced an earlier fuzz.partial_ratio-based design: partial_ratio's character-
    level alignment scored "show me the menu" as a near-match for "show me the database"
    purely because of their long shared prefix, a real false positive confirmed by direct
    testing. Exact token-set containment can't fail that way -- "database" is either
    literally one of the words the customer typed, or it isn't."""
    return any(combo.issubset(tokens) for combo in combos)


def classify(normalized_text: str) -> SafetyResult:
    """`normalized_text` must already be conversational_intent.py's `_normalize()` output
    (lowercased, punctuation stripped, filler words dropped) -- this module never imports
    that private helper to avoid a circular import; callers already have the normalized
    string on hand from their own lexicon checks. Returns the FIRST matching category in
    a fixed, deliberate priority order (threats and injection/credential attempts checked
    before milder categories), never more than one.
    """
    if not normalized_text:
        return SafetyResult()

    tokens = _word_tokens(normalized_text)

    if _matches_any_combo(tokens, lex.THREAT_TOKEN_COMBOS):
        return SafetyResult(UnsafeCategory.THREAT)

    if _matches_any_combo(tokens, lex.PROMPT_INJECTION_TOKEN_COMBOS):
        return SafetyResult(UnsafeCategory.PROMPT_INJECTION_OR_CREDENTIALS)

    if _matches_any_combo(tokens, lex.OTHER_CUSTOMER_DATA_TOKEN_COMBOS):
        return SafetyResult(UnsafeCategory.OTHER_CUSTOMER_DATA)

    if _matches_any_combo(tokens, lex.ILLEGAL_OR_DANGEROUS_TOKEN_COMBOS):
        return SafetyResult(UnsafeCategory.ILLEGAL_OR_DANGEROUS)

    if _contains_word(tokens, lex.SEXUAL_WORDS):
        return SafetyResult(UnsafeCategory.SEXUAL)

    if _contains_word(tokens, lex.PROFANITY_WORDS):
        return SafetyResult(UnsafeCategory.PROFANITY)

    return SafetyResult()


# Fixed, honest, non-escalating response lines -- same "never LLM-generated, never
# claims something untrue" principle as generic_flow_engine.py's own IS_BOT_PHRASES
# disclosure line. Deliberately NOT run through conversational_style.humanize(): a
# tone/emoji layer is exactly wrong for a boundary-setting message, especially for
# THREAT/OTHER_CUSTOMER_DATA. Calm, short, professional -- never insults the customer,
# never escalates, never explains WHY the rule exists (that would itself leak internal
# reasoning to a prompt-injection attempt).
_SAFETY_RESPONSES: dict[str, str] = {
    UnsafeCategory.PROFANITY: "I'm here to help with your request. Please keep the conversation respectful. 🙂",
    UnsafeCategory.SEXUAL: "I can help with our available services and products. Please choose an option below.",
    UnsafeCategory.THREAT: (
        "I'm not able to continue with messages like that. I'm here to help with our "
        "products and services -- please choose an option below."
    ),
    UnsafeCategory.PROMPT_INJECTION_OR_CREDENTIALS: (
        "I can help with this business's services and products. Please choose an option below."
    ),
    UnsafeCategory.OTHER_CUSTOMER_DATA: (
        "I'm not able to share another customer's information. I can help with your own "
        "order or enquiry -- please choose an option below."
    ),
    UnsafeCategory.ILLEGAL_OR_DANGEROUS: (
        "I'm not able to help with that request. I can help with our available services "
        "-- please choose an option below."
    ),
}


def response_for(category: str) -> str:
    return _SAFETY_RESPONSES.get(category, _SAFETY_RESPONSES[UnsafeCategory.PROMPT_INJECTION_OR_CREDENTIALS])
