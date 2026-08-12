from abc import ABC, abstractmethod
from typing import Any

from app.models.order import Order


class PaymentGateway(ABC):
    """Contract every payment method (COD, Razorpay, Stripe, PhonePe, UPI, ...) implements.

    order_service and the WhatsApp flow engine talk to this interface only, so a new
    gateway plugs in without touching order creation/status logic.
    """

    method: str

    @abstractmethod
    async def create_payment(self, order: Order) -> dict[str, Any]:
        """Kick off payment collection for an order. Returns gateway-specific metadata
        (e.g. a payment link/order id) to hand back to the customer."""

    @abstractmethod
    async def verify_payment(self, order: Order, payload: dict[str, Any]) -> bool:
        """Verify a payment confirmation payload (e.g. gateway webhook) for this order."""

    @abstractmethod
    async def refund(self, payment_id: str, amount: float) -> dict[str, Any]:
        """Refund a previously captured payment. `payment_id` is gateway-specific (e.g. a
        Razorpay payment id); `amount` is the amount to refund in the restaurant's base
        currency unit (not paise/cents). Returns gateway-specific metadata about the
        refund. Implementations that can't refund programmatically (e.g. COD) must raise
        rather than silently no-op, so callers can't mistake "did nothing" for "refunded"."""


_REGISTRY: dict[str, PaymentGateway] = {}


def register_gateway(gateway: PaymentGateway) -> None:
    _REGISTRY[gateway.method] = gateway


def get_gateway(method: str) -> PaymentGateway:
    if method not in _REGISTRY:
        raise ValueError(f"No payment gateway registered for method '{method}'")
    return _REGISTRY[method]
