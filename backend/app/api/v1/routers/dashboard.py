import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from app.core.deps import CurrentUser, DbSession, require_roles, resolve_tenant_id
from app.models.enums import UserRole
from app.repositories.customer_repository import CustomerRepository
from app.repositories.engagement_repository import EngagementRepository
from app.repositories.order_repository import OrderRepository
from app.repositories.restaurant_repository import RestaurantRepository

router = APIRouter(prefix="/restaurants/{restaurant_id}/dashboard", tags=["dashboard"])
# Platform-wide (not one business), so it lives under its own /admin prefix rather than
# the /restaurants/{restaurant_id}/... shape every other route in this file uses -- see
# api.py, which registers this alongside `router` from the same module.
admin_router = APIRouter(prefix="/admin/dashboard", tags=["dashboard"])


@router.get("/stats")
async def get_dashboard_stats(restaurant_id: uuid.UUID, db: DbSession, user: CurrentUser):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    order_repo = OrderRepository(db)
    customer_repo = CustomerRepository(db)

    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    stats = await order_repo.dashboard_stats(tenant_id, today_start)
    customers = await customer_repo.list(restaurant_id=tenant_id)

    return {
        **stats,
        "total_customers": len(customers),
        "since": today_start.isoformat(),
    }


@admin_router.get("/platform-stats")
async def get_platform_stats(db: DbSession, user=Depends(require_roles(UserRole.SUPER_ADMIN))):
    """The real, cross-tenant Super Admin Dashboard -- every number is a DB aggregate over
    every non-demo business (see RestaurantRepository.platform_counts,
    EngagementRepository.platform_summary_by_type/recent_platform_activity,
    OrderRepository.platform_totals), never a client-side reduce over a paginated list
    like the frontend's previous placeholder computed from GET /restaurants.

    "orders" combines both engines' order-shaped activity: legacy-engine Order rows plus
    generic-engine engagements of type "order" -- reported as separate counted totals
    (orders_legacy / orders_generic) as well as a combined "orders" total, so which engine
    a number came from is never hidden.
    """
    restaurant_repo = RestaurantRepository(db)
    engagement_repo = EngagementRepository(db)
    order_repo = OrderRepository(db)

    business_counts = await restaurant_repo.platform_counts()
    by_type = await engagement_repo.platform_summary_by_type()
    legacy_orders = await order_repo.platform_totals()
    recent = await engagement_repo.recent_platform_activity(limit=10)

    generic_orders = by_type.get("order", {"count": 0, "revenue": 0.0})
    inquiries = by_type.get("inquiry", {"count": 0, "revenue": 0.0})
    appointments = by_type.get("appointment", {"count": 0, "revenue": 0.0})
    bookings = by_type.get("booking", {"count": 0, "revenue": 0.0})

    return {
        "businesses": business_counts,
        "orders_legacy": legacy_orders,
        "orders_generic": generic_orders,
        "orders": {
            "count": legacy_orders["count"] + generic_orders["count"],
            "revenue": legacy_orders["revenue"] + generic_orders["revenue"],
        },
        "inquiries": inquiries,
        "appointments": appointments,
        "bookings": bookings,
        "recent_activity": [
            {
                "id": str(e.id),
                "business_name": e.restaurant.name if e.restaurant else None,
                "type": e.type.value,
                "status": e.status.value,
                "customer_name": e.customer.name if e.customer else None,
                "total": float(e.total),
                "created_at": e.created_at.isoformat(),
            }
            for e in recent
        ],
    }
