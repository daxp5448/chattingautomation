"""Celery task: purges accumulated Demo Bot conversation/engagement history so it doesn't
grow unbounded -- every message on the Demo Bot's one WhatsApp number (see
app/services/demo_bot_service.py) creates real Customer/Message/GenericConversationState/
Engagement rows scoped to whichever niche's demo restaurant, exactly like a real business,
and nothing else in this feature ever cleans them up. Demo restaurants themselves (and
their catalog/flow) are never touched -- only conversation history older than
DEMO_DATA_RETENTION_DAYS.

Scheduled via `beat_schedule` in app/tasks/celery_app.py (daily), same mechanism already
running app/tasks/reconciliation.py::check_stuck_payments every 5 minutes.
"""

import asyncio
import logging
from datetime import timedelta

from sqlalchemy import delete, select

from app.db.base import utcnow
from app.db.session import AsyncSessionLocal
from app.models.customer import Customer
from app.models.demo_session import DemoSession
from app.models.engagement import Engagement
from app.models.generic_conversation_state import GenericConversationState
from app.models.message import Message
from app.models.restaurant import Restaurant
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

DEMO_DATA_RETENTION_DAYS = 7


async def _purge_demo_data() -> int:
    """Does the actual purge inside its own DB session. Returns the number of rows
    deleted. Split out from the `purge_demo_data` Celery task below so it can be awaited
    directly in tests without going through `asyncio.run` -- same pattern as
    app/tasks/reconciliation.py::_check_stuck_payments.
    """
    cutoff = utcnow() - timedelta(days=DEMO_DATA_RETENTION_DAYS)
    deleted = 0

    async with AsyncSessionLocal() as session:
        demo_ids = list((await session.execute(select(Restaurant.id).where(Restaurant.is_demo.is_(True)))).scalars().all())

        if demo_ids:
            # Order matters: Engagement first (DB-level ON DELETE CASCADE removes its
            # EngagementItem children automatically), then Customer -- Engagement.
            # customer_id is ON DELETE RESTRICT, so a Customer can't be deleted while any
            # Engagement (even one newer than cutoff) still references it.
            result = await session.execute(
                delete(Engagement).where(Engagement.restaurant_id.in_(demo_ids), Engagement.created_at < cutoff)
            )
            deleted += result.rowcount or 0

            result = await session.execute(
                delete(GenericConversationState).where(
                    GenericConversationState.restaurant_id.in_(demo_ids), GenericConversationState.created_at < cutoff
                )
            )
            deleted += result.rowcount or 0

            result = await session.execute(
                delete(Message).where(Message.restaurant_id.in_(demo_ids), Message.created_at < cutoff)
            )
            deleted += result.rowcount or 0

            still_referenced = select(Engagement.customer_id)
            result = await session.execute(
                delete(Customer).where(
                    Customer.restaurant_id.in_(demo_ids),
                    Customer.created_at < cutoff,
                    Customer.id.not_in(still_referenced),
                )
            )
            deleted += result.rowcount or 0

        result = await session.execute(delete(DemoSession).where(DemoSession.updated_at < cutoff))
        deleted += result.rowcount or 0

        await session.commit()

    return deleted


@celery_app.task(name="app.tasks.demo_data_purge.purge_demo_data")
def purge_demo_data() -> int:
    """Entry point invoked by celery-beat. Celery tasks run synchronously, so this just
    wraps the async DB work in its own event loop -- same pattern as
    app/tasks/reconciliation.py::check_stuck_payments.
    """
    return asyncio.run(_purge_demo_data())
