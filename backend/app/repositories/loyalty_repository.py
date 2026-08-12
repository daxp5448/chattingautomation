import uuid

from sqlalchemy import select

from app.models.loyalty import LoyaltyTransaction
from app.repositories.base import BaseRepository


class LoyaltyTransactionRepository(BaseRepository[LoyaltyTransaction]):
    model = LoyaltyTransaction

    async def list_for_customer(self, restaurant_id: uuid.UUID, customer_id: uuid.UUID) -> list[LoyaltyTransaction]:
        stmt = (
            select(LoyaltyTransaction)
            .where(LoyaltyTransaction.restaurant_id == restaurant_id, LoyaltyTransaction.customer_id == customer_id)
            .order_by(LoyaltyTransaction.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
