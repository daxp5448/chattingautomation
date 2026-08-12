import uuid
from datetime import datetime, timezone

from app.db.base import utcnow
from app.models.coupon import Coupon, CouponRedemption
from app.models.enums import CouponType
from app.repositories.coupon_repository import CouponRedemptionRepository, CouponRepository


class CouponValidationError(Exception):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def compute_discount(coupon: Coupon, subtotal: float) -> float:
    if coupon.type == CouponType.FLAT:
        discount = float(coupon.value)
    else:
        discount = subtotal * float(coupon.value) / 100
        if coupon.max_discount_amount is not None:
            discount = min(discount, float(coupon.max_discount_amount))
    # A negative coupon.value (bad data, or a FLAT coupon misconfigured as a negative
    # amount) must never increase the order total -- clamp to zero before capping at
    # the subtotal.
    discount = max(0.0, discount)
    return round(min(discount, subtotal), 2)


async def _check_eligibility(
    coupon: Coupon,
    redemption_repo: CouponRedemptionRepository,
    customer_id,
    cart_subtotal: float,
    is_first_order: bool,
) -> None:
    if not coupon.is_active:
        raise CouponValidationError("This coupon is no longer active")

    now = datetime.now(timezone.utc)
    if coupon.starts_at and now < coupon.starts_at:
        raise CouponValidationError("This coupon isn't active yet")
    if coupon.expires_at and now > coupon.expires_at:
        raise CouponValidationError("This coupon has expired")
    if cart_subtotal < float(coupon.min_order_amount or 0):
        raise CouponValidationError(f"Minimum order amount for this coupon is {coupon.min_order_amount}")
    if coupon.first_order_only and not is_first_order:
        raise CouponValidationError("This coupon is only valid on your first order")

    if coupon.usage_limit is not None:
        total_uses = await redemption_repo.count_for_coupon(coupon.id)
        if total_uses >= coupon.usage_limit:
            raise CouponValidationError("This coupon has reached its usage limit")
    if coupon.usage_limit_per_customer is not None:
        customer_uses = await redemption_repo.count_for_customer(coupon.id, customer_id)
        if customer_uses >= coupon.usage_limit_per_customer:
            raise CouponValidationError("You've already used this coupon the maximum number of times")


async def validate_and_apply(
    coupon_repo: CouponRepository,
    redemption_repo: CouponRedemptionRepository,
    restaurant_id,
    customer_id,
    cart_subtotal: float,
    code: str,
    is_first_order: bool,
) -> tuple[Coupon, float]:
    # Locked fetch: two customers (or two racing requests for the same customer) entering
    # the same limited coupon at the same moment serialize on this row instead of both
    # reading the same pre-redemption usage count and both passing eligibility.
    coupon = await coupon_repo.get_by_code_for_update(restaurant_id, code.strip().upper())
    if not coupon:
        raise CouponValidationError("Invalid coupon code")
    await _check_eligibility(coupon, redemption_repo, customer_id, cart_subtotal, is_first_order)
    return coupon, compute_discount(coupon, cart_subtotal)


async def redeem(
    coupon_repo: CouponRepository,
    redemption_repo: CouponRedemptionRepository,
    restaurant_id,
    customer_id,
    order_id: uuid.UUID,
    cart_subtotal: float,
    code: str,
    is_first_order: bool,
    discount: float,
) -> CouponRedemption:
    """Authoritative check-and-redeem, meant to be called once at the point an order is
    actually confirmed (not at the earlier "enter a coupon code" chat step, where the
    result is only a preview). Locks the coupon row for the eligibility check and creates
    the CouponRedemption row in the same locked scope, so two concurrent order
    confirmations against the same usage-limited coupon can't both slip past the count
    check before either commits -- the second waits for the first's row lock to release,
    then re-reads the now-updated redemption count and (correctly) gets rejected.

    `discount` is the amount already computed (via `compute_discount`) and shown to the
    customer back at the "enter a coupon code" step -- this function deliberately does NOT
    recompute it. Recomputing here would let the discount actually redeemed silently
    diverge from the one the customer was quoted if an admin edited the coupon (value,
    max_discount_amount, ...) in the window between the two calls. Instead, this is the
    single source of truth: it validates the already-computed `discount` is still
    consistent with the *current* (locked) coupon row's constraints -- non-negative, no
    greater than the subtotal, and the coupon still active/not expired/still within its
    usage limits (via `_check_eligibility`) -- and only then writes it verbatim. If any of
    that no longer holds, the coupon is rejected outright rather than silently substituting
    a different number.
    """
    coupon = await coupon_repo.get_by_code_for_update(restaurant_id, code.strip().upper())
    if not coupon:
        raise CouponValidationError("Invalid coupon code")
    await _check_eligibility(coupon, redemption_repo, customer_id, cart_subtotal, is_first_order)
    if discount < 0 or discount > cart_subtotal:
        raise CouponValidationError("This coupon's discount is no longer valid for this order")
    redemption = CouponRedemption(
        coupon_id=coupon.id,
        order_id=order_id,
        customer_id=customer_id,
        discount_amount=round(discount, 2),
        redeemed_at=utcnow(),
    )
    return await redemption_repo.create(redemption)


async def find_best_auto_coupon(
    coupon_repo: CouponRepository,
    redemption_repo: CouponRedemptionRepository,
    restaurant_id,
    customer_id,
    cart_subtotal: float,
    is_first_order: bool,
) -> tuple[Coupon, float] | None:
    """Best-effort: tries every auto_apply coupon and returns the one giving the
    largest discount the customer is currently eligible for, or None."""
    best: tuple[Coupon, float] | None = None
    for coupon in await coupon_repo.list_auto_apply(restaurant_id):
        try:
            await _check_eligibility(coupon, redemption_repo, customer_id, cart_subtotal, is_first_order)
        except CouponValidationError:
            continue
        discount = compute_discount(coupon, cart_subtotal)
        if best is None or discount > best[1]:
            best = (coupon, discount)
    return best
