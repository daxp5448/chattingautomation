import uuid

from sqlalchemy import select

from app.models.staff_member import StaffMember
from app.repositories.base import BaseRepository


class StaffMemberRepository(BaseRepository[StaffMember]):
    model = StaffMember

    async def list_active(self, restaurant_id: uuid.UUID) -> list[StaffMember]:
        stmt = (
            select(StaffMember)
            .where(StaffMember.restaurant_id == restaurant_id, StaffMember.active.is_(True))
            .order_by(StaffMember.name)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
