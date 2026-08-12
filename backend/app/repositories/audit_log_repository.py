import uuid

from sqlalchemy import select

from app.models.audit_log import AuditLog
from app.repositories.base import BaseRepository


class AuditLogRepository(BaseRepository[AuditLog]):
    model = AuditLog

    async def list_for_restaurant(self, restaurant_id: uuid.UUID, limit: int = 100) -> list[AuditLog]:
        stmt = (
            select(AuditLog)
            .where(AuditLog.restaurant_id == restaurant_id)
            .order_by(AuditLog.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def record(
        self,
        *,
        actor_id: uuid.UUID | None,
        restaurant_id: uuid.UUID | None,
        action: str,
        entity: str,
        entity_id: str | None,
        diff: dict,
    ) -> AuditLog:
        entry = AuditLog(
            actor_id=actor_id,
            restaurant_id=restaurant_id,
            action=action,
            entity=entity,
            entity_id=entity_id,
            diff=diff,
        )
        return await self.create(entry)
