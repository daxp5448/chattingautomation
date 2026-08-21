from datetime import datetime

from sqlalchemy import select

from app.models.meta_media_cache import MetaMediaCache
from app.repositories.base import BaseRepository


class MetaMediaCacheRepository(BaseRepository[MetaMediaCache]):
    model = MetaMediaCache

    async def get(self, phone_number_id: str, image_url: str) -> MetaMediaCache | None:  # type: ignore[override]
        stmt = select(MetaMediaCache).where(
            MetaMediaCache.phone_number_id == phone_number_id,
            MetaMediaCache.image_url == image_url,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def upsert(self, restaurant_id, phone_number_id: str, image_url: str, media_id: str, uploaded_at: datetime) -> None:
        existing = await self.get(phone_number_id, image_url)
        if existing is not None:
            existing.media_id = media_id
            existing.uploaded_at = uploaded_at
            return
        self.session.add(
            MetaMediaCache(
                restaurant_id=restaurant_id, phone_number_id=phone_number_id,
                image_url=image_url, media_id=media_id, uploaded_at=uploaded_at,
            )
        )
        await self.session.flush()
