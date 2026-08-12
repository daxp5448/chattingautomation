"""Celery task: sends a BroadcastCampaign's pending recipients, one at a time.

Per-recipient commit (not batched) is deliberate -- there's no dedupe/idempotency key on
the outbound WhatsApp send itself, so per-recipient commit is the only way "resume after
a crash" is actually true rather than approximately true: a task restart re-fetches only
the still-PENDING rows (app/repositories/broadcast_repository.py::list_pending_for_campaign)
and never re-sends to a row already marked SENT/FAILED/SKIPPED.

Two safety mechanisms neither of which exists anywhere else in this codebase yet:
- A consecutive-failure circuit breaker: aborts the rest of the campaign rather than
  burning through a possibly-thousands-long recipient list on a revoked token or a
  platform-wide outage.
- customer.is_blocked / anonymized-marker is re-checked immediately before EACH send, not
  only once at snapshot time (app/api/v1/routers/broadcasts.py::start_campaign) -- a
  campaign can take minutes to work through, and a customer can withdraw consent or
  request erasure while it's running. See app/models/broadcast.py's docstrings.

SEND_PACING_SECONDS is a module attribute (not a bare constant baked into the sleep call)
specifically so tests can zero it out -- every other Celery task in this codebase is
directly awaitable so tests skip real delays entirely; a real sleep per loop iteration
needs to stay overridable the same way.
"""

import asyncio
import logging

from app.core.security import decrypt_secret
from app.core.ws_manager import manager as ws_manager
from app.db.base import utcnow
from app.db.session import AsyncSessionLocal
from app.models.broadcast import BroadcastCampaign
from app.models.customer import Customer
from app.models.enums import BroadcastRecipientStatus, BroadcastStatus
from app.models.restaurant import Restaurant
from app.models.whatsapp_template import WhatsAppTemplate
from app.repositories.broadcast_repository import BroadcastRecipientRepository
from app.services import broadcast_service
from app.services.whatsapp_client import GraphAPIWhatsAppSender, OutboundMessage
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

# Swap for InMemoryWhatsAppSender in tests, same module-level-singleton pattern as
# every router this session that sends WhatsApp messages.
_sender = GraphAPIWhatsAppSender()

CONSECUTIVE_FAILURE_LIMIT = 5
# Overridable in tests (monkeypatch this module attribute to 0) -- see module docstring.
SEND_PACING_SECONDS = 0.5


async def _send_broadcast_campaign(campaign_id: str) -> dict:
    """Does the actual send loop inside its own DB session. Returns a small summary dict
    for tests/logging. Split out from `send_broadcast_campaign` below so it can be
    awaited directly in tests without `asyncio.run` -- same pattern as every other task
    this session (reconciliation.py, whatsapp_template_status_sync.py).
    """
    async with AsyncSessionLocal() as session:
        campaign = await session.get(BroadcastCampaign, campaign_id)
        if campaign is None or campaign.status != BroadcastStatus.SENDING:
            # Already cancelled/completed/never actually started SENDING -- nothing to do.
            # Guards against a redundant .delay() call or a race with a cancel request.
            return {"sent": 0, "failed": 0, "skipped": 0}

        restaurant = await session.get(Restaurant, campaign.restaurant_id)
        template = await session.get(WhatsAppTemplate, campaign.template_id)
        if restaurant is None or template is None:
            campaign.status = BroadcastStatus.FAILED
            campaign.failure_reason = "Restaurant or template no longer exists"
            campaign.completed_at = utcnow()
            await session.commit()
            return {"sent": 0, "failed": 0, "skipped": 0}

        access_token = decrypt_secret(restaurant.whatsapp_access_token_encrypted or "")
        phone_number_id = restaurant.whatsapp_phone_number_id or ""

        pending = await BroadcastRecipientRepository(session).list_pending_for_campaign(campaign.id)
        sent = failed = skipped = 0
        consecutive_failures = 0

        for recipient in pending:
            await session.refresh(campaign)
            if campaign.status == BroadcastStatus.CANCELLED:
                break

            customer = await session.get(Customer, recipient.customer_id)
            if customer is None or customer.is_blocked or "anonymized" in customer.tags:
                recipient.status = BroadcastRecipientStatus.SKIPPED
                skipped += 1
                try:
                    await session.commit()
                except Exception:
                    await session.rollback()
                    logger.warning("Broadcast %s: failed to persist skip for recipient %s", campaign.id, recipient.id, exc_info=True)
                continue

            try:
                values = broadcast_service.resolve_variable_values(campaign.variable_template, customer)
                await _sender.send(
                    phone_number_id, access_token,
                    OutboundMessage.template(customer.phone, template.name, template.language, values),
                )
            except Exception as exc:
                recipient.status = BroadcastRecipientStatus.FAILED
                recipient.error_reason = str(exc)[:500]
                campaign.failed_count += 1
                failed += 1
                consecutive_failures += 1
            else:
                recipient.status = BroadcastRecipientStatus.SENT
                recipient.sent_at = utcnow()
                campaign.sent_count += 1
                sent += 1
                consecutive_failures = 0

            try:
                await session.commit()
            except Exception:
                await session.rollback()
                logger.warning("Broadcast %s: failed to persist outcome for recipient %s", campaign.id, recipient.id, exc_info=True)
                continue

            await ws_manager.broadcast(
                campaign.restaurant_id,
                {"type": "broadcast_progress", "campaign_id": str(campaign.id), "sent": campaign.sent_count, "failed": campaign.failed_count, "total": campaign.total_recipients},
            )

            if consecutive_failures >= CONSECUTIVE_FAILURE_LIMIT:
                campaign.status = BroadcastStatus.FAILED
                campaign.failure_reason = f"Aborted after {CONSECUTIVE_FAILURE_LIMIT} consecutive send failures"
                campaign.completed_at = utcnow()
                await session.commit()
                return {"sent": sent, "failed": failed, "skipped": skipped}

            if SEND_PACING_SECONDS:
                await asyncio.sleep(SEND_PACING_SECONDS)

        await session.refresh(campaign)
        if campaign.status == BroadcastStatus.SENDING:
            campaign.status = BroadcastStatus.COMPLETED
            campaign.completed_at = utcnow()
            await session.commit()
        elif campaign.status == BroadcastStatus.CANCELLED and campaign.completed_at is None:
            campaign.completed_at = utcnow()
            await session.commit()

        return {"sent": sent, "failed": failed, "skipped": skipped}


@celery_app.task(name="app.tasks.broadcast_sender.send_broadcast_campaign")
def send_broadcast_campaign(campaign_id: str) -> dict:
    """Entry point invoked via `.delay()` from app/api/v1/routers/broadcasts.py::
    start_campaign, and from the beat-task dispatcher (app/tasks/broadcast_dispatch.py)
    once a SCHEDULED campaign comes due. Celery tasks run synchronously, so this just
    wraps the async DB/gateway work in its own event loop.
    """
    return asyncio.run(_send_broadcast_campaign(campaign_id))
