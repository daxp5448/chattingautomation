import uuid

from sqlalchemy import select

from app.models.catalog import CatalogItem
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
            .order_by(Image.display_order, Image.created_at)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_for_catalog_items(self, catalog_item_ids: list[uuid.UUID], restaurant_id: uuid.UUID) -> list[Image]:
        # Batched variant of list_for_catalog_item -- one IN-query for a whole category's
        # items instead of one query per item, used by
        # image_presenter.py::resolve_item_images_bulk. Ordering still by
        # (display_order, created_at) so a per-item variant-pick downstream sees the same
        # order the single-item version gives.
        if not catalog_item_ids:
            return []
        stmt = (
            select(Image)
            .where(
                Image.catalog_item_id.in_(catalog_item_ids),
                Image.restaurant_id == restaurant_id,
                Image.deleted_at.is_(None),
            )
            .order_by(Image.display_order, Image.created_at)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_for_catalog_category(self, catalog_category_id: uuid.UUID, restaurant_id: uuid.UUID) -> list[Image]:
        stmt = (
            select(Image)
            .where(
                Image.catalog_category_id == catalog_category_id,
                Image.restaurant_id == restaurant_id,
                Image.deleted_at.is_(None),
            )
            .order_by(Image.display_order, Image.created_at)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_for_catalog_categories(self, catalog_category_ids: list[uuid.UUID], restaurant_id: uuid.UUID) -> list[Image]:
        # Batched sibling of list_for_catalog_category -- mirrors list_for_catalog_items,
        # used by image_presenter.py::resolve_category_images_bulk so a "Categories" step
        # with many categories issues one query, not one per category.
        if not catalog_category_ids:
            return []
        stmt = (
            select(Image)
            .where(
                Image.catalog_category_id.in_(catalog_category_ids),
                Image.restaurant_id == restaurant_id,
                Image.deleted_at.is_(None),
            )
            .order_by(Image.display_order, Image.created_at)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_for_flow_step(self, flow_definition_id: uuid.UUID, flow_step_id: str, restaurant_id: uuid.UUID) -> list[Image]:
        stmt = (
            select(Image)
            .where(
                Image.flow_definition_id == flow_definition_id,
                Image.flow_step_id == flow_step_id,
                Image.restaurant_id == restaurant_id,
                Image.deleted_at.is_(None),
            )
            .order_by(Image.display_order, Image.created_at)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_for_flow_definition(self, flow_definition_id: uuid.UUID, restaurant_id: uuid.UUID) -> list[Image]:
        # Batched variant of list_for_flow_step -- one query for every step-image in a
        # whole flow, used by image_presenter.py::resolve_step_images_bulk (renders a
        # step's images while previewing/editing the flow without one query per step).
        stmt = (
            select(Image)
            .where(
                Image.flow_definition_id == flow_definition_id,
                Image.restaurant_id == restaurant_id,
                Image.deleted_at.is_(None),
            )
            .order_by(Image.display_order, Image.created_at)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_for_restaurant(
        self,
        restaurant_id: uuid.UUID,
        *,
        search: str | None = None,
        image_type: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[tuple[Image, CatalogItem | None]]:
        """Restaurant-wide "browse every image" query for the Media Library page --
        distinct from `list_for_catalog_item` above (which every existing caller, e.g.
        the catalog editor, still uses unchanged). Outer-joins CatalogItem (rather than an
        inner join) so this stays correct if a future owner column is added and a given
        Image has no catalog_item_id -- `search` and the owning item's name/category_id
        in the response simply come back empty for such a row instead of the row vanishing.
        Soft-deleted images are always excluded; newest-first, same as every other
        "recent activity" list in this codebase.
        """
        stmt = (
            select(Image, CatalogItem)
            .outerjoin(CatalogItem, Image.catalog_item_id == CatalogItem.id)
            .where(Image.restaurant_id == restaurant_id, Image.deleted_at.is_(None))
        )
        if image_type:
            stmt = stmt.where(Image.image_type == image_type)
        if search:
            stmt = stmt.where(CatalogItem.name.ilike(f"%{search}%"))
        stmt = stmt.order_by(Image.created_at.desc()).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return [(row[0], row[1]) for row in result.all()]
