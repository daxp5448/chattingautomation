import uuid

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.conversation_state import ConversationState
from app.models.enums import ConversationStep
from app.models.message import Message
from app.repositories.base import BaseRepository


class MessageRepository(BaseRepository[Message]):
    model = Message

    async def get_by_wa_message_id(self, wa_message_id: str) -> Message | None:
        stmt = select(Message).where(Message.wa_message_id == wa_message_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_customer(self, restaurant_id: uuid.UUID, customer_id: uuid.UUID) -> list[Message]:
        stmt = (
            select(Message)
            .where(Message.restaurant_id == restaurant_id, Message.customer_id == customer_id)
            .order_by(Message.created_at.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_handed_over_conversations(self, restaurant_id: uuid.UUID) -> list[ConversationState]:
        """Conversations currently waiting on a staff reply, most recently updated first."""
        stmt = (
            select(ConversationState)
            .options(selectinload(ConversationState.customer))
            .where(
                ConversationState.restaurant_id == restaurant_id,
                ConversationState.current_step == ConversationStep.HANDED_OVER,
            )
            .order_by(ConversationState.updated_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
