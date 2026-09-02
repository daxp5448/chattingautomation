"""Rule-based (no LLM) free-text intent resolution for generic_flow_engine.py's
handle(). Pure functions only -- no DB/session access, no niche awareness beyond the
`options`/`context` dicts already resolved by the caller. Its ONE job: decide whether a
free-text message should be treated as if the customer had tapped a specific button
(`synthetic_reply_id`), typed a recognized command word ("back"/"restart"/"change
quantity"/"show more"/"cheaper" -- `signal`), asked "are you a bot?" (`is_bot_query`), or
is genuinely ambiguous between two-or-more real options (`ambiguous_candidates`) -- so
every existing per-step-type branch in generic_flow_engine.py keeps working completely
unchanged. Never invents an option that isn't already in `options`; when nothing matches
confidently, returns an untouched result and the caller's existing "invalid input, please
pick again" path is the correct, safe fallback.
"""

import re
from dataclasses import dataclass
from typing import Any

from rapidfuzz import fuzz

from app.services import conversation_lexicon as lex

_NON_WORD = re.compile(r"[^a-z0-9\s]")


@dataclass
class ResolvedInteraction:
    synthetic_reply_id: str | None = None
    signal: str | None = None  # "back" | "restart" | "change_qty" | "show_more" | "cheaper"
    ambiguous_candidates: list[dict[str, Any]] | None = None
    is_bot_query: bool = False

    @property
    def is_noop(self) -> bool:
        return (
            self.synthetic_reply_id is None
            and self.signal is None
            and self.ambiguous_candidates is None
            and not self.is_bot_query
        )


def _normalize(text: str) -> str:
    """Lowercase, strip emoji/punctuation, drop filler words -- so "Bhai, Ring dikhana!"
    and "ring dikhana" score the same against both a lexicon phrase and an option title."""
    cleaned = _NON_WORD.sub(" ", text.lower())
    words = [w for w in cleaned.split() if w not in lex.FILLER_WORDS]
    return " ".join(words).strip()


def _best_phrase_score(normalized: str, phrases: set[str]) -> float:
    if not normalized:
        return 0.0
    return max((fuzz.token_sort_ratio(normalized, phrase) for phrase in phrases), default=0.0)


def resolve_interaction(
    interaction, options: list[dict[str, Any]], context: dict[str, Any], restaurant
) -> ResolvedInteraction:
    # A real button/list tap already carries a real reply_id -- never second-guess it.
    if interaction.reply_id:
        return ResolvedInteraction()
    if interaction.kind != "text" or not (interaction.text or "").strip():
        return ResolvedInteraction()

    normalized = _normalize(interaction.text)
    if not normalized:
        return ResolvedInteraction()

    if _best_phrase_score(normalized, lex.IS_BOT_PHRASES) >= lex.INTENT_MATCH_THRESHOLD:
        return ResolvedInteraction(is_bot_query=True)

    for signal, phrases in (
        ("back", lex.BACK_PHRASES),
        ("restart", lex.RESTART_PHRASES),
        ("change_qty", lex.CHANGE_QTY_PHRASES),
        ("show_more", lex.SHOW_MORE_PHRASES),
        ("cheaper", lex.CHEAPER_PHRASES),
    ):
        if _best_phrase_score(normalized, phrases) >= lex.INTENT_MATCH_THRESHOLD:
            return ResolvedInteraction(signal=signal)

    if not options:
        return ResolvedInteraction()

    # partial_ratio (not token_sort_ratio) -- same choice nlu_service.py already makes for
    # this exact problem shape: a short, possibly Hinglish/typo'd customer phrase that
    # only PARTIALLY overlaps a longer option title ("ring dikhana" vs "Rings"), rather
    # than two strings of comparable length differing mainly in word order.
    scored = sorted(
        (
            (fuzz.partial_ratio(normalized, _normalize(opt.get("title", ""))), opt)
            for opt in options
        ),
        key=lambda pair: pair[0],
        reverse=True,
    )
    if not scored or scored[0][0] < lex.OPTION_MATCH_THRESHOLD:
        return ResolvedInteraction()

    top_score = scored[0][0]
    close = [opt for score, opt in scored if top_score - score <= lex.AMBIGUOUS_MARGIN]
    if len(close) == 1:
        return ResolvedInteraction(synthetic_reply_id=close[0]["id"])
    return ResolvedInteraction(ambiguous_candidates=close[:3])
