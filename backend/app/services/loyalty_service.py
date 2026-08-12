from sqlalchemy import update

from app.models.customer import Customer
from app.models.enums import LoyaltyReason
from app.models.loyalty import LoyaltyTransaction
from app.models.order import Order
from app.models.restaurant import Restaurant
from app.repositories.loyalty_repository import LoyaltyTransactionRepository


class LoyaltyError(Exception):
    pass


async def award_points(
    loyalty_repo: LoyaltyTransactionRepository, restaurant: Restaurant, customer: Customer, order: Order
) -> int:
    rate = float((restaurant.loyalty_settings or {}).get("points_per_currency_unit", 0))
    points = int(round(float(order.total) * rate))
    if points <= 0:
        return 0

    session = loyalty_repo.session
    txn = LoyaltyTransaction(
        restaurant_id=restaurant.id,
        customer_id=customer.id,
        order_id=order.id,
        points_delta=points,
        reason=LoyaltyReason.EARNED,
    )
    # Flushes the transaction row *and* any pending in-memory changes on `customer`, so the
    # atomic update below computes off the row's true current DB value.
    await loyalty_repo.create(txn)
    # Atomic read-modify-write at the DB level (`loyalty_points = loyalty_points + points`)
    # instead of Python-side `customer.loyalty_points += points`, so two concurrent awards
    # for the same customer (e.g. two orders completing at once) both land instead of one
    # clobbering the other's read.
    await session.execute(
        update(Customer).where(Customer.id == customer.id).values(loyalty_points=Customer.loyalty_points + points)
    )
    await session.flush()
    await session.refresh(customer)
    return points


async def redeem_points(
    loyalty_repo: LoyaltyTransactionRepository, restaurant: Restaurant, customer: Customer, points: int
) -> float:
    if points <= 0:
        raise LoyaltyError("Points to redeem must be positive")

    session = loyalty_repo.session
    # Flush any pending in-memory changes on `customer` first, so the atomic gate below
    # checks/updates against its true current DB value.
    await session.flush()

    value_per_point = float((restaurant.loyalty_settings or {}).get("redemption_value_per_point", 0))
    discount = round(points * value_per_point, 2)

    # Atomic check-and-deduct: the WHERE clause re-checks the balance at the DB level in
    # the same statement that deducts it, so two concurrent redemption attempts for the
    # same customer can't both read "enough points" before either commits and over-redeem.
    result = await session.execute(
        update(Customer)
        .where(Customer.id == customer.id, Customer.loyalty_points >= points)
        .values(loyalty_points=Customer.loyalty_points - points)
    )
    if result.rowcount == 0:
        raise LoyaltyError("Not enough loyalty points")

    txn = LoyaltyTransaction(
        restaurant_id=restaurant.id,
        customer_id=customer.id,
        order_id=None,
        points_delta=-points,
        reason=LoyaltyReason.REDEEMED,
    )
    await loyalty_repo.create(txn)
    await session.refresh(customer)
    return discount
