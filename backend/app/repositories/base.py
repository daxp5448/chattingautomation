import uuid
from typing import Generic, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import Base

ModelType = TypeVar("ModelType", bound=Base)


class BaseRepository(Generic[ModelType]):
    """Thin CRUD repository, tenant-scoped by `restaurant_id` for aggregates that carry one."""

    model: type[ModelType]

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, id_: uuid.UUID, restaurant_id: uuid.UUID | None = None) -> ModelType | None:
        stmt = select(self.model).where(self.model.id == id_)
        if restaurant_id is not None and hasattr(self.model, "restaurant_id"):
            stmt = stmt.where(self.model.restaurant_id == restaurant_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list(self, restaurant_id: uuid.UUID | None = None, **filters) -> list[ModelType]:
        stmt = select(self.model)
        if restaurant_id is not None and hasattr(self.model, "restaurant_id"):
            stmt = stmt.where(self.model.restaurant_id == restaurant_id)
        for field, value in filters.items():
            stmt = stmt.where(getattr(self.model, field) == value)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, obj: ModelType) -> ModelType:
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def delete(self, obj: ModelType) -> None:
        await self.session.delete(obj)
        await self.session.flush()

    async def commit(self) -> None:
        await self.session.commit()
