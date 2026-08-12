import uuid

from sqlalchemy import select

from app.models.bot_config import BotButton, BotMessage
from app.repositories.base import BaseRepository


class BotMessageRepository(BaseRepository[BotMessage]):
    model = BotMessage

    async def get_by_key(self, restaurant_id: uuid.UUID, key: str) -> BotMessage | None:
        stmt = select(BotMessage).where(BotMessage.restaurant_id == restaurant_id, BotMessage.key == key)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def upsert(self, restaurant_id: uuid.UUID, key: str, content: str) -> BotMessage:
        existing = await self.get_by_key(restaurant_id, key)
        if existing:
            existing.content = content
            await self.session.flush()
            return existing
        message = BotMessage(restaurant_id=restaurant_id, key=key, content=content)
        return await self.create(message)


class BotButtonRepository(BaseRepository[BotButton]):
    model = BotButton

    async def list_visible(self, restaurant_id: uuid.UUID) -> list[BotButton]:
        stmt = (
            select(BotButton)
            .where(BotButton.restaurant_id == restaurant_id, BotButton.visible.is_(True))
            .order_by(BotButton.display_order)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
