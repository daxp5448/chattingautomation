"""Razorpay payment-link creation for the generic engine's order/booking niches --
deliberately NOT reusing app/services/payment/razorpay.py::RazorpayGateway.create_payment,
which is typed directly to the legacy `Order` model (order.order_number, etc.). Rather
than force an Engagement to duck-type as an Order, this is a small (~20 line) parallel
adapter using the identical HTTP pattern -- see that file for the original.

Webhook receiver: app/api/v1/routers/generic_payments.py (HMAC-verified, mirrors the
legacy engine's app/api/v1/routers/payments.py). It flips Engagement.payment_status to
"paid" on a verified `payment.captured`/`payment_link.paid` event, and on a
`payment_link.expired`/`payment.failed` event calls `create_payment_link` again (this
same function) to hand the customer a fresh link -- the retry path for an expired/failed
payment, no new conversational flow-engine step required.

Timeout policy: `expire_by` below gives every generated link a 24-hour window (Razorpay
fires `payment_link.expired` when it lapses, handled by the webhook receiver above); a
business's own Razorpay dashboard default would otherwise apply if this were omitted,
which is not a policy this codebase should leave implicit.
"""

import time
from typing import Any

import httpx

from app.core.security import decrypt_secret
from app.models.engagement import Engagement
from app.models.restaurant import Restaurant

RAZORPAY_API_BASE = "https://api.razorpay.com/v1"
PAYMENT_LINK_EXPIRY_SECONDS = 24 * 60 * 60


async def create_payment_link(restaurant: Restaurant, engagement: Engagement) -> dict[str, Any]:
    key_id = restaurant.razorpay_key_id or ""
    key_secret = decrypt_secret(restaurant.razorpay_key_secret_encrypted or "")
    if not key_id or not key_secret:
        return {"error": "razorpay_not_configured"}

    payload = {
        "amount": int(round(float(engagement.total) * 100)),
        "currency": restaurant.currency,
        "description": f"{restaurant.name} - {engagement.reference_number}",
        "notes": {"engagement_id": str(engagement.id), "reference_number": engagement.reference_number},
        "reminder_enable": True,
        "expire_by": int(time.time()) + PAYMENT_LINK_EXPIRY_SECONDS,
    }
    try:
        async with httpx.AsyncClient(timeout=10.0, auth=(key_id, key_secret)) as client:
            response = await client.post(f"{RAZORPAY_API_BASE}/payment_links", json=payload)
            response.raise_for_status()
            data = response.json()
        return {"payment_link_id": data.get("id"), "payment_link_url": data.get("short_url")}
    except Exception as exc:
        return {"error": str(exc)}
