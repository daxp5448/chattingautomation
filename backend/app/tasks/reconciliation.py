"""Celery task: reconciliation for Razorpay payments that never received a webhook.

The primary path for an order's `payment_status` moving from PENDING to PAID/FAILED is
the Razorpay webhook (see app/api/v1/routers/payments.py and
app/services/payment/razorpay.py:verify_webhook_signature) -- but webhook delivery isn't
guaranteed (network blips, an outage on either side, a misconfigured webhook URL). This
task is the safety net: periodically poll Razorpay directly, via
`RazorpayGateway.check_payment_status`, for any order that's been sitting in PENDING for
suspiciously long, and resolve it from the gateway's own record instead of waiting
indefinitely on a webhook that may never arrive.

Scheduled via `beat_schedule` in app/tasks/celery_app.py (every 5 minutes) -- that only
actually fires once a `celery -A app.tasks.celery_app beat` process is running alongside
the worker.
"""

import asyncio
import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.base import utcnow
from app.db.session import AsyncSessionLocal
from app.models.enums import PaymentMethod, PaymentStatus
from app.models.order import Order
from app.services.payment.razorpay import RazorpayGateway
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

# How long an order can sit in PENDING before it's "stuck" and worth an out-of-band
# status check against Razorpay directly, rather than continuing to wait on a webhook.
STUCK_THRESHOLD_MINUTES = 30

# Razorpay payment/payment-link statuses (see app/services/payment/razorpay.py) that mean
# the payment definitively went through vs. definitively did not. Anything else (e.g.
# "created" -- the customer simply hasn't paid yet) is left alone so this task never marks
# a not-yet-attempted payment as failed just because it's old.
_SUCCESS_STATUSES = {"paid", "captured"}
_FAILURE_STATUSES = {"failed", "expired", "cancelled"}


async def _check_stuck_payments() -> int:
    """Does the actual reconciliation work inside its own DB session. Returns the number
    of orders whose payment_status was resolved (moved to PAID or FAILED). Split out from
    the `check_stuck_payments` Celery task below so it can be awaited directly in tests
    without going through `asyncio.run` (which can't be called from an already-running
    event loop, e.g. under pytest-asyncio).
    """
    cutoff = utcnow() - timedelta(minutes=STUCK_THRESHOLD_MINUTES)
    resolved = 0

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Order)
            .options(selectinload(Order.restaurant))
            .where(
                Order.payment_status == PaymentStatus.PENDING,
                Order.payment_method == PaymentMethod.RAZORPAY,
                Order.created_at < cutoff,
            )
        )
        orders = result.scalars().all()

        for order in orders:
            try:
                gateway = RazorpayGateway(order.restaurant)
                status = await gateway.check_payment_status(order)
            except Exception:
                # One bad lookup (gateway timeout, malformed response, etc.) must not kill
                # the rest of the batch -- log and move on to the next stuck order.
                logger.warning(
                    "Reconciliation: failed to check Razorpay status for order %s", order.order_number, exc_info=True
                )
                continue

            if status in _SUCCESS_STATUSES:
                order.payment_status = PaymentStatus.PAID
            elif status in _FAILURE_STATUSES:
                order.payment_status = PaymentStatus.FAILED
            else:
                # Still genuinely pending on Razorpay's side (or an unrecognized status) --
                # leave it alone; a later run will pick it back up.
                continue

            try:
                await session.commit()
                resolved += 1
            except Exception:
                await session.rollback()
                logger.warning(
                    "Reconciliation: failed to persist payment status for order %s", order.order_number, exc_info=True
                )
                continue

    return resolved


@celery_app.task(name="app.tasks.reconciliation.check_stuck_payments")
def check_stuck_payments() -> int:
    """Entry point invoked by celery-beat on the `beat_schedule` in app/tasks/celery_app.py.
    Celery tasks run synchronously, so this just wraps the async DB/gateway work in its
    own event loop.
    """
    return asyncio.run(_check_stuck_payments())
