import uuid
from datetime import datetime, timezone

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice_counter import RestaurantInvoiceCounter

# Substring markers used to recognise "this IntegrityError is the uq_invoice_counter_restaurant_fy
# unique-constraint firing" (as opposed to some other integrity failure that should propagate)
# across SQLite (used by the test suite) and Postgres (production), which phrase constraint
# violations differently -- same approach as
# app/services/order_service.py::_is_order_number_collision.
_COUNTER_COLLISION_MARKERS = ("uq_invoice_counter_restaurant_fy", "restaurant_invoice_counters")


def _current_financial_year(now: datetime | None = None) -> str:
    """Indian financial year: April 1 - March 31. A date in Apr 2026 - Mar 2027 is FY
    "2026-27"; a date in Jan-Mar 2026 is still FY "2025-26"."""
    now = now or datetime.now(timezone.utc)
    start_year = now.year if now.month >= 4 else now.year - 1
    return f"{start_year}-{str(start_year + 1)[-2:]}"


def _is_counter_collision(exc: IntegrityError) -> bool:
    message = str(exc.orig or exc).lower()
    return any(marker in message for marker in _COUNTER_COLLISION_MARKERS)


async def assign_invoice_number(session: AsyncSession, restaurant_id: uuid.UUID) -> str:
    """Atomically allocates the next sequential GST invoice number for `restaurant_id`
    within the current Indian financial year, formatted as
    "INV-{financial_year}-{next_number:05d}", e.g. "INV-2026-27-00001".

    Race-safe get-or-create-and-increment against `restaurant_invoice_counters`:
      1. Try `UPDATE ... SET next_number = next_number + 1 WHERE (restaurant_id, financial_year)
         = ... RETURNING next_number` -- atomic at the DB level, so two concurrent callers
         for the same restaurant+FY never get the same number.
      2. If that UPDATE matches no row (first invoice this restaurant has issued this FY),
         INSERT a fresh counter row seeded at next_number=2 and use 1 for this invoice.
      3. If two concurrent callers both hit step 2 for the very first invoice of a
         restaurant+FY, only one INSERT wins the unique constraint on
         (restaurant_id, financial_year); the loser catches the IntegrityError and retries
         from step 1, which now finds the winner's row. Mirrors the collision-retry pattern
         in app/services/order_service.py::create_order_from_cart for order_number.

    Intended usage: call and let the caller commit this as part of the SAME DB transaction
    as order confirmation, e.g. `order.invoice_number = await assign_invoice_number(session,
    restaurant.id)` -- deliberately independent of PDF generation/upload, so a confirmed
    order always gets a permanent, real sequential invoice number even if the PDF/S3 upload
    step afterward fails.
    """
    financial_year = _current_financial_year()

    for _attempt in range(3):
        stmt = (
            update(RestaurantInvoiceCounter)
            .where(
                RestaurantInvoiceCounter.restaurant_id == restaurant_id,
                RestaurantInvoiceCounter.financial_year == financial_year,
            )
            .values(next_number=RestaurantInvoiceCounter.next_number + 1)
            .returning(RestaurantInvoiceCounter.next_number)
        )
        result = await session.execute(stmt)
        row = result.first()
        if row is not None:
            # next_number was just incremented from N to N+1 by the UPDATE above; this
            # invoice gets N.
            assigned_number = row[0] - 1
            return f"INV-{financial_year}-{assigned_number:05d}"

        # No counter row yet for this (restaurant, financial_year) -- create one. This
        # invoice becomes number 1, so the row is seeded at 2 for the *next* caller.
        counter = RestaurantInvoiceCounter(
            restaurant_id=restaurant_id, financial_year=financial_year, next_number=2
        )
        try:
            # A SAVEPOINT, not a full rollback: on IntegrityError only this attempt's
            # insert is undone, leaving the rest of the caller's in-progress transaction
            # (e.g. the order row already added earlier in the same request) intact.
            async with session.begin_nested():
                session.add(counter)
                await session.flush()
            return f"INV-{financial_year}-{1:05d}"
        except IntegrityError as exc:
            if not _is_counter_collision(exc):
                raise
            continue

    raise RuntimeError(f"Could not assign an invoice number for restaurant {restaurant_id} after multiple attempts")
