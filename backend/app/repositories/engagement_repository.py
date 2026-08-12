import uuid

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.engagement import Engagement
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

    async def list_with_items(self, restaurant_id: uuid.UUID) -> list[Engagement]:
        stmt = (
            select(Engagement)
            .options(selectinload(Engagement.items), selectinload(Engagement.customer))
            .where(Engagement.restaurant_id == restaurant_id)
            .order_by(Engagement.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
