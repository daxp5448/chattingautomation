from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.demo_session import DemoSession
from app.repositories.base import BaseRepository


class DemoSessionRepository(BaseRepository[DemoSession]):
    model = DemoSession

    async def get_for_update_by_phone(self, customer_phone: str) -> DemoSession | None:
        """Row-locked read -- same reasoning as GenericConversationStateRepository.
        get_for_update_by_customer: serializes two concurrent/redelivered webhook events
        for the same demo phone number instead of letting both read the same
        pre-transition session and race on the picker/"starting demo" sends."""
        result = await self.session.execute(
            select(DemoSession).where(DemoSession.customer_phone == customer_phone).with_for_update()
        )
        return result.scalar_one_or_none()

    async def get_or_create_for_update(self, customer_phone: str) -> DemoSession:
        existing = await self.get_for_update_by_phone(customer_phone)
        if existing is not None:
            return existing
        session_row = DemoSession(customer_phone=customer_phone, active_restaurant_id=None)
        try:
            return await self.create(session_row)
        except IntegrityError:
            # Lost the race: another concurrent request for this same phone number
            # committed its own row first, tripping the unique constraint on
            # customer_phone. Roll back this failed insert and use the row that won --
            # same pattern as CustomerRepository.get_or_create.
            await self.session.rollback()
            existing = await self.get_for_update_by_phone(customer_phone)
            if existing:
                return existing
            raise
