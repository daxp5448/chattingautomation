"""DEMO billing only -- no real payment gateway (Razorpay/Cashfree/Stripe) is called
anywhere in this file, no money moves, no webhook from any payment provider exists here.
This exists to demo the shape of "7-day free trial, then pay" to internal stakeholders --
POST .../demo-pay is itself the fake charge: one click, one flag flip, nothing else. Real
platform billing is a separate, future build (see SUPER_ADMIN_FEATURES.md's Billing item,
still PLANNED, which would replace this file entirely rather than extend it).
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status

from app.core.deps import CurrentUser, DbSession, resolve_tenant_id
from app.models.enums import UserRole
from app.repositories.audit_log_repository import AuditLogRepository
from app.repositories.restaurant_repository import RestaurantRepository
from app.schemas.billing import BillingStatus

router = APIRouter(prefix="/restaurants/{restaurant_id}/billing", tags=["billing"])


async def _get_restaurant(db: DbSession, user: CurrentUser, restaurant_id: uuid.UUID):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    restaurant = await RestaurantRepository(db).get(tenant_id)
    if restaurant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Business not found")
    return restaurant


def _billing_status(restaurant) -> BillingStatus:
    trial_ends_at = restaurant.trial_ends_at
    expired = False
    if trial_ends_at is not None:
        # SQLite doesn't reliably round-trip tzinfo even for a DateTime(timezone=True)
        # column -- treat a naive value read back from the DB as UTC (everything that
        # ever writes this column, here and in restaurants.py, writes UTC) rather than
        # letting a naive-vs-aware comparison raise.
        if trial_ends_at.tzinfo is None:
            trial_ends_at = trial_ends_at.replace(tzinfo=timezone.utc)
        expired = trial_ends_at < datetime.now(timezone.utc)
    return BillingStatus(
        trial_ends_at=restaurant.trial_ends_at,
        trial_expired=expired,
        is_demo_billing_paid=restaurant.is_demo_billing_paid,
    )


@router.get("/status", response_model=BillingStatus)
async def get_billing_status(restaurant_id: uuid.UUID, db: DbSession, user: CurrentUser):
    restaurant = await _get_restaurant(db, user, restaurant_id)
    return _billing_status(restaurant)


@router.post("/demo-pay", response_model=BillingStatus)
async def demo_pay(restaurant_id: uuid.UUID, db: DbSession, user: CurrentUser):
    if user.role not in (UserRole.SUPER_ADMIN, UserRole.OWNER):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    restaurant = await _get_restaurant(db, user, restaurant_id)
    restaurant.is_demo_billing_paid = True

    await AuditLogRepository(db).record(
        actor_id=user.id,
        restaurant_id=restaurant.id,
        action="demo_payment_recorded",
        entity="restaurant",
        entity_id=str(restaurant.id),
        diff={"is_demo_billing_paid": True},
    )
    await db.commit()

    return _billing_status(restaurant)
