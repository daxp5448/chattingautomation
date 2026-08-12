import pytest

from app.models.customer import Customer
from app.models.order import Order
from app.models.restaurant import Restaurant
from app.repositories.loyalty_repository import LoyaltyTransactionRepository
from app.services import loyalty_service


@pytest.fixture
async def restaurant_and_customer(db_session):
    restaurant = Restaurant(
        name="Loyalty Test", slug="loyalty-test", loyalty_settings={"points_per_currency_unit": 0.1, "redemption_value_per_point": 1.0}
    )
    db_session.add(restaurant)
    await db_session.flush()
    customer = Customer(restaurant_id=restaurant.id, phone="922222")
    db_session.add(customer)
    await db_session.commit()
    return restaurant, customer


async def test_award_points(db_session, restaurant_and_customer):
    restaurant, customer = restaurant_and_customer
    repo = LoyaltyTransactionRepository(db_session)
    order = Order(restaurant_id=restaurant.id, branch_id=restaurant.id, customer_id=customer.id, order_number="X1", total=250)

    points = await loyalty_service.award_points(repo, restaurant, customer, order)

    assert points == 25  # 250 * 0.1
    assert customer.loyalty_points == 25


async def test_award_points_zero_rate_awards_nothing(db_session, restaurant_and_customer):
    restaurant, customer = restaurant_and_customer
    restaurant.loyalty_settings = {}
    repo = LoyaltyTransactionRepository(db_session)
    order = Order(restaurant_id=restaurant.id, branch_id=restaurant.id, customer_id=customer.id, order_number="X2", total=250)

    points = await loyalty_service.award_points(repo, restaurant, customer, order)

    assert points == 0
    assert customer.loyalty_points == 0


async def test_redeem_points_within_balance(db_session, restaurant_and_customer):
    restaurant, customer = restaurant_and_customer
    customer.loyalty_points = 100
    repo = LoyaltyTransactionRepository(db_session)

    discount = await loyalty_service.redeem_points(repo, restaurant, customer, 40)

    assert discount == 40  # 1.0 value per point
    assert customer.loyalty_points == 60


async def test_redeem_more_points_than_balance_raises(db_session, restaurant_and_customer):
    restaurant, customer = restaurant_and_customer
    customer.loyalty_points = 10
    repo = LoyaltyTransactionRepository(db_session)

    with pytest.raises(loyalty_service.LoyaltyError):
        await loyalty_service.redeem_points(repo, restaurant, customer, 50)


async def test_redeem_points_atomic_check_and_deduct_rejects_over_redemption(db_session, restaurant_and_customer):
    """The check-and-deduct is a single atomic UPDATE ... WHERE loyalty_points >= points,
    not a Python-side read-then-write -- so a second redemption that would overdraw the
    balance left *after* a first successful redemption must be rejected using the DB's
    current value, not a stale in-memory one.
    """
    restaurant, customer = restaurant_and_customer
    customer.loyalty_points = 50
    repo = LoyaltyTransactionRepository(db_session)

    first_discount = await loyalty_service.redeem_points(repo, restaurant, customer, 30)
    assert first_discount == 30
    assert customer.loyalty_points == 20

    with pytest.raises(loyalty_service.LoyaltyError):
        await loyalty_service.redeem_points(repo, restaurant, customer, 30)

    # Rejected attempt must not have deducted anything.
    assert customer.loyalty_points == 20
