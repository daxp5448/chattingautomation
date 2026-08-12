from typing import Any

from app.models.order import Order
from app.services.payment.base import PaymentGateway, register_gateway


class CODRefundNotSupportedError(Exception):
    """Raised by CashOnDeliveryGateway.refund. COD money is physical cash collected at
    delivery/pickup, so there's no API to call to reverse it -- refunding a COD order is
    an out-of-band, manual action (hand cash back, or credit it against a future order)
    that this system can't perform for the caller. Raising here (instead of silently
    returning) means a caller can't mistake "nothing happened" for "refunded"."""


class CashOnDeliveryGateway(PaymentGateway):
    method = "cod"

    async def create_payment(self, order: Order) -> dict[str, Any]:
        return {"method": "cod", "collect_at_delivery": order.total}

    async def verify_payment(self, order: Order, payload: dict[str, Any]) -> bool:
        # COD has nothing to verify upfront; payment is marked paid on delivery
        # (order status transition), not through a gateway callback.
        return True

    async def refund(self, payment_id: str, amount: float) -> dict[str, Any]:
        raise CODRefundNotSupportedError(
            "COD payments are collected as cash and can't be refunded automatically -- "
            "refund the customer manually (cash/credit) and record it outside this system."
        )


register_gateway(CashOnDeliveryGateway())
