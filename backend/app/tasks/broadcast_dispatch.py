"""Celery task: polls for BroadcastCampaigns whose `scheduled_at` has come due and
dispatches their actual send.

Deliberately NOT Celery's `apply_async(eta=scheduled_at)` -- this project's Celery broker
is Redis with the default `visibility_timeout` (3600s) and no `broker_transport_options`
override anywhere in the codebase. Celery holds ETA tasks unacknowledged on the broker
until they fire; if the delay exceeds the visibility timeout, Redis's unacked-message
redelivery can make the message visible to another consumer while the original worker is
still legitimately holding it -- causing the same campaign to send to every recipient
twice. "Schedule for tomorrow 9am" is the headline use case for `scheduled_at`, not an
edge case, so this isn't a corner worth cutting.

Instead: reapplies the same "poll for due work" pattern this codebase already uses twice
(app/tasks/reconciliation.py, app/tasks/whatsapp_template_status_sync.py). Scheduled via
`beat_schedule` in app/tasks/celery_app.py, every 15 minutes -- fine granularity for
"scheduled for a specific hour," not a precision-timing mechanism.
"""

import asyncio
import logging
from datetime import datetime

from app.db.base import utcnow
from app.db.session import AsyncSessionLocal
from app.models.enums import BroadcastStatus
from app.repositories.broadcast_repository import BroadcastCampaignRepository
from app.services import broadcast_service
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


async def _dispatch_due_campaigns() -> int:
    """Does the actual dispatch work inside its own DB session. Returns the number of
    campaigns handed off to the send task. Split out from `dispatch_due_campaigns` below
    so it can be awaited directly in tests -- same pattern as every other task this
    session.
    """
    dispatched = 0
    now: datetime = utcnow()

    async with AsyncSessionLocal() as session:
        repo = BroadcastCampaignRepository(session)
        due = await repo.list_due_scheduled(now)

        for campaign in due:
            campaign.status = BroadcastStatus.SENDING
            campaign.started_at = now if campaign.started_at is None else campaign.started_at
            try:
                await session.commit()
            except Exception:
                await session.rollback()
                logger.warning("Broadcast dispatch: failed to flip campaign %s to SENDING", campaign.id, exc_info=True)
                continue
            await broadcast_service.enqueue_broadcast_send(campaign.id)
            dispatched += 1

    return dispatched


@celery_app.task(name="app.tasks.broadcast_dispatch.dispatch_due_campaigns")
def dispatch_due_campaigns() -> int:
    """Entry point invoked by celery-beat on the `beat_schedule` in
    app/tasks/celery_app.py. Celery tasks run synchronously, so this just wraps the
    async DB work in its own event loop.
    """
    return asyncio.run(_dispatch_due_campaigns())
