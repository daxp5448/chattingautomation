"""Static English + Hinglish surface-form data for conversational_intent.py's rule-based
free-text intent detection -- data only, no logic, so the phrase lists can grow without
touching any matching code. Deliberately NOT niche-specific: every set here is generic
across all 12 niches (a niche's own vocabulary is matched separately, against that
niche's own catalog/option titles, by conversational_intent.py's fuzzy-matching step).

Real vocabulary a niche's own catalog legitimately uses (e.g. an automobile business
selling a physical "switch", or an item literally named "Back") must never collide with
these -- see generic_flow_engine.py's own _LEAVE_TO_PICKER_WORDS docstring in
demo_bot_service.py for the exact prior incident this guards against. Kept short and
deliberately unambiguous rather than exhaustive for that reason.
"""

# "Take me back one step" -- synthesizes BACK_REPLY_ID (see generic_flow_engine.py),
# reusing the existing Back-button code path verbatim rather than a new one.
BACK_PHRASES = {
    "back", "go back", "previous", "wapas", "peeche", "peeche jao",
}

# "Start this whole conversation over" -- folded into the same code path as
# _looks_like_greeting (see generic_flow_engine.py), never a separate reset mechanism.
RESTART_PHRASES = {
    "start again", "start over", "restart", "reset", "shuru se", "phir se shuru",
}

# "I want to change the quantity I already gave" -- routes back to the nearest
# quantity_input step via existing back_target/routes data, never a hardcoded step id.
CHANGE_QTY_PHRASES = {
    "change quantity", "change qty", "different quantity", "quantity badlo",
    "matra badlo",
}

# "Show me more of what I'm already looking at" -- re-paginates the current step's
# already-resolved options, never invents a new one.
SHOW_MORE_PHRASES = {
    "show more", "more options", "anything else", "aur dikhao", "aur options",
    "kuch aur",
}

# "Show me lower-priced options among what I'm already looking at" -- re-sorts the
# current step's already-resolved (real, already-fetched) options by price, ascending.
CHEAPER_PHRASES = {
    "cheaper", "anything cheaper", "something cheaper", "lower price", "sasta",
    "kuch sasta", "kam price", "kam daam",
}

# Honesty rule (spec section 27): answered with one fixed, honest disclosure line --
# never pretend to be human, never ignore the question.
IS_BOT_PHRASES = {
    "are you a bot", "are you human", "are you real", "is this a bot",
    "kya tum bot ho", "tum robot ho kya", "real insaan ho",
}

# Stripped from free text before fuzzy-matching it against a lexicon phrase or a step's
# option titles, so filler words don't dilute the match score (e.g. "bhai ring dikhana"
# should score against "ring dikhana"/"rings", not the full four-word string).
FILLER_WORDS = {"bhai", "yaar", "please", "pls", "plz", "hi", "hello"}

# Match-confidence thresholds, same style/magnitude as nlu_service.py's
# _FAQ_MATCH_THRESHOLD/_PRODUCT_MATCH_THRESHOLD (rapidfuzz scores are 0-100).
INTENT_MATCH_THRESHOLD = 80  # lexicon phrase override -- high bar, these change navigation
OPTION_MATCH_THRESHOLD = 65  # free text vs. the current step's own option titles
AMBIGUOUS_MARGIN = 8  # top-two option scores this close -> ask, don't guess
