import logging
import uuid

from fastapi import APIRouter, Header, HTTPException, Request, status
from sqlalchemy import select

from app.core.rate_limit import limiter
from app.core.security import decrypt_secret
from app.core.ws_manager import manager as ws_manager
from app.db.session import AsyncSessionLocal
from app.models.enums import PaymentStatus
from app.models.order import Order
from app.repositories.customer_repository import CustomerRepository
from app.repositories.order_repository import OrderRepository
from app.repositories.restaurant_repository import RestaurantRepository
from app.services.payment.razorpay import verify_webhook_signature
from app.services.whatsapp_client import GraphAPIWhatsAppSender, OutboundMessage

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/payments", tags=["payments"])

_sender = GraphAPIWhatsAppSender()

# Events that mean "the customer's money landed" vs. "the customer's money did not land".
# Anything outside these two sets (or a redelivery of an event whose outcome we've already
# recorded) is intentionally a no-op past signature verification -- see the final `else`
# branch below.
_SUCCESS_EVENTS = {"payment_link.paid", "payment.captured"}
_FAILURE_EVENTS = {"payment_link.expired", "payment.failed"}


def _extract_order_id(payload: dict) -> str | None:
    entity = payload.get("payload", {})
    for key in ("payment_link", "payment"):
        notes = entity.get(key, {}).get("entity", {}).get("notes", {})
        if notes.get("order_id"):
            return notes["order_id"]
    return None


def _extract_payment_id(payload: dict) -> str | None:
    """The Razorpay *payment* id (e.g. "pay_xxx"), distinct from the payment_link id
    stored on the order at create_payment time. Needed later for issuing a refund
    (RazorpayGateway.refund takes a payment id, not a payment_link id)."""
    return payload.get("payload", {}).get("payment", {}).get("entity", {}).get("id")


@router.post("/razorpay/webhook")
@limiter.limit("60/minute")
async def razorpay_webhook(request: Request, x_razorpay_signature: str | None = Header(default=None)):
    raw_body = await request.body()
    payload = await request.json()
    event = payload.get("event")

    order_id = _extract_order_id(payload)
    if not order_id:
        logger.info("Razorpay webhook ignored: no order_id in payload notes (event=%s)", event)
        return {"status": "ignored"}

    async with AsyncSessionLocal() as session:
        order_repo = OrderRepository(session)
        # Row-lock the order for the rest of this transaction: two concurrent/redelivered
        # webhook deliveries for the same order (Razorpay retries on anything but a fast
        # 200) now serialize on this SELECT instead of both reading `payment_status !=
        # PAID` as true and both sending the customer a duplicate "payment received"
        # WhatsApp message / both re-crediting anything downstream.
        stmt = select(Order).where(Order.id == uuid.UUID(order_id)).with_for_update()
        order = (await session.execute(stmt)).scalar_one_or_none()
        if not order:
            logger.warning("Razorpay webhook: order %s not found (event=%s)", order_id, event)
            return {"status": "ignored"}

        restaurant_repo = RestaurantRepository(session)
        restaurant = await restaurant_repo.get(order.restaurant_id)
        if not restaurant:
            logger.warning(
                "Razorpay webhook: restaurant %s not found for order %s (order_number=%s, event=%s)",
                order.restaurant_id,
                order.id,
                order.order_number,
                event,
            )
            return {"status": "ignored"}

        webhook_secret = decrypt_secret(restaurant.razorpay_webhook_secret_encrypted or "")
        if not verify_webhook_signature(raw_body, x_razorpay_signature, webhook_secret):
            logger.warning(
                "Razorpay webhook: signature verification failed for order %s (order_number=%s, restaurant_id=%s, event=%s)",
                order.id,
                order.order_number,
                restaurant.id,
                event,
            )
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signature")

        if event in _SUCCESS_EVENTS:
            if order.payment_status == PaymentStatus.PAID:
                # Redelivery of an event we've already processed -- exactly the race the
                # row lock above serializes against. Log and stop; do not resend the
                # "payment received" WhatsApp message a second time.
                logger.info(
                    "Razorpay webhook: duplicate '%s' event ignored, order %s (order_number=%s) already paid",
                    event,
                    order.id,
                    order.order_number,
                )
            else:
                order.payment_status = PaymentStatus.PAID
                payment_id = _extract_payment_id(payload)
                if payment_id:
                    # Needed later to issue a refund (RazorpayGateway.refund takes a
                    # payment id, not the payment_link id already stored here).
                    order.gateway_metadata = {**(order.gateway_metadata or {}), "payment_id": payment_id}
                await session.commit()

                logger.info(
                    "Razorpay payment confirmed: order_id=%s order_number=%s restaurant_id=%s amount=%s event=%s",
                    order.id,
                    order.order_number,
                    restaurant.id,
                    order.total,
                    event,
                )

                customer_repo = CustomerRepository(session)
                customer = await customer_repo.get(order.customer_id, restaurant.id)
                if customer:
                    access_token = decrypt_secret(restaurant.whatsapp_access_token_encrypted or "")
                    msg = f"Payment received for order {order.order_number}. Thank you!"
                    await _sender.send(
                        restaurant.whatsapp_phone_number_id or "", access_token, OutboundMessage.text(customer.phone, msg)
                    )
                await ws_manager.broadcast(restaurant.id, {"type": "payment_success", "order_id": str(order.id)})

        elif event in _FAILURE_EVENTS:
            if order.payment_status == PaymentStatus.PAID:
                # Out-of-order/late delivery of a failure event for an order we've already
                # confirmed as paid -- never let this clobber a confirmed payment.
                logger.warning(
                    "Razorpay webhook: '%s' event ignored for order %s (order_number=%s) -- already marked PAID",
                    event,
                    order.id,
                    order.order_number,
                )
            elif order.payment_status == PaymentStatus.FAILED:
                logger.info(
                    "Razorpay webhook: duplicate '%s' event ignored, order %s (order_number=%s) already marked FAILED",
                    event,
                    order.id,
                    order.order_number,
                )
            else:
                order.payment_status = PaymentStatus.FAILED
                await session.commit()

                logger.info(
                    "Razorpay payment failed/expired: order_id=%s order_number=%s restaurant_id=%s event=%s",
                    order.id,
                    order.order_number,
                    restaurant.id,
                    event,
                )

                customer_repo = CustomerRepository(session)
                customer = await customer_repo.get(order.customer_id, restaurant.id)
                if customer:
                    access_token = decrypt_secret(restaurant.whatsapp_access_token_encrypted or "")
                    msg = (
                        f"Your payment for order {order.order_number} didn't go through. "
                        "You can try again, or reply here if you need help."
                    )
                    await _sender.send(
                        restaurant.whatsapp_phone_number_id or "", access_token, OutboundMessage.text(customer.phone, msg)
                    )
                await ws_manager.broadcast(restaurant.id, {"type": "payment_failed", "order_id": str(order.id)})

        else:
            logger.info(
                "Razorpay webhook: unrecognized event '%s' ignored for order %s (order_number=%s, restaurant_id=%s)",
                event,
                order.id,
                order.order_number,
                restaurant.id,
            )

    return {"status": "ok"}
