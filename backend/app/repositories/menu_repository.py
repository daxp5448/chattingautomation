import uuid

from sqlalchemy import exists, or_, select, update
from sqlalchemy.orm import selectinload

from app.models.category import Category
from app.models.product import Addon, Product, product_branch
from app.repositories.base import BaseRepository


class CategoryRepository(BaseRepository[Category]):
    model = Category


class ProductRepository(BaseRepository[Product]):
    model = Product

    async def get_with_relations(self, id_: uuid.UUID, restaurant_id: uuid.UUID) -> Product | None:
        stmt = (
            select(Product)
            .options(selectinload(Product.branches), selectinload(Product.addons))
            .where(Product.id == id_, Product.restaurant_id == restaurant_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    def _scope_to_branch(stmt, branch_id: uuid.UUID | None):
        """Restricts `stmt` (already selecting `Product`) to products available at
        `branch_id`: either explicitly linked to it via the `product_branch` M2M table, or
        carrying no branch assignment at all (zero `product_branch` rows for that product),
        which is the M2M's implicit signal for "available at every branch" -- there's no
        separate boolean flag on Product for that. `branch_id=None` (single-branch
        restaurants, or a caller that hasn't threaded a branch through) leaves the query
        unfiltered, matching the pre-existing behavior.
        """
        if branch_id is None:
            return stmt
        assigned_to_branch = exists().where(
            product_branch.c.product_id == Product.id, product_branch.c.branch_id == branch_id
        )
        has_any_branch_assignment = exists().where(product_branch.c.product_id == Product.id)
        return stmt.where(or_(assigned_to_branch, ~has_any_branch_assignment))

    async def list_by_category(
        self, category_id: uuid.UUID, restaurant_id: uuid.UUID, branch_id: uuid.UUID | None = None
    ) -> list[Product]:
        stmt = select(Product).where(
            Product.category_id == category_id,
            Product.restaurant_id == restaurant_id,
            Product.available.is_(True),
        )
        stmt = self._scope_to_branch(stmt, branch_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_featured(self, restaurant_id: uuid.UUID, branch_id: uuid.UUID | None = None) -> list[Product]:
        stmt = select(Product).where(
            Product.restaurant_id == restaurant_id,
            Product.is_featured.is_(True),
            Product.available.is_(True),
        )
        stmt = self._scope_to_branch(stmt, branch_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def decrement_stock(self, product_id: uuid.UUID, qty: int) -> bool:
        """Atomic check-and-decrement, mirroring the pattern in
        `app/services/loyalty_service.py::redeem_points`: the WHERE clause re-checks the
        current stock at the DB level in the same UPDATE that decrements it, so two
        concurrent orders racing for the last unit of a product can't both read "enough
        stock" before either commits and oversell it. Returns False (no row matched) if
        there isn't enough stock right now -- callers must treat that as a rejection, not a
        no-op; nothing is decremented on a False return.
        """
        result = await self.session.execute(
            update(Product)
            .where(Product.id == product_id, Product.stock_quantity >= qty)
            .values(stock_quantity=Product.stock_quantity - qty)
        )
        return result.rowcount > 0


class AddonRepository(BaseRepository[Addon]):
    model = Addon
