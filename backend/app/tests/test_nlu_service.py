import uuid

from app.models.faq import FaqEntry
from app.models.product import Product
from app.services import nlu_service


def _product(name, price, tags, available=True):
    return Product(
        id=uuid.uuid4(),
        restaurant_id=uuid.uuid4(),
        category_id=uuid.uuid4(),
        name=name,
        price=price,
        tags=tags,
        available=available,
    )


def _faq(keywords, answer, active=True):
    return FaqEntry(id=uuid.uuid4(), restaurant_id=uuid.uuid4(), trigger_keywords=keywords, answer=answer, is_active=active)


def test_matches_products_by_tag_and_price_ceiling():
    products = [
        _product("Fiery Wings", 350, ["spicy"]),
        _product("Volcano Burger", 500, ["spicy"]),
        _product("Plain Rice", 100, []),
    ]
    result = nlu_service.match_products(products, "something spicy under 400", "INR")
    assert result is not None
    assert "Fiery Wings" in result
    assert "Volcano Burger" not in result  # over the price ceiling


def test_no_product_match_when_query_not_food_related():
    products = [_product("Fiery Wings", 350, ["spicy"])]
    assert nlu_service.match_products(products, "what time do you open", "INR") is None


def test_unavailable_products_excluded():
    products = [_product("Fiery Wings", 350, ["spicy"], available=False)]
    assert nlu_service.match_products(products, "something spicy", "INR") is None


def test_faq_keyword_match_renders_template():
    entries = [_faq(["jain"], "We offer Jain options at {{restaurant_name}}.")]
    result = nlu_service.match_faq(entries, "what is jain food?", {"restaurant_name": "Test Diner"})
    assert result == "We offer Jain options at Test Diner."


def test_faq_no_match_returns_none():
    entries = [_faq(["jain"], "answer")]
    assert nlu_service.match_faq(entries, "completely unrelated text", {}) is None


def test_inactive_faq_entry_ignored():
    entries = [_faq(["jain"], "answer", active=False)]
    assert nlu_service.match_faq(entries, "what is jain", {}) is None


def test_match_falls_back_to_faq_when_no_product_hit():
    products = [_product("Plain Rice", 100, [])]
    faqs = [_faq(["delivery time"], "We deliver in 30-45 mins.")]
    result = nlu_service.match(products, faqs, "what's your delivery time?", "INR", {})
    assert result == "We deliver in 30-45 mins."


def test_match_returns_none_when_nothing_matches():
    assert nlu_service.match([], [], "asdkjhaskjdh random gibberish", "INR", {}) is None
