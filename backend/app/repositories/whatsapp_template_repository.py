import uuid

from sqlalchemy import select

from app.models.enums import TemplateStatus
from app.models.whatsapp_template import WhatsAppTemplate
from app.repositories.base import BaseRepository


class WhatsAppTemplateRepository(BaseRepository[WhatsAppTemplate]):
    model = WhatsAppTemplate

    async def get_by_name(self, restaurant_id: uuid.UUID, name: str) -> WhatsAppTemplate | None:
        result = await self.session.execute(
            select(WhatsAppTemplate).where(WhatsAppTemplate.restaurant_id == restaurant_id, WhatsAppTemplate.name == name)
        )
        return result.scalar_one_or_none()

    async def list_pending(self) -> list[WhatsAppTemplate]:
        """Cross-tenant -- used only by the status-polling task (app/tasks/
        whatsapp_template_status_sync.py), never by a tenant-scoped router handler."""
        result = await self.session.execute(select(WhatsAppTemplate).where(WhatsAppTemplate.status == TemplateStatus.PENDING))
        return list(result.scalars().all())
