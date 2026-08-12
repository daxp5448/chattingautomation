import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, update

from app.core.deps import CurrentUser, DbSession, require_roles, resolve_branch_scope, resolve_tenant_id
from app.core.security import decrypt_secret
from app.core.ws_manager import manager as ws_manager
from app.models.coupon import CouponRedemption
from app.models.customer import Customer
from app.models.enums import FulfillmentType, LoyaltyReason, OrderStatus, PaymentMethod, PaymentStatus, UserRole
from app.models.loyalty import LoyaltyTransaction
from app.models.order import Order
from app.models.user import User
from app.repositories.customer_repository import CustomerRepository
from app.repositories.loyalty_repository import LoyaltyTransactionRepository
from app.repositories.order_repository import OrderRepository
from app.repositories.restaurant_repository import RestaurantRepository
from app.schemas.order import OrderRead, OrderStatusUpdate
from app.services import loyalty_service
from app.services.payment.base import get_gateway
from app.services.payment.cod import CODRefundNotSupportedError
from app.services.payment.razorpay import RazorpayGateway
from app.services.whatsapp_client import GraphAPIWhatsAppSender, OutboundMessage

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/restaurants/{restaurant_id}/orders", tags=["orders"])

_sender = GraphAPIWhatsAppSender()

# Legal status graph for PATCH /{order_id}/status. REFUNDED is intentionally absent from
# every allowed-targets set below -- it's a terminal state reachable only through the
# dedicated POST /{order_id}/refund endpoint (item 4), which flips it only after a real
# gateway refund succeeds. COMPLETED/CANCELLED/REFUNDED are all terminal: nothing can be
# PATCHed out of them through this endpoint.
_LEGAL_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.PENDING: {OrderStatus.ACCEPTED, OrderStatus.CANCELLED},
    OrderStatus.ACCEPTED: {OrderStatus.PREPARING, OrderStatus.CANCELLED},
    OrderStatus.PREPARING: {OrderStatus.READY, OrderStatus.CANCELLED},
    OrderStatus.READY: {OrderStatus.COMPLETED, OrderStatus.CANCELLED},
    OrderStatus.COMPLETED: set(),
    OrderStatus.CANCELLED: set(),
    OrderStatus.REFUNDED: set(),
}


def _to_order_read(order: Order) -> OrderRead:
    """OrderRead carries customer_name/customer_phone, but those live on the related
    Customer, not on Order itself -- model_validate(from_attributes=True) fills them with
    the schema's defaults (None / ""), then we overwrite with the real values from the
    eager-loaded `order.customer` (see OrderRepository.get_with_items/list_with_items).
    """
    read = OrderRead.model_validate(order, from_attributes=True)
    read.customer_name = order.customer.name if order.customer else None
    read.customer_phone = order.customer.phone if order.customer else ""
    return read


def _status_message(order: Order) -> str | None:
    """Customer-facing copy for a status transition. None for PENDING (the initial state --
    nothing to announce) and for any status this function doesn't recognize."""
    is_pickup = order.fulfillment_type == FulfillmentType.PICKUP
    if order.status == OrderStatus.ACCEPTED:
        return f"Your order #{order.order_number} has been accepted and is being prepared!"
    if order.status == OrderStatus.PREPARING:
        return f"Your order #{order.order_number} is now being prepared."
    if order.status == OrderStatus.READY:
        if is_pickup:
            return f"Your order #{order.order_number} is ready for pickup!"
        return f"Your order #{order.order_number} is ready and out for delivery!"
    if order.status == OrderStatus.COMPLETED:
        if is_pickup:
            return f"Your order #{order.order_number} has been picked up. Thanks for ordering with us!"
        return f"Your order #{order.order_number} has been delivered. Thanks for ordering with us!"
    if order.status == OrderStatus.CANCELLED:
        return f"Your order #{order.order_number} has been cancelled. If you have questions, please contact us."
    return None


async def _reverse_coupon_and_loyalty(db: DbSession, order: Order) -> None:
    """Undo whatever this order consumed at confirm time, so cancelling it doesn't
    permanently cost the customer a coupon use or spent loyalty points. No-op if the order
    used neither.
    """
    redemption_result = await db.execute(select(CouponRedemption).where(CouponRedemption.order_id == order.id))
    for redemption in redemption_result.scalars().all():
        await db.delete(redemption)

    loyalty_result = await db.execute(
        select(LoyaltyTransaction).where(
            LoyaltyTransaction.order_id == order.id, LoyaltyTransaction.reason == LoyaltyReason.REDEEMED
        )
    )
    redeemed_txns = loyalty_result.scalars().all()
    points_to_restore = sum(-txn.points_delta for txn in redeemed_txns)
    if points_to_restore > 0:
        # Same atomic read-modify-write pattern as loyalty_service.award_points/
        # redeem_points: `loyalty_points = loyalty_points + delta` at the DB level, not a
        # Python-side increment, so this can't race with a concurrent award/redemption for
        # the same customer.
        await db.execute(
            update(Customer)
            .where(Customer.id == order.customer_id)
            .values(loyalty_points=Customer.loyalty_points + points_to_restore)
        )
        db.add(
            LoyaltyTransaction(
                restaurant_id=order.restaurant_id,
                customer_id=order.customer_id,
                order_id=order.id,
                points_delta=points_to_restore,
                reason=LoyaltyReason.EARNED,
            )
        )


@router.get("", response_model=list[OrderRead])
async def list_orders(
    restaurant_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
    status_filter: OrderStatus | None = None,
    branch_id: uuid.UUID | None = None,
):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    effective_branch_id = resolve_branch_scope(user, branch_id)
    repo = OrderRepository(db)
    orders = await repo.list_with_items(tenant_id, status_filter, effective_branch_id)
    return [_to_order_read(order) for order in orders]


@router.get("/{order_id}", response_model=OrderRead)
async def get_order(restaurant_id: uuid.UUID, order_id: uuid.UUID, db: DbSession, user: CurrentUser):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    effective_branch_id = resolve_branch_scope(user)
    repo = OrderRepository(db)
    order = await repo.get_with_items(order_id, tenant_id, effective_branch_id)
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    return _to_order_read(order)


@router.patch("/{order_id}/status", response_model=OrderRead)
async def update_order_status(
    restaurant_id: uuid.UUID, order_id: uuid.UUID, payload: OrderStatusUpdate, db: DbSession, user: CurrentUser
):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    effective_branch_id = resolve_branch_scope(user)
    repo = OrderRepository(db)
    order = await repo.get_with_items(order_id, tenant_id, effective_branch_id)
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")

    previous_status = order.status
    new_status = payload.status
    if new_status not in _LEGAL_TRANSITIONS.get(previous_status, set()):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot transition order from '{previous_status.value}' to '{new_status.value}'",
        )

    order.status = new_status

    restaurant = await RestaurantRepository(db).get(tenant_id)
    customer = await CustomerRepository(db).get(order.customer_id, tenant_id)

    if new_status == OrderStatus.COMPLETED:
        if restaurant and customer:
            await loyalty_service.award_points(LoyaltyTransactionRepository(db), restaurant, customer, order)
        if order.payment_method == PaymentMethod.COD:
            # Cash is collected by definition once a COD order is completed. Razorpay
            # orders are unaffected -- their payment_status only ever changes via the
            # webhook (see app/api/v1/routers/payments.py).
            order.payment_status = PaymentStatus.PAID

    if new_status == OrderStatus.CANCELLED:
        await _reverse_coupon_and_loyalty(db, order)

    await repo.commit()
    await ws_manager.broadcast(
        tenant_id, {"type": "order_status_changed", "order_id": str(order.id), "status": order.status.value}
    )

    message = _status_message(order)
    if message and restaurant and customer:
        try:
            access_token = decrypt_secret(restaurant.whatsapp_access_token_encrypted or "")
            await _sender.send(
                restaurant.whatsapp_phone_number_id or "", access_token, OutboundMessage.text(customer.phone, message)
            )
        except Exception:
            # A WhatsApp API failure must never fail the status-update request itself --
            # the status change already committed above; the notification is best-effort.
            logger.warning(
                "Failed to send WhatsApp status-update message for order %s (order_number=%s, status=%s)",
                order.id,
                order.order_number,
                order.status.value,
                exc_info=True,
            )

    return _to_order_read(order)


@router.post("/{order_id}/refund", response_model=OrderRead)
async def refund_order(
    restaurant_id: uuid.UUID,
    order_id: uuid.UUID,
    db: DbSession,
    user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    repo = OrderRepository(db)
    order = await repo.get_with_items(order_id, tenant_id)
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    if order.payment_status != PaymentStatus.PAID:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Order payment_status is '{order.payment_status.value}', not 'paid' -- there is nothing to refund",
        )

    try:
        if order.payment_method == PaymentMethod.RAZORPAY:
            restaurant = await RestaurantRepository(db).get(tenant_id)
            if not restaurant:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")
            payment_id = (order.gateway_metadata or {}).get("payment_id")
            if not payment_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="No Razorpay payment_id recorded for this order -- cannot refund automatically",
                )
            await RazorpayGateway(restaurant).refund(payment_id, float(order.total))
        else:
            gateway = get_gateway(order.payment_method.value)
            await gateway.refund("", float(order.total))
    except HTTPException:
        raise
    except CODRefundNotSupportedError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Refund failed: {exc}") from exc

    # Only mark as refunded now that the gateway call above actually succeeded -- never
    # flip payment_status ahead of the real refund landing.
    order.payment_status = PaymentStatus.REFUNDED
    order.status = OrderStatus.REFUNDED
    await repo.commit()
    await ws_manager.broadcast(tenant_id, {"type": "order_refunded", "order_id": str(order.id)})
    logger.info(
        "Order refunded: order_id=%s order_number=%s restaurant_id=%s amount=%s",
        order.id,
        order.order_number,
        tenant_id,
        order.total,
    )
    return _to_order_read(order)
