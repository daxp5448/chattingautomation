import uuid

from sqlalchemy import func, select

from app.models.jewellery_design import JewelleryDesign
from app.repositories.base import BaseRepository


class JewelleryDesignRepository(BaseRepository[JewelleryDesign]):
    model = JewelleryDesign

    async def list_materials(self, restaurant_id: uuid.UUID) -> list[str]:
        # Deliberately NOT filtered on is_active: a material whose designs are all
        # temporarily deactivated should still be tappable, landing on the graceful
        # "no designs available" empty state (see _render_jewellery_gallery) rather than
        # silently vanishing from the menu -- only list_designs/count_designs (the actual
        # page content) filter on is_active.
        stmt = (
            select(func.distinct(JewelleryDesign.material))
            .where(JewelleryDesign.restaurant_id == restaurant_id)
            .order_by(JewelleryDesign.material)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_categories(self, restaurant_id: uuid.UUID, material: str) -> list[str]:
        # Same reasoning as list_materials above -- not filtered on is_active.
        stmt = (
            select(func.distinct(JewelleryDesign.category))
            .where(
                JewelleryDesign.restaurant_id == restaurant_id,
                JewelleryDesign.material == material,
            )
            .order_by(JewelleryDesign.category)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_designs(
        self, restaurant_id: uuid.UUID, material: str, category: str, offset: int, limit: int
    ) -> list[JewelleryDesign]:
        stmt = (
            select(JewelleryDesign)
            .where(
                JewelleryDesign.restaurant_id == restaurant_id,
                JewelleryDesign.material == material,
                JewelleryDesign.category == category,
                JewelleryDesign.is_active.is_(True),
            )
            .order_by(JewelleryDesign.display_order, JewelleryDesign.created_at)
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_designs(self, restaurant_id: uuid.UUID, material: str, category: str) -> int:
        stmt = select(func.count()).select_from(
            select(JewelleryDesign.id)
            .where(
                JewelleryDesign.restaurant_id == restaurant_id,
                JewelleryDesign.material == material,
                JewelleryDesign.category == category,
                JewelleryDesign.is_active.is_(True),
            )
            .subquery()
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()
