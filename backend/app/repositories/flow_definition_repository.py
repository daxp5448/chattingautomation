import uuid

from sqlalchemy import select

from app.models.flow_definition import FlowDefinition
from app.repositories.base import BaseRepository


class FlowDefinitionRepository(BaseRepository[FlowDefinition]):
    model = FlowDefinition

    async def get_by_restaurant(self, restaurant_id: uuid.UUID) -> FlowDefinition | None:
        result = await self.session.execute(
            select(FlowDefinition).where(FlowDefinition.restaurant_id == restaurant_id)
        )
        return result.scalar_one_or_none()

    async def get_for_update_by_restaurant(self, restaurant_id: uuid.UUID) -> FlowDefinition | None:
        """Row-locked read for the home-buttons PATCH (app/api/v1/routers/
        flow_definitions.py) -- same reasoning as
        GenericConversationStateRepository.get_for_update_by_customer: two concurrent
        edits (or a stale browser tab) to the same business's flow must serialize instead
        of silently dropping one.
        """
        result = await self.session.execute(
            select(FlowDefinition).where(FlowDefinition.restaurant_id == restaurant_id).with_for_update()
        )
        return result.scalar_one_or_none()
