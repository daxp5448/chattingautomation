import random
import string
import uuid
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy.exc import IntegrityError

from app.models.enums import FulfillmentType, PaymentMethod
from app.models.order import Order, OrderItem
from app.models.restaurant import Restaurant
from app.repositories.order_repository import OrderRepository

_ORDER_NUMBER_COLLISION_MARKERS = ("order_number", "ix_orders_order_number")


def _generate_order_number(restaurant: Restaurant) -> str:
    prefix = "".join(ch for ch in restaurant.slug.upper() if ch.isalnum())[:4] or "ORD"
    date_part = datetime.now(timezone.utc).strftime("%y%m%d")
    # order_number is String(50); "PREFIX(<=4)-YYMMDD(6)-DIGITS(6)" is at most 18 chars,
    # comfortably within that, and 6 random digits (1M possibilities/restaurant/day vs.
    # 10K at 4 digits) makes a same-day collision far less likely to begin with -- the
    # retry loop below is the actual correctness guarantee either way.
    suffix = "".join(random.choices(string.digits, k=6))
    return f"{prefix}-{date_part}-{suffix}"


def _is_order_number_collision(exc: IntegrityError) -> bool:
    message = str(exc.orig or exc).lower()
    return any(marker in message for marker in _ORDER_NUMBER_COLLISION_MARKERS)


_CENTS = Decimal("0.01")


def _to_decimal(value: Any) -> Decimal:
    # Never `Decimal(float)` directly -- that constructs from the float's exact (and
    # imprecise) binary value, e.g. Decimal(0.1) == Decimal('0.1000000000000000055511151231257827021181583404541015625').
    # Going through `str()` first gives the decimal literal a human/currency value actually
    # means.
    return Decimal(str(value))


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(_CENTS, rounding=ROUND_HALF_UP)


def compute_totals(
    restaurant: Restaurant,
    cart: list[dict[str, Any]],
    discount: float | Decimal = 0.0,
    fulfillment_type: FulfillmentType = FulfillmentType.DELIVERY,
) -> dict[str, Decimal]:
    subtotal = Decimal("0")
    tax = Decimal("0")
    for item in cart:
        price = _to_decimal(item["price"])
        qty = Decimal(int(item["qty"]))
        line_total = price * qty
        subtotal += line_total
        gst_percent = _to_decimal(item.get("gst_percent") or 0)
        tax += line_total * gst_percent / Decimal("100")
    delivery_charge = (
        _to_decimal(restaurant.delivery_charge or 0) if fulfillment_type == FulfillmentType.DELIVERY else Decimal("0")
    )
    discount_dec = max(Decimal("0"), min(_to_decimal(discount), subtotal))
    total = subtotal + tax + delivery_charge - discount_dec
    return {
        "subtotal": _quantize(subtotal),
        "tax": _quantize(tax),
        "delivery_charge": _quantize(delivery_charge),
        "discount": _quantize(discount_dec),
        "total": _quantize(total),
    }


async def create_order_from_cart(
    order_repo: OrderRepository,
    restaurant: Restaurant,
    branch_id: uuid.UUID,
    customer_id: uuid.UUID,
    cart: list[dict[str, Any]],
    delivery_address: dict[str, Any],
    notes: str | None = None,
    discount: float = 0.0,
    coupon_id: uuid.UUID | None = None,
    payment_method: PaymentMethod = PaymentMethod.COD,
    fulfillment_type: FulfillmentType = FulfillmentType.DELIVERY,
) -> Order:
    if not cart:
        raise ValueError("Cannot create an order from an empty cart")

    totals = compute_totals(restaurant, cart, discount, fulfillment_type)
    session = order_repo.session

    last_error: IntegrityError | None = None
    for _attempt in range(3):
        order = Order(
            restaurant_id=restaurant.id,
            branch_id=branch_id,
            customer_id=customer_id,
            coupon_id=coupon_id,
            order_number=_generate_order_number(restaurant),
            payment_method=payment_method,
            fulfillment_type=fulfillment_type,
            delivery_address=delivery_address,
            notes=notes,
            **totals,
        )
        order.items = [
            OrderItem(
                product_id=item["product_id"],
                name_snapshot=item["name"],
                price_snapshot=item["price"],
                quantity=item["qty"],
                addons_snapshot=item.get("addons", []),
            )
            for item in cart
        ]
        try:
            # A SAVEPOINT (not a full rollback): on IntegrityError only this attempt's
            # insert is undone, leaving the rest of the caller's in-progress transaction
            # (e.g. the conversation-state row already touched earlier in this request)
            # intact so the loop can retry with a fresh order_number.
            async with session.begin_nested():
                session.add(order)
                await session.flush()
            return order
        except IntegrityError as exc:
            if not _is_order_number_collision(exc):
                raise
            last_error = exc
            continue

    assert last_error is not None
    raise last_error
