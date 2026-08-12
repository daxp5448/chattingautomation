import uuid
from datetime import datetime, timezone

from fastapi import APIRouter

from app.core.deps import CurrentUser, DbSession, resolve_tenant_id
from app.repositories.customer_repository import CustomerRepository
from app.repositories.order_repository import OrderRepository

router = APIRouter(prefix="/restaurants/{restaurant_id}/dashboard", tags=["dashboard"])


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
