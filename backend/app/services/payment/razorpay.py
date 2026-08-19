import hashlib
import hmac
from typing import Any

import httpx

from app.core.security import decrypt_secret
from app.models.order import Order
from app.models.restaurant import Restaurant
from app.services.payment.base import PaymentGateway

RAZORPAY_API_BASE = "https://api.razorpay.com/v1"


class RazorpayGateway(PaymentGateway):
    """Unlike CashOnDeliveryGateway (stateless, registered once via register_gateway),
    Razorpay needs per-restaurant API credentials, so it's instantiated directly with a
    restaurant rather than looked up through the global PaymentGateway registry.
    """

    method = "razorpay"

    def __init__(self, restaurant: Restaurant):
        self.restaurant = restaurant
        self.key_id = restaurant.razorpay_key_id or ""
        self.key_secret = decrypt_secret(restaurant.razorpay_key_secret_encrypted or "")

    async def create_payment(self, order: Order) -> dict[str, Any]:
        if not self.key_id or not self.key_secret:
            return {"error": "razorpay_not_configured"}

        payload = {
            "amount": int(round(float(order.total) * 100)),  # paise
            "currency": self.restaurant.currency,
            "description": f"Order {order.order_number}",
            "notes": {"order_id": str(order.id), "order_number": order.order_number},
            "reminder_enable": True,
        }
        async with httpx.AsyncClient(timeout=10.0, auth=(self.key_id, self.key_secret)) as client:
            response = await client.post(f"{RAZORPAY_API_BASE}/payment_links", json=payload)
            response.raise_for_status()
            data = response.json()
        return {"payment_link_id": data.get("id"), "payment_link_url": data.get("short_url")}

    async def verify_payment(self, order: Order, payload: dict[str, Any]) -> bool:
        return payload.get("event") in {"payment_link.paid", "payment.captured"}

    async def refund(self, payment_id: str, amount: float) -> dict[str, Any]:
        """Issue a real refund via Razorpay's REST API. `payment_id` is the Razorpay
        *payment* id (e.g. "pay_xxx", captured off the webhook payload when the payment
        succeeded -- see app/api/v1/routers/payments.py), not the payment_link id returned
        by create_payment. Raises (via httpx's raise_for_status, same as create_payment)
        on any non-2xx response so a failed refund can never be mistaken for a successful
        one by the caller.
        """
        if not self.key_id or not self.key_secret:
            raise ValueError("Razorpay is not configured for this business")
        if not payment_id:
            raise ValueError("Cannot refund: no Razorpay payment_id on this order")

        payload = {"amount": int(round(float(amount) * 100))}  # paise
        async with httpx.AsyncClient(timeout=10.0, auth=(self.key_id, self.key_secret)) as client:
            response = await client.post(f"{RAZORPAY_API_BASE}/payments/{payment_id}/refund", json=payload)
            response.raise_for_status()
            data = response.json()
        return {"refund_id": data.get("id"), "status": data.get("status"), "amount": data.get("amount")}

    async def check_payment_status(self, order: Order) -> str:
        """Query Razorpay for the current status of the payment link created for `order`
        (see create_payment, which stores `payment_link_id` in order.gateway_metadata).
        Returns Razorpay's own status string for the payment link (e.g. "created",
        "paid", "expired", "cancelled") normalized to lowercase, or "unknown" if this
        order has no recorded payment link or isn't configured for Razorpay. Method name
        and signature are relied on by the reconciliation task -- do not rename.
        """
        if not self.key_id or not self.key_secret:
            return "unknown"
        payment_link_id = (order.gateway_metadata or {}).get("payment_link_id")
        if not payment_link_id:
            return "unknown"

        async with httpx.AsyncClient(timeout=10.0, auth=(self.key_id, self.key_secret)) as client:
            response = await client.get(f"{RAZORPAY_API_BASE}/payment_links/{payment_link_id}")
            response.raise_for_status()
            data = response.json()
        return str(data.get("status") or "unknown").lower()


def verify_webhook_signature(raw_body: bytes, signature: str | None, webhook_secret: str) -> bool:
    if not webhook_secret or not signature:
        return False
    expected = hmac.new(webhook_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
