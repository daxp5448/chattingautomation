import uuid

from sqlalchemy import select, update

from app.models.catalog import CatalogCategory, CatalogItem
from app.repositories.base import BaseRepository


class CatalogCategoryRepository(BaseRepository[CatalogCategory]):
    model = CatalogCategory

    async def list_visible(self, restaurant_id: uuid.UUID) -> list[CatalogCategory]:
        stmt = (
            select(CatalogCategory)
            .where(CatalogCategory.restaurant_id == restaurant_id, CatalogCategory.visible.is_(True))
            .order_by(CatalogCategory.display_order)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class CatalogItemRepository(BaseRepository[CatalogItem]):
    model = CatalogItem

    async def list_by_category(self, category_id: uuid.UUID, restaurant_id: uuid.UUID) -> list[CatalogItem]:
        stmt = (
            select(CatalogItem)
            .where(
                CatalogItem.category_id == category_id,
                CatalogItem.restaurant_id == restaurant_id,
                CatalogItem.available.is_(True),
            )
            .order_by(CatalogItem.display_order)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def decrement_stock(self, item_id: uuid.UUID, qty: int) -> bool:
        """Atomic check-and-decrement -- identical pattern to
        app/repositories/menu_repository.py::decrement_stock for the legacy engine: the
        WHERE clause re-checks current stock in the same UPDATE that decrements it, so
        two concurrent engagements racing for the last unit can't both read "enough
        stock" before either commits. Returns False (nothing decremented) if there isn't
        enough stock right now.
        """
        result = await self.session.execute(
            update(CatalogItem)
            .where(CatalogItem.id == item_id, CatalogItem.stock_quantity >= qty)
            .values(stock_quantity=CatalogItem.stock_quantity - qty)
        )
        return result.rowcount > 0
