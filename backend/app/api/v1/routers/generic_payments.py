"""Razorpay webhook receiver for the generic multi-niche engine's Engagement model --
the direct counterpart of app/api/v1/routers/payments.py (legacy, Order-typed), built as
a fully separate, parallel endpoint rather than extended into that file, for the same
reason every other piece of the generic engine is parallel: a business is either on the
legacy engine or the generic one (Restaurant.uses_generic_engine), never both, so there
is no need -- and real risk -- in sharing code between the two payment paths. A business
on the generic engine configures ITS Razorpay account's webhook URL to point at this
endpoint instead of the legacy one; nothing about the legacy path changes.

Closes the gap flagged in app/services/payment/generic_razorpay.py's module docstring:
until now, create_payment_link generated and sent a real link but nothing ever verified
that it was actually paid -- an Engagement could sit at payment_status="pending" forever
even after the customer paid. This receiver is what flips it to "paid" for real, off a
signature-verified webhook event, mirroring payments.py's proven idempotency/locking
pattern line for line (row-lock the Engagement, verify signature only after loading the
right restaurant's webhook secret, treat a redelivered event as a safe no-op, never let
a late failure event clobber an already-confirmed payment).
"""

import logging
import uuid

from fastapi import APIRouter, Header, HTTPException, Request, status
from sqlalchemy import select

from app.core.rate_limit import limiter
from app.core.security import decrypt_secret
from app.core.ws_manager import manager as ws_manager
from app.db.session import AsyncSessionLocal
from app.models.engagement import Engagement
from app.repositories.customer_repository import CustomerRepository
from app.repositories.restaurant_repository import RestaurantRepository
from app.services.payment.razorpay import verify_webhook_signature
from app.services.whatsapp_client import GraphAPIWhatsAppSender, OutboundMessage

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/generic-payments", tags=["generic-payments"])

_sender = GraphAPIWhatsAppSender()

# Same two event-outcome sets as payments.py -- anything outside them (or a redelivery of
# an event whose outcome is already recorded) is a no-op past signature verification.
_SUCCESS_EVENTS = {"payment_link.paid", "payment.captured"}
_FAILURE_EVENTS = {"payment_link.expired", "payment.failed"}


def _extract_engagement_id(payload: dict) -> str | None:
    """Mirrors payments.py's _extract_order_id: checks both the payment_link entity and
    the payment entity's notes, since a payment made through a Razorpay Payment Link
    carries the link's notes forward onto the resulting Payment entity too -- either
    shape can appear depending on which event fired first."""
    entity = payload.get("payload", {})
    for key in ("payment_link", "payment"):
        notes = entity.get(key, {}).get("entity", {}).get("notes", {})
        if notes.get("engagement_id"):
            return notes["engagement_id"]
    return None


def _extract_payment_id(payload: dict) -> str | None:
    return payload.get("payload", {}).get("payment", {}).get("entity", {}).get("id")


@router.post("/razorpay/webhook")
@limiter.limit("60/minute")
async def generic_razorpay_webhook(request: Request, x_razorpay_signature: str | None = Header(default=None)):
    raw_body = await request.body()
    payload = await request.json()
    event = payload.get("event")

    engagement_id = _extract_engagement_id(payload)
    if not engagement_id:
        logger.info("Generic Razorpay webhook ignored: no engagement_id in payload notes (event=%s)", event)
        return {"status": "ignored"}

    async with AsyncSessionLocal() as session:
        # Row-lock for the rest of this transaction: two concurrent/redelivered webhook
        # deliveries for the same engagement (Razorpay retries on anything but a fast
        # 200) serialize on this SELECT instead of both reading payment_status != "paid"
        # as true and both sending the customer a duplicate confirmation.
        stmt = select(Engagement).where(Engagement.id == uuid.UUID(engagement_id)).with_for_update()
        engagement = (await session.execute(stmt)).scalar_one_or_none()
        if not engagement:
            logger.warning("Generic Razorpay webhook: engagement %s not found (event=%s)", engagement_id, event)
            return {"status": "ignored"}

        restaurant_repo = RestaurantRepository(session)
        restaurant = await restaurant_repo.get(engagement.restaurant_id)
        if not restaurant:
            logger.warning(
                "Generic Razorpay webhook: restaurant %s not found for engagement %s (reference_number=%s, event=%s)",
                engagement.restaurant_id, engagement.id, engagement.reference_number, event,
            )
            return {"status": "ignored"}

        webhook_secret = decrypt_secret(restaurant.razorpay_webhook_secret_encrypted or "")
        if not verify_webhook_signature(raw_body, x_razorpay_signature, webhook_secret):
            logger.warning(
                "Generic Razorpay webhook: signature verification failed for engagement %s (reference_number=%s, restaurant_id=%s, event=%s)",
                engagement.id, engagement.reference_number, restaurant.id, event,
            )
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signature")

        if event in _SUCCESS_EVENTS:
            if engagement.payment_status == "paid":
                # Redelivery of an event already processed -- exactly the race the row
                # lock above serializes against. Log and stop; never resend the
                # "payment received" WhatsApp message a second time.
                logger.info(
                    "Generic Razorpay webhook: duplicate '%s' event ignored, engagement %s (reference_number=%s) already paid",
                    event, engagement.id, engagement.reference_number,
                )
            else:
                engagement.payment_status = "paid"
                payment_id = _extract_payment_id(payload)
                if payment_id:
                    engagement.gateway_metadata = {**(engagement.gateway_metadata or {}), "payment_id": payment_id}
                await session.commit()

                logger.info(
                    "Generic Razorpay payment confirmed: engagement_id=%s reference_number=%s restaurant_id=%s amount=%s event=%s",
                    engagement.id, engagement.reference_number, restaurant.id, engagement.total, event,
                )

                customer_repo = CustomerRepository(session)
                customer = await customer_repo.get(engagement.customer_id, restaurant.id)
                if customer:
                    access_token = decrypt_secret(restaurant.whatsapp_access_token_encrypted or "")
                    msg = f"✅ Payment received for {engagement.reference_number}. Thank you!"
                    await _sender.send(
                        restaurant.whatsapp_phone_number_id or "", access_token, OutboundMessage.text(customer.phone, msg)
                    )
                await ws_manager.broadcast(restaurant.id, {"type": "engagement_payment_success", "engagement_id": str(engagement.id)})

        elif event in _FAILURE_EVENTS:
            if engagement.payment_status == "paid":
                # Out-of-order/late delivery of a failure event for an engagement already
                # confirmed as paid -- never let this clobber a confirmed payment.
                logger.warning(
                    "Generic Razorpay webhook: '%s' event ignored for engagement %s (reference_number=%s) -- already marked paid",
                    event, engagement.id, engagement.reference_number,
                )
            elif engagement.payment_status == "failed":
                logger.info(
                    "Generic Razorpay webhook: duplicate '%s' event ignored, engagement %s (reference_number=%s) already marked failed",
                    event, engagement.id, engagement.reference_number,
                )
            else:
                engagement.payment_status = "failed"
                await session.commit()

                logger.info(
                    "Generic Razorpay payment failed/expired: engagement_id=%s reference_number=%s restaurant_id=%s event=%s",
                    engagement.id, engagement.reference_number, restaurant.id, event,
                )

                customer_repo = CustomerRepository(session)
                customer = await customer_repo.get(engagement.customer_id, restaurant.id)
                if customer:
                    access_token = decrypt_secret(restaurant.whatsapp_access_token_encrypted or "")
                    # Retry path: rather than requiring a new conversational step (which
                    # would be a genuine new engine capability), immediately generate a
                    # fresh payment link server-side and hand it straight to the
                    # customer -- no flow-engine change needed for "is there a retry
                    # option" to be a real yes.
                    from app.services.payment.generic_razorpay import create_payment_link

                    retry_result = await create_payment_link(restaurant, engagement)
                    retry_link = retry_result.get("payment_link_url")
                    if retry_link:
                        msg = (
                            f"Your payment for {engagement.reference_number} didn't go through or expired. "
                            f"Here's a new payment link: {retry_link}"
                        )
                    else:
                        msg = (
                            f"Your payment for {engagement.reference_number} didn't go through or expired. "
                            "Please contact us and we'll help you complete your payment."
                        )
                    await _sender.send(
                        restaurant.whatsapp_phone_number_id or "", access_token, OutboundMessage.text(customer.phone, msg)
                    )
                await ws_manager.broadcast(restaurant.id, {"type": "engagement_payment_failed", "engagement_id": str(engagement.id)})

        else:
            logger.info(
                "Generic Razorpay webhook: unrecognized event '%s' ignored for engagement %s (reference_number=%s, restaurant_id=%s)",
                event, engagement.id, engagement.reference_number, restaurant.id,
            )

    return {"status": "ok"}
