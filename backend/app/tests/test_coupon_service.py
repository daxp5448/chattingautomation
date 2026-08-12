import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models.coupon import Coupon
from app.models.customer import Customer
from app.models.enums import CouponType
from app.models.restaurant import Restaurant
from app.repositories.coupon_repository import CouponRedemptionRepository, CouponRepository
from app.services import coupon_service


@pytest.fixture
async def restaurant_and_customer(db_session):
    restaurant = Restaurant(name="Coupon Test", slug="coupon-test")
    db_session.add(restaurant)
    await db_session.flush()
    customer = Customer(restaurant_id=restaurant.id, phone="911111")
    db_session.add(customer)
    await db_session.commit()
    return restaurant, customer


async def test_flat_coupon_applies_discount(db_session, restaurant_and_customer):
    restaurant, customer = restaurant_and_customer
    coupon_repo = CouponRepository(db_session)
    redemption_repo = CouponRedemptionRepository(db_session)

    coupon = Coupon(restaurant_id=restaurant.id, code="FLAT50", type=CouponType.FLAT, value=50)
    db_session.add(coupon)
    await db_session.commit()

    applied, discount = await coupon_service.validate_and_apply(
        coupon_repo, redemption_repo, restaurant.id, customer.id, 300, "flat50", is_first_order=False
    )
    assert applied.id == coupon.id
    assert discount == 50


async def test_percentage_coupon_respects_max_discount(db_session, restaurant_and_customer):
    restaurant, customer = restaurant_and_customer
    coupon_repo = CouponRepository(db_session)
    redemption_repo = CouponRedemptionRepository(db_session)

    coupon = Coupon(
        restaurant_id=restaurant.id, code="PCT20", type=CouponType.PERCENTAGE, value=20, max_discount_amount=30
    )
    db_session.add(coupon)
    await db_session.commit()

    _, discount = await coupon_service.validate_and_apply(
        coupon_repo, redemption_repo, restaurant.id, customer.id, 1000, "PCT20", is_first_order=False
    )
    assert discount == 30  # 20% of 1000 = 200, capped at 30


async def test_invalid_code_raises(db_session, restaurant_and_customer):
    restaurant, customer = restaurant_and_customer
    coupon_repo = CouponRepository(db_session)
    redemption_repo = CouponRedemptionRepository(db_session)

    with pytest.raises(coupon_service.CouponValidationError):
        await coupon_service.validate_and_apply(
            coupon_repo, redemption_repo, restaurant.id, customer.id, 300, "NOPE", is_first_order=False
        )


async def test_expired_coupon_rejected(db_session, restaurant_and_customer):
    restaurant, customer = restaurant_and_customer
    coupon_repo = CouponRepository(db_session)
    redemption_repo = CouponRedemptionRepository(db_session)

    coupon = Coupon(
        restaurant_id=restaurant.id,
        code="OLD10",
        type=CouponType.FLAT,
        value=10,
        expires_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    db_session.add(coupon)
    await db_session.commit()

    with pytest.raises(coupon_service.CouponValidationError, match="expired"):
        await coupon_service.validate_and_apply(
            coupon_repo, redemption_repo, restaurant.id, customer.id, 300, "OLD10", is_first_order=False
        )


async def test_min_order_amount_enforced(db_session, restaurant_and_customer):
    restaurant, customer = restaurant_and_customer
    coupon_repo = CouponRepository(db_session)
    redemption_repo = CouponRedemptionRepository(db_session)

    coupon = Coupon(restaurant_id=restaurant.id, code="BIG100", type=CouponType.FLAT, value=100, min_order_amount=500)
    db_session.add(coupon)
    await db_session.commit()

    with pytest.raises(coupon_service.CouponValidationError, match="Minimum order"):
        await coupon_service.validate_and_apply(
            coupon_repo, redemption_repo, restaurant.id, customer.id, 300, "BIG100", is_first_order=False
        )


async def test_first_order_only_enforced(db_session, restaurant_and_customer):
    restaurant, customer = restaurant_and_customer
    coupon_repo = CouponRepository(db_session)
    redemption_repo = CouponRedemptionRepository(db_session)

    coupon = Coupon(restaurant_id=restaurant.id, code="WELCOME", type=CouponType.FLAT, value=20, first_order_only=True)
    db_session.add(coupon)
    await db_session.commit()

    with pytest.raises(coupon_service.CouponValidationError, match="first order"):
        await coupon_service.validate_and_apply(
            coupon_repo, redemption_repo, restaurant.id, customer.id, 300, "WELCOME", is_first_order=False
        )

    # Should succeed when it IS the first order.
    _, discount = await coupon_service.validate_and_apply(
        coupon_repo, redemption_repo, restaurant.id, customer.id, 300, "WELCOME", is_first_order=True
    )
    assert discount == 20


async def test_usage_limit_enforced(db_session, restaurant_and_customer):
    restaurant, customer = restaurant_and_customer
    coupon_repo = CouponRepository(db_session)
    redemption_repo = CouponRedemptionRepository(db_session)

    coupon = Coupon(restaurant_id=restaurant.id, code="ONCE", type=CouponType.FLAT, value=10, usage_limit=1)
    db_session.add(coupon)
    await db_session.commit()

    from app.db.base import utcnow
    from app.models.coupon import CouponRedemption

    db_session.add(
        CouponRedemption(
            coupon_id=coupon.id,
            order_id=uuid.uuid4(),
            customer_id=customer.id,
            discount_amount=10,
            redeemed_at=utcnow(),
        )
    )
    await db_session.commit()

    with pytest.raises(coupon_service.CouponValidationError, match="usage limit"):
        await coupon_service.validate_and_apply(
            coupon_repo, redemption_repo, restaurant.id, customer.id, 300, "ONCE", is_first_order=False
        )


async def test_redeem_rejects_second_attempt_once_usage_limit_reached(db_session, restaurant_and_customer):
    """The locked check-and-redeem path (coupon_repo.get_by_code_for_update +
    coupon_service.redeem) used at order-confirmation time: a second redemption attempt
    against a usage_limit=1 coupon, made after the first one already succeeded and created
    its CouponRedemption row, must be rejected -- not just a second *check* against a
    pre-seeded row (test_usage_limit_enforced above), but the actual redeem-then-redeem-
    again sequence.
    """
    restaurant, customer = restaurant_and_customer
    coupon_repo = CouponRepository(db_session)
    redemption_repo = CouponRedemptionRepository(db_session)

    coupon = Coupon(restaurant_id=restaurant.id, code="ONLYONE", type=CouponType.FLAT, value=10, usage_limit=1)
    db_session.add(coupon)
    await db_session.commit()

    redemption = await coupon_service.redeem(
        coupon_repo, redemption_repo, restaurant.id, customer.id, uuid.uuid4(), 300, "ONLYONE", is_first_order=False, discount=10
    )
    assert redemption.discount_amount == 10

    with pytest.raises(coupon_service.CouponValidationError, match="usage limit"):
        await coupon_service.redeem(
            coupon_repo, redemption_repo, restaurant.id, customer.id, uuid.uuid4(), 300, "ONLYONE", is_first_order=False, discount=10
        )

    # Exactly one redemption row exists -- the second attempt didn't get as far as
    # inserting anything.
    count = await redemption_repo.count_for_coupon(coupon.id)
    assert count == 1


def test_compute_discount_flat_negative_value_never_increases_total():
    """A negative coupon.value (bad data, or a misconfigured FLAT coupon) must clamp to
    zero discount rather than becoming a negative discount that increases the order total.
    """
    coupon = Coupon(type=CouponType.FLAT, value=-50)
    assert coupon_service.compute_discount(coupon, 300) == 0.0
