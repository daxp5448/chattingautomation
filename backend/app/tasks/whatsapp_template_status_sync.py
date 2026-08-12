"""Celery task: polls Meta for the current approval status of every PENDING
WhatsAppTemplate. Meta doesn't reliably push status changes to an app without separate
webhook-subscription configuration (out of scope here), so this is the safety net --
same reasoning as app/tasks/reconciliation.py's payment-status polling, and an identical
shape: async worker (directly awaitable in tests) + thin sync Celery entrypoint.

Scheduled via `beat_schedule` in app/tasks/celery_app.py, every 15 minutes -- template
review turnaround is hours-to-days, not seconds-to-minutes, so tighter polling than
reconciliation's 5-minute cadence would add load with no real benefit.
"""

import asyncio
import logging

from app.db.base import utcnow
from app.db.session import AsyncSessionLocal
from app.models.enums import TemplateStatus
from app.models.restaurant import Restaurant
from app.repositories.whatsapp_template_repository import WhatsAppTemplateRepository
from app.services import whatsapp_template_client
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

_APPROVED_STATUSES = {"approved"}
_REJECTED_STATUSES = {"rejected"}
_DISABLED_STATUSES = {"disabled", "paused"}


async def _sync_template_statuses() -> int:
    """Does the actual polling work inside its own DB session. Returns the number of
    templates whose status changed. Split out from `sync_template_statuses` below so it
    can be awaited directly in tests without `asyncio.run` (can't be called from an
    already-running event loop, e.g. under pytest-asyncio) -- same pattern as
    app/tasks/reconciliation.py::_check_stuck_payments.
    """
    updated = 0

    async with AsyncSessionLocal() as session:
        repo = WhatsAppTemplateRepository(session)
        templates = await repo.list_pending()

        for template in templates:
            restaurant = await session.get(Restaurant, template.restaurant_id)
            if restaurant is None or not template.meta_template_id:
                continue
            try:
                result = await whatsapp_template_client.get_template_status(restaurant, template.meta_template_id)
            except Exception:
                # One bad lookup (gateway timeout, malformed response, revoked token,
                # etc.) must not kill the rest of the batch -- log and move on.
                logger.warning(
                    "WhatsApp template status sync: failed to check template %s (restaurant %s)",
                    template.id,
                    template.restaurant_id,
                    exc_info=True,
                )
                continue

            meta_status = str(result.get("status") or "").lower()
            new_status = None
            if meta_status in _APPROVED_STATUSES:
                new_status = TemplateStatus.APPROVED
            elif meta_status in _REJECTED_STATUSES:
                new_status = TemplateStatus.REJECTED
            elif meta_status in _DISABLED_STATUSES:
                new_status = TemplateStatus.DISABLED
            # Anything else (still "in_appeal"/"pending"/unrecognized) is left alone --
            # a later run will pick it back up.

            template.last_synced_at = utcnow()
            if new_status is not None and new_status != template.status:
                template.status = new_status
                template.rejection_reason = result.get("rejected_reason") if new_status == TemplateStatus.REJECTED else None
                updated += 1

            try:
                await session.commit()
            except Exception:
                await session.rollback()
                logger.warning(
                    "WhatsApp template status sync: failed to persist status for template %s", template.id, exc_info=True
                )
                continue

    return updated


@celery_app.task(name="app.tasks.whatsapp_template_status_sync.sync_template_statuses")
def sync_template_statuses() -> int:
    """Entry point invoked by celery-beat on the `beat_schedule` in
    app/tasks/celery_app.py. Celery tasks run synchronously, so this just wraps the
    async DB/gateway work in its own event loop.
    """
    return asyncio.run(_sync_template_statuses())
