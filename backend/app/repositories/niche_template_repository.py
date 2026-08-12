from sqlalchemy import select

from app.models.niche_template import NicheTemplate
from app.repositories.base import BaseRepository


class NicheTemplateRepository(BaseRepository[NicheTemplate]):
    model = NicheTemplate

    async def get_by_code(self, code: str) -> NicheTemplate | None:
        result = await self.session.execute(select(NicheTemplate).where(NicheTemplate.code == code))
        return result.scalar_one_or_none()

    async def list_all(self) -> list[NicheTemplate]:
        result = await self.session.execute(select(NicheTemplate).order_by(NicheTemplate.name))
        return list(result.scalars().all())
