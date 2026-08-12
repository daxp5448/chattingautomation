import uuid

from sqlalchemy import select

from app.models.broadcast import BroadcastCampaign, BroadcastRecipient
from app.models.enums import BroadcastRecipientStatus, BroadcastStatus
from app.repositories.base import BaseRepository


class BroadcastCampaignRepository(BaseRepository[BroadcastCampaign]):
    model = BroadcastCampaign

    async def list_due_scheduled(self, now) -> list[BroadcastCampaign]:
        """Cross-tenant -- used only by the beat-task dispatcher (app/tasks/
        broadcast_dispatch.py), never by a tenant-scoped router handler. See that
        module's docstring for why this polls instead of using Celery's apply_async(eta=)."""
        result = await self.session.execute(
            select(BroadcastCampaign).where(
                BroadcastCampaign.status == BroadcastStatus.SCHEDULED, BroadcastCampaign.scheduled_at <= now
            )
        )
        return list(result.scalars().all())


class BroadcastRecipientRepository(BaseRepository[BroadcastRecipient]):
    model = BroadcastRecipient

    async def list_pending_for_campaign(self, campaign_id: uuid.UUID) -> list[BroadcastRecipient]:
        result = await self.session.execute(
            select(BroadcastRecipient).where(
                BroadcastRecipient.campaign_id == campaign_id, BroadcastRecipient.status == BroadcastRecipientStatus.PENDING
            )
        )
        return list(result.scalars().all())

    async def list_for_campaign(self, campaign_id: uuid.UUID) -> list[BroadcastRecipient]:
        result = await self.session.execute(select(BroadcastRecipient).where(BroadcastRecipient.campaign_id == campaign_id))
        return list(result.scalars().all())
