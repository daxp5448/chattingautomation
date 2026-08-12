from datetime import datetime, timezone

from app.models.invoice_counter import RestaurantInvoiceCounter
from app.models.restaurant import Restaurant
from app.services.invoice_numbering import _current_financial_year, assign_invoice_number


async def _make_restaurant(db_session, slug: str) -> Restaurant:
    restaurant = Restaurant(name=slug, slug=slug)
    db_session.add(restaurant)
    await db_session.flush()
    return restaurant


def test_current_financial_year_boundaries():
    # April 1 starts a new FY...
    assert _current_financial_year(datetime(2026, 4, 1, tzinfo=timezone.utc)) == "2026-27"
    # ...and March 31 is still the *previous* FY.
    assert _current_financial_year(datetime(2026, 3, 31, tzinfo=timezone.utc)) == "2025-26"
    assert _current_financial_year(datetime(2027, 1, 15, tzinfo=timezone.utc)) == "2026-27"


async def test_two_orders_same_restaurant_get_consecutive_invoice_numbers(db_session):
    restaurant = await _make_restaurant(db_session, "invoice-diner-a")

    first = await assign_invoice_number(db_session, restaurant.id)
    second = await assign_invoice_number(db_session, restaurant.id)
    await db_session.commit()

    fy = _current_financial_year()
    assert first == f"INV-{fy}-00001"
    assert second == f"INV-{fy}-00002"


async def test_different_restaurants_do_not_conflict_on_numbering(db_session):
    restaurant_a = await _make_restaurant(db_session, "invoice-diner-b")
    restaurant_b = await _make_restaurant(db_session, "invoice-diner-c")

    a_number = await assign_invoice_number(db_session, restaurant_a.id)
    b_number = await assign_invoice_number(db_session, restaurant_b.id)
    a_second_number = await assign_invoice_number(db_session, restaurant_a.id)
    await db_session.commit()

    fy = _current_financial_year()
    # Both restaurants independently start at 1 within the same FY -- restaurant_b's
    # first invoice does not observe/consume restaurant_a's sequence.
    assert a_number == f"INV-{fy}-00001"
    assert b_number == f"INV-{fy}-00001"
    assert a_second_number == f"INV-{fy}-00002"


async def test_previous_financial_year_counter_does_not_leak_into_current_year(db_session):
    """A financial-year rollover must produce a fresh sequence starting at 1, proven here
    by directly seeding a stale counter row for a different financial_year (rather than
    mocking the clock) and confirming it has no effect on the current FY's sequence."""
    restaurant = await _make_restaurant(db_session, "invoice-diner-d")

    stale_counter = RestaurantInvoiceCounter(
        restaurant_id=restaurant.id, financial_year="2000-01", next_number=42
    )
    db_session.add(stale_counter)
    await db_session.commit()

    number = await assign_invoice_number(db_session, restaurant.id)
    await db_session.commit()

    fy = _current_financial_year()
    assert number == f"INV-{fy}-00001"
