import uuid

from sqlalchemy import select

from app.models.generic_conversation_state import GenericConversationState
from app.repositories.base import BaseRepository


class GenericConversationStateRepository(BaseRepository[GenericConversationState]):
    model = GenericConversationState

    async def get_for_update_by_customer(self, customer_id: uuid.UUID) -> GenericConversationState | None:
        """Row-locked fetch, same reasoning as app/services/flow_engine.py's
        ConversationState lock: serializes two concurrent/redelivered webhook events for
        the same customer instead of letting both read the same pre-transition step and
        both advance it.
        """
        stmt = select(GenericConversationState).where(
            GenericConversationState.customer_id == customer_id
        ).with_for_update()
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_customer(self, customer_id: uuid.UUID, restaurant_id: uuid.UUID) -> GenericConversationState | None:
        """Tenant-scoped fetch for app/api/v1/routers/generic_conversations.py -- unlike
        get_for_update_by_customer above (whose only caller, the webhook handler,
        already knows customer_id is restaurant-scoped via how it was looked up), a
        router handler must verify restaurant_id itself."""
        stmt = select(GenericConversationState).where(
            GenericConversationState.customer_id == customer_id, GenericConversationState.restaurant_id == restaurant_id
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_handed_over(self, restaurant_id: uuid.UUID) -> list[GenericConversationState]:
        """Conversations currently waiting on a staff reply, most recently updated
        first. No `customer` relationship exists on this model (unlike the legacy
        ConversationState) -- callers needing customer details do a second lookup via
        CustomerRepository, the same pattern generic_flow_engine.py already uses
        throughout this file."""
        stmt = (
            select(GenericConversationState)
            .where(GenericConversationState.restaurant_id == restaurant_id, GenericConversationState.is_handed_over.is_(True))
            .order_by(GenericConversationState.updated_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
