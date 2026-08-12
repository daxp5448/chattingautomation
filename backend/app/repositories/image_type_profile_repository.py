from sqlalchemy import select

from app.models.image_type_profile import ImageTypeProfile
from app.repositories.base import BaseRepository


class ImageTypeProfileRepository(BaseRepository[ImageTypeProfile]):
    model = ImageTypeProfile

    async def get_by_code(self, code: str) -> ImageTypeProfile | None:
        result = await self.session.execute(select(ImageTypeProfile).where(ImageTypeProfile.code == code))
        return result.scalar_one_or_none()

    async def list_all(self) -> list[ImageTypeProfile]:
        result = await self.session.execute(select(ImageTypeProfile).order_by(ImageTypeProfile.label))
        return list(result.scalars().all())
