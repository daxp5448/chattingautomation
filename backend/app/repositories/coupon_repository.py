import uuid

from sqlalchemy import func, select

from app.models.coupon import Coupon, CouponRedemption
from app.repositories.base import BaseRepository


class CouponRepository(BaseRepository[Coupon]):
    model = Coupon

    async def get_by_code(self, restaurant_id: uuid.UUID, code: str) -> Coupon | None:
        stmt = select(Coupon).where(Coupon.restaurant_id == restaurant_id, Coupon.code == code)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_code_for_update(self, restaurant_id: uuid.UUID, code: str) -> Coupon | None:
        """Same as `get_by_code`, but locks the row (`SELECT ... FOR UPDATE`) so concurrent
        eligibility-check-then-redeem sequences for the same coupon serialize instead of
        both reading a stale usage count and over-redeeming a limited coupon. SQLite (used
        in tests) accepts `.with_for_update()` as a no-op rather than erroring, so no
        dialect guard is needed here.
        """
        stmt = select(Coupon).where(Coupon.restaurant_id == restaurant_id, Coupon.code == code).with_for_update()
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_auto_apply(self, restaurant_id: uuid.UUID) -> list[Coupon]:
        stmt = select(Coupon).where(
            Coupon.restaurant_id == restaurant_id, Coupon.auto_apply.is_(True), Coupon.is_active.is_(True)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class CouponRedemptionRepository(BaseRepository[CouponRedemption]):
    model = CouponRedemption

    async def count_for_coupon(self, coupon_id: uuid.UUID) -> int:
        stmt = select(func.count()).where(CouponRedemption.coupon_id == coupon_id)
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def count_for_customer(self, coupon_id: uuid.UUID, customer_id: uuid.UUID) -> int:
        stmt = select(func.count()).where(
            CouponRedemption.coupon_id == coupon_id, CouponRedemption.customer_id == customer_id
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()
