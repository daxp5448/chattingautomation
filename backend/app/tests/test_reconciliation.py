from datetime import timedelta

import pytest
from sqlalchemy import select

from app.db.base import utcnow
from app.models.customer import Customer
from app.models.enums import PaymentMethod, PaymentStatus
from app.models.order import Order
from app.models.restaurant import Restaurant
from app.services.payment.razorpay import RazorpayGateway
from app.tasks.reconciliation import STUCK_THRESHOLD_MINUTES, _check_stuck_payments

OLD_ENOUGH = timedelta(minutes=STUCK_THRESHOLD_MINUTES + 5)
NOT_OLD_ENOUGH = timedelta(minutes=STUCK_THRESHOLD_MINUTES - 5)


@pytest.fixture
async def tenant(db_session):
    restaurant = Restaurant(name="Recon Test", slug="recon-test")
    db_session.add(restaurant)
    await db_session.flush()

    customer = Customer(restaurant_id=restaurant.id, phone="911234567890")
    db_session.add(customer)
    await db_session.commit()

    return restaurant, customer


def _make_order(restaurant, customer, *, order_number, age, payment_status=PaymentStatus.PENDING, payment_method=PaymentMethod.RAZORPAY):
    return Order(
        restaurant_id=restaurant.id,
        branch_id=restaurant.id,  # no real Branch row needed -- FK not enforced under SQLite here, matches test_loyalty_service.py
        customer_id=customer.id,
        order_number=order_number,
        total=250,
        payment_status=payment_status,
        payment_method=payment_method,
        created_at=utcnow() - age,
    )


async def test_stuck_order_marked_paid_on_success_status(db_session, tenant, monkeypatch):
    restaurant, customer = tenant
    order = _make_order(restaurant, customer, order_number="R1", age=OLD_ENOUGH)
    db_session.add(order)
    await db_session.commit()

    async def fake_check_payment_status(self, order):
        return "paid"

    monkeypatch.setattr(RazorpayGateway, "check_payment_status", fake_check_payment_status, raising=False)
    order_id = order.id

    resolved = await _check_stuck_payments()

    assert resolved == 1
    # The reconciliation task commits via its own DB session (AsyncSessionLocal()), so the
    # test's db_session identity map is holding a stale copy of `order` -- expire it first
    # so the re-query below actually reflects what was persisted. (order_id was captured
    # above, before expiring, since accessing an expired attribute outside an `await`
    # triggers an implicit sync lazy-load that AsyncSession can't perform -- MissingGreenlet.)
    db_session.expire_all()
    refreshed = (await db_session.execute(select(Order).where(Order.id == order_id))).scalar_one()
    assert refreshed.payment_status == PaymentStatus.PAID


async def test_stuck_order_marked_failed_on_failure_status(db_session, tenant, monkeypatch):
    restaurant, customer = tenant
    order = _make_order(restaurant, customer, order_number="R2", age=OLD_ENOUGH)
    db_session.add(order)
    await db_session.commit()

    async def fake_check_payment_status(self, order):
        return "expired"

    monkeypatch.setattr(RazorpayGateway, "check_payment_status", fake_check_payment_status, raising=False)
    order_id = order.id

    resolved = await _check_stuck_payments()

    assert resolved == 1
    db_session.expire_all()
    refreshed = (await db_session.execute(select(Order).where(Order.id == order_id))).scalar_one()
    assert refreshed.payment_status == PaymentStatus.FAILED


async def test_still_pending_status_leaves_order_untouched(db_session, tenant, monkeypatch):
    restaurant, customer = tenant
    order = _make_order(restaurant, customer, order_number="R3", age=OLD_ENOUGH)
    db_session.add(order)
    await db_session.commit()

    async def fake_check_payment_status(self, order):
        return "created"

    monkeypatch.setattr(RazorpayGateway, "check_payment_status", fake_check_payment_status, raising=False)
    order_id = order.id

    resolved = await _check_stuck_payments()

    assert resolved == 0
    db_session.expire_all()
    refreshed = (await db_session.execute(select(Order).where(Order.id == order_id))).scalar_one()
    assert refreshed.payment_status == PaymentStatus.PENDING


async def test_recent_order_not_checked(db_session, tenant, monkeypatch):
    restaurant, customer = tenant
    order = _make_order(restaurant, customer, order_number="R4", age=NOT_OLD_ENOUGH)
    db_session.add(order)
    await db_session.commit()

    calls = []

    async def fake_check_payment_status(self, order):
        calls.append(order.id)
        return "paid"

    monkeypatch.setattr(RazorpayGateway, "check_payment_status", fake_check_payment_status, raising=False)

    resolved = await _check_stuck_payments()

    assert resolved == 0
    assert calls == []


async def test_non_razorpay_order_not_checked(db_session, tenant, monkeypatch):
    restaurant, customer = tenant
    order = _make_order(restaurant, customer, order_number="R5", age=OLD_ENOUGH, payment_method=PaymentMethod.COD)
    db_session.add(order)
    await db_session.commit()

    calls = []

    async def fake_check_payment_status(self, order):
        calls.append(order.id)
        return "paid"

    monkeypatch.setattr(RazorpayGateway, "check_payment_status", fake_check_payment_status, raising=False)

    resolved = await _check_stuck_payments()

    assert resolved == 0
    assert calls == []


async def test_already_resolved_order_not_checked(db_session, tenant, monkeypatch):
    restaurant, customer = tenant
    order = _make_order(restaurant, customer, order_number="R6", age=OLD_ENOUGH, payment_status=PaymentStatus.PAID)
    db_session.add(order)
    await db_session.commit()

    calls = []

    async def fake_check_payment_status(self, order):
        calls.append(order.id)
        return "paid"

    monkeypatch.setattr(RazorpayGateway, "check_payment_status", fake_check_payment_status, raising=False)

    resolved = await _check_stuck_payments()

    assert resolved == 0
    assert calls == []


async def test_one_bad_lookup_does_not_block_the_rest_of_the_batch(db_session, tenant, monkeypatch):
    restaurant, customer = tenant
    bad_order = _make_order(restaurant, customer, order_number="R7", age=OLD_ENOUGH)
    good_order = _make_order(restaurant, customer, order_number="R8", age=OLD_ENOUGH)
    db_session.add_all([bad_order, good_order])
    await db_session.commit()

    async def flaky_check_payment_status(self, order):
        if order.order_number == "R7":
            raise RuntimeError("gateway timeout")
        return "paid"

    monkeypatch.setattr(RazorpayGateway, "check_payment_status", flaky_check_payment_status, raising=False)
    bad_order_id = bad_order.id
    good_order_id = good_order.id

    resolved = await _check_stuck_payments()

    assert resolved == 1
    db_session.expire_all()
    bad_refreshed = (await db_session.execute(select(Order).where(Order.id == bad_order_id))).scalar_one()
    good_refreshed = (await db_session.execute(select(Order).where(Order.id == good_order_id))).scalar_one()
    assert bad_refreshed.payment_status == PaymentStatus.PENDING
    assert good_refreshed.payment_status == PaymentStatus.PAID
