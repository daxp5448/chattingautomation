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

# --- conservative, rule-based input-safety data (see conversational_safety.py) -----------
#
# This is intentionally a small, conservative v1 safety net for a customer-facing demo --
# NOT an exhaustive moderation system. Every category below is matched by exact
# WORD-BOUNDARY TOKEN membership (see conversational_safety.py's _contains_word /
# _matches_any_combo) -- NEVER substring containment (a naive `"ass" in text` check would
# misfire on "assemble"/"class") and NEVER fuzzy/typo-tolerant matching.
#
# An earlier version of this module used fuzz.partial_ratio to catch a phrase embedded in
# a longer sentence (the same technique conversational_intent.py's own option-matching
# uses) -- confirmed BY DIRECT TESTING to false-positive on exactly the kind of ordinary
# query this platform exists to handle: "show me the menu" and "show me the catalog" both
# scored above threshold against "show me the database", because partial_ratio's
# character-level alignment scores two same-length phrases with a long shared prefix
# ("show me the ___") as very similar even when the one word that actually matters
# differs completely. Multi-word signals are therefore expressed here as REQUIRED TOKEN
# COMBINATIONS (every token in the set must be present somewhere in the message, in any
# order/position -- see TOKEN_COMBOS below) rather than a fuzzy-matched phrase string.
# This is strictly more precise: two unrelated words can never "average out" to a false
# match the way two fuzzy-scored strings can.
#
# Kept intentionally short and conservative: only words/combinations with no plausible
# legitimate meaning across any of this platform's 12 niches (restaurant/jewellery/salon/
# gym/hotel/real_estate/automobile/clinic/education/electronics/grocery/retail). Missing
# a real attempt just falls through to the existing safe "I didn't understand, please
# choose an option" fallback (Part 12's own behavior) -- an acceptable outcome, since a
# false positive that incorrectly refuses a legitimate customer is the worse failure mode.

# Category A: profanity/abusive language. Single-word signals -- unambiguous English +
# Hinglish curses only, nothing that could plausibly be a real word/brand/product/food
# name in any niche's catalog.
PROFANITY_WORDS = {
    "fuck", "fucking", "fucker", "motherfucker", "shit", "bullshit", "bitch",
    "asshole", "bastard", "dumbass", "idiot", "stupid", "moron",
    "chutiya", "madarchod", "behenchod", "bhosdike", "randi", "gandu", "harami",
}

# Category B: sexual/sexually explicit requests. Single-word signals -- excludes ordinary
# anatomical/medical terms a clinic niche could legitimately need.
SEXUAL_WORDS = {
    "sex", "sexy", "nude", "nudes", "naked", "porn", "pornhub", "blowjob",
    "boobs", "hookup", "sexting",
}

# Category C: harassment/threats toward staff. Each entry is a set of tokens that must
# ALL be present -- the threat is in the COMBINATION, never a single word alone (a bare
# "kill" is too collision-prone; "kill" + "you" together, in a short customer message,
# realistically never means anything else). Deliberately excludes anything a genuine
# commerce message could say on its own, e.g. "I'll pay for this" -- dropped from an
# earlier draft of this list for exactly that reason.
THREAT_TOKEN_COMBOS: list[set[str]] = [
    {"kill", "you"}, {"hurt", "you"}, {"beat", "you"}, {"destroy", "business"},
    {"know", "where", "live"}, {"maar", "dunga"}, {"dekh", "lunga"}, {"chhodunga"},
]

# Category G+H: prompt-injection attempts and credential/internal-info requests -- merged
# into one category since both get the same "I can't share that, here's the business
# flow" response (see conversational_safety.py).
PROMPT_INJECTION_TOKEN_COMBOS: list[set[str]] = [
    {"ignore", "instructions"}, {"disregard", "instructions"}, {"forget", "instructions"},
    {"system", "prompt"}, {"internal", "rules"}, {"admin", "access"},
    {"reveal", "token"}, {"access", "token"}, {"api", "key"},
    {"show", "database"}, {"access", "database"}, {"developer", "mode"},
    {"no", "restrictions"},
]

# Category I: requests for another customer's private information.
#
# An earlier draft required just one generic "whose data" word (e.g. "another"/"other")
# together with one generic "what data" word (e.g. "order") -- confirmed BY DIRECT
# TESTING to false-positive on "I want to place ANOTHER ORDER", an extremely ordinary
# repeat-customer phrase that has nothing to do with anyone else's data at all ("another"
# alone just means "one more", not "someone else's"). Token combos below are deliberately
# more specific: "customers" (plural, i.e. OTHER customers, not "my own account") or the
# distinctly non-generic "elses" token (only ever appears from "someone else's"/"anyone
# else's" -- not a standalone English word any legitimate query would otherwise produce).
OTHER_CUSTOMER_DATA_TOKEN_COMBOS: list[set[str]] = [
    {"another", "customers"}, {"other", "customers"}, {"elses"},
    {"everyones", "orders"}, {"everyones", "details"}, {"everyones", "addresses"},
]

# Category F: requests for something illegal/dangerous this business could never
# legitimately provide -- deliberately a very small, unambiguous set (this is not a
# general-purpose illegal-content classifier, just a narrow refusal for the clearest
# cases; anything less clear-cut falls through to the normal unsupported-input fallback).
ILLEGAL_OR_DANGEROUS_TOKEN_COMBOS: list[set[str]] = [
    {"sell", "drugs"}, {"buy", "drugs"}, {"get", "drugs"},
    {"sell", "weapon"}, {"sell", "gun"}, {"buy", "gun"},
    {"make", "bomb"}, {"build", "bomb"}, {"hurt", "someone"},
]
