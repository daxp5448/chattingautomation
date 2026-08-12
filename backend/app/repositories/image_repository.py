import uuid

from sqlalchemy import select

from app.models.image import Image
from app.repositories.base import BaseRepository


class ImageRepository(BaseRepository[Image]):
    model = Image

    async def list_for_catalog_item(self, catalog_item_id: uuid.UUID, restaurant_id: uuid.UUID) -> list[Image]:
        stmt = (
            select(Image)
            .where(
                Image.catalog_item_id == catalog_item_id,
                Image.restaurant_id == restaurant_id,
                Image.deleted_at.is_(None),
            )
            .order_by(Image.created_at)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
