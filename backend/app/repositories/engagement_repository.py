import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.models.engagement import Engagement
from app.models.enums import EngagementStatus, EngagementType
from app.models.restaurant import Restaurant
from app.repositories.base import BaseRepository


class EngagementRepository(BaseRepository[Engagement]):
    model = Engagement

    async def get_with_items(self, id_: uuid.UUID, restaurant_id: uuid.UUID) -> Engagement | None:
        stmt = (
            select(Engagement)
            .options(selectinload(Engagement.items), selectinload(Engagement.customer))
            .where(Engagement.id == id_, Engagement.restaurant_id == restaurant_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_with_items(
        self,
        restaurant_id: uuid.UUID,
        type_filter: EngagementType | None = None,
        status_filter: EngagementStatus | None = None,
        branch_id: uuid.UUID | None = None,
    ) -> list[Engagement]:
        """The per-business "Orders/Bookings/Appointments/Leads" list -- the generic-engine
        counterpart of OrderRepository.list_with_items, same filter shape (type/status/
        branch), used by GET /restaurants/{id}/engagements.
        """
        stmt = (
            select(Engagement)
            .options(selectinload(Engagement.items), selectinload(Engagement.customer))
            .where(Engagement.restaurant_id == restaurant_id)
            .order_by(Engagement.created_at.desc())
        )
        if type_filter is not None:
            stmt = stmt.where(Engagement.type == type_filter)
        if status_filter is not None:
            stmt = stmt.where(Engagement.status == status_filter)
        if branch_id is not None:
            stmt = stmt.where(Engagement.branch_id == branch_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def platform_summary_by_type(self) -> dict[str, dict]:
        """Platform-wide engagement counts + revenue grouped by type (order/inquiry/
        appointment/booking), across every non-demo restaurant -- the Super Admin
        Dashboard's real Orders/Leads/Appointments/Bookings numbers (see
        app/api/v1/routers/dashboard.py's /admin/platform-stats), as opposed to
        OrderRepository.dashboard_stats's single-business view.
        """
        stmt = (
            select(Engagement.type, func.count(Engagement.id), func.coalesce(func.sum(Engagement.total), 0))
            .join(Restaurant, Restaurant.id == Engagement.restaurant_id)
            .where(Restaurant.is_demo.is_(False))
            .group_by(Engagement.type)
        )
        result = await self.session.execute(stmt)
        return {row[0].value: {"count": row[1], "revenue": float(row[2])} for row in result.all()}

    async def recent_platform_activity(self, limit: int = 10) -> list[Engagement]:
        """Newest engagements across every non-demo restaurant, for the Super Admin
        Dashboard's "Recent activity" feed."""
        stmt = (
            select(Engagement)
            .join(Restaurant, Restaurant.id == Engagement.restaurant_id)
            .where(Restaurant.is_demo.is_(False))
            .options(selectinload(Engagement.customer), selectinload(Engagement.restaurant))
            .order_by(Engagement.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
