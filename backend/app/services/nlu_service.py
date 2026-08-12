import re
from typing import Any

from rapidfuzz import fuzz

from app.models.faq import FaqEntry
from app.models.product import Product
from app.services.template_engine import render_template

_PRICE_CEILING_PATTERN = re.compile(r"under\s*(?:rs\.?|inr|₹)?\s*(\d+)", re.IGNORECASE)
_DIET_TAG_KEYWORDS = [
    "spicy",
    "veg",
    "vegan",
    "jain",
    "healthy",
    "kids",
    "chef special",
    "best seller",
    "popular",
    "recommended",
]

_FAQ_MATCH_THRESHOLD = 70
_PRODUCT_MATCH_THRESHOLD = 60
_MAX_PRODUCT_SUGGESTIONS = 5


def _extract_price_ceiling(text: str) -> float | None:
    match = _PRICE_CEILING_PATTERN.search(text)
    return float(match.group(1)) if match else None


def _looks_like_product_query(text: str) -> bool:
    lowered = text.lower()
    return _extract_price_ceiling(text) is not None or any(kw in lowered for kw in _DIET_TAG_KEYWORDS)


def match_products(products: list[Product], text: str, currency: str) -> str | None:
    if not _looks_like_product_query(text):
        return None

    lowered = text.lower()
    price_ceiling = _extract_price_ceiling(text)
    candidates: list[tuple[float, Product]] = []

    for product in products:
        if not product.available:
            continue
        effective_price = float(product.discount_price or product.price)
        if price_ceiling is not None and effective_price > price_ceiling:
            continue
        haystack = " ".join([product.name, *(product.tags or [])]).lower()
        score = fuzz.partial_ratio(lowered, haystack)
        if score >= _PRODUCT_MATCH_THRESHOLD:
            candidates.append((score, product))

    if not candidates:
        return None

    candidates.sort(key=lambda c: c[0], reverse=True)
    lines = [
        f"- {p.name} ({currency} {p.discount_price or p.price})" for _, p in candidates[:_MAX_PRODUCT_SUGGESTIONS]
    ]
    return "Here's what I found:\n" + "\n".join(lines)


def match_faq(faq_entries: list[FaqEntry], text: str, context: dict[str, Any]) -> str | None:
    lowered = text.lower()
    best_entry: FaqEntry | None = None
    best_score = 0.0

    for entry in faq_entries:
        if not entry.is_active:
            continue
        for keyword in entry.trigger_keywords:
            score = fuzz.partial_ratio(lowered, keyword.lower())
            if score > best_score:
                best_score = score
                best_entry = entry

    if best_entry and best_score >= _FAQ_MATCH_THRESHOLD:
        return render_template(best_entry.answer, context)
    return None


def match(
    products: list[Product], faq_entries: list[FaqEntry], text: str, currency: str, context: dict[str, Any]
) -> str | None:
    """Rule-based free-text matching: product/tag lookup first, then FAQ keywords.
    Returns None when nothing matches well enough -- the caller treats that as a
    signal to hand the conversation over to a human instead of guessing.
    """
    return match_products(products, text, currency) or match_faq(faq_entries, text, context)
