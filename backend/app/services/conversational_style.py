"""Outbound phrasing layer for generic_flow_engine.py's _render_step(). Pure string
transforms only -- operates on an already-fully-composed prompt string (real catalog
data/prices/{{variables}} already substituted by the caller), never fabricates a fact,
price, or emoji the template didn't already contain. No-ops entirely when a restaurant
hasn't configured `conversation_settings` (empty dict), so every tenant that hasn't
opted in sees zero behavior change.
"""

import re

_EMOJI_PATTERN = re.compile(
    "["
    "\U0001F300-\U0001FAFF"
    "\U00002600-\U000027BF"
    "\U0001F1E6-\U0001F1FF"
    "\U00002190-\U000021FF"
    "\U00002B00-\U00002BFF"
    "]+",
    flags=re.UNICODE,
)

# Acknowledgement phrase pools, keyed by the `tone` value each niche_seeds/*.py module
# sets in its `default_personality` -- see app/models/niche_template.py's
# default_personality docstring. A tenant can freely set any custom tone string via its
# own conversation_settings; an unrecognized tone just gets no acknowledgement prefix
# (safe no-op, never a KeyError).
_ACKNOWLEDGEMENT_POOLS: dict[str, list[str]] = {
    "friendly_casual": ["Sure thing!", "Got it 👍", "On it!", "Sounds good!"],
    "premium_elegant": ["Certainly.", "Of course.", "Right away."],
    "professional_calm": ["Understood.", "Noted.", "Sure, one moment."],
    "energetic_motivating": ["Let's go! 💪", "You got it!", "Awesome, let's do this!"],
    "hospitality_polished": ["Absolutely.", "With pleasure.", "Right away."],
    "professional_informative": ["Sure.", "Got it.", "Understood."],
    "helpful_encouraging": ["Great question!", "Sure!", "Happy to help!"],
    "knowledgeable_practical": ["Sure.", "Got it.", "No problem."],
    "simple_quick_convenient": ["Sure!", "Got it 👍", "On it!"],
    "friendly_style_focused": ["Love that!", "Great choice!", "Sure thing!"],
    "warm_friendly_conversational": ["Of course 😊", "Sure!", "No worries!"],
    "professional_trustworthy": ["Sure.", "Understood.", "Noted."],
}


def _pick_acknowledgement(tone: str, seed_key: str) -> str | None:
    pool = _ACKNOWLEDGEMENT_POOLS.get(tone)
    if not pool:
        return None
    return pool[hash(seed_key) % len(pool)]


def _apply_emoji_level(text: str, emoji_level: str) -> str:
    if emoji_level == "high" or not emoji_level:
        return text
    if emoji_level == "none":
        return re.sub(r"\s+", " ", _EMOJI_PATTERN.sub("", text)).strip()
    if emoji_level == "low":
        seen = False

        def _keep_first(match: re.Match) -> str:
            nonlocal seen
            if seen:
                return ""
            seen = True
            return match.group(0)

        return re.sub(r"\s+", " ", _EMOJI_PATTERN.sub(_keep_first, text)).strip()
    return text


def _apply_response_length(text: str, response_length: str) -> str:
    if response_length != "short":
        return text
    blocks = text.split("\n\n")
    return blocks[0] if blocks else text


def humanize(
    prompt: str,
    restaurant,
    seed_key: str,
    is_reprompt: bool = False,
    is_entry_step: bool = False,
) -> str:
    settings = restaurant.conversation_settings or {}
    if not settings:
        return prompt

    result = prompt
    # No acknowledgement on the very first message of a session (nothing to acknowledge
    # yet) or on a re-render after unrecognized input ("Sorry, please pick one of the
    # options below" already carries its own tone -- stacking "Sure!" on top of it reads
    # wrong, not more natural).
    if not is_reprompt and not is_entry_step:
        ack = _pick_acknowledgement(settings.get("tone", ""), seed_key)
        if ack:
            result = f"{ack} {result}"

    result = _apply_emoji_level(result, settings.get("emoji_level", "high"))
    result = _apply_response_length(result, settings.get("response_length", "normal"))
    return result
