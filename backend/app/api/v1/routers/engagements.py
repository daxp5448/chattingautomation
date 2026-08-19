"""The generic-engine counterpart of orders.py -- "Orders/Bookings/Appointments/Leads"
for any business on the generic multi-niche engine (Restaurant.uses_generic_engine=True).
Reuses the exact same EngagementRepository/Engagement model the real bot already writes
to (see generic_flow_engine.py::_Engine._create_engagement) -- this is the first HTTP
surface for that data; EngagementRepository.list_with_items/get_with_items existed
already but had no router wired to them before this file.
"""

import logging
import uuid

from fastapi import APIRouter, HTTPException, status

from app.core.deps import CurrentUser, DbSession, resolve_branch_scope, resolve_tenant_id
from app.core.ws_manager import manager as ws_manager
from app.models.engagement import Engagement
from app.models.enums import EngagementStatus, EngagementType
from app.repositories.customer_repository import CustomerRepository
from app.repositories.engagement_repository import EngagementRepository
from app.repositories.niche_template_repository import NicheTemplateRepository
from app.repositories.restaurant_repository import RestaurantRepository
from app.schemas.engagement import EngagementRead, EngagementStatusUpdate
from app.services.generic_flow_engine import send_generic_message
from app.services.whatsapp_client import GraphAPIWhatsAppSender, OutboundMessage

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/restaurants/{restaurant_id}/engagements", tags=["engagements"])

_sender = GraphAPIWhatsAppSender()

# Same shape as orders.py's _LEGAL_TRANSITIONS -- one small status set shared by every
# engagement type (see EngagementStatus's docstring: niche terminology only changes the
# *label*, never this underlying graph).
_LEGAL_TRANSITIONS: dict[EngagementStatus, set[EngagementStatus]] = {
    EngagementStatus.NEW: {EngagementStatus.CONFIRMED, EngagementStatus.CANCELLED},
    EngagementStatus.CONFIRMED: {EngagementStatus.IN_PROGRESS, EngagementStatus.CANCELLED},
    EngagementStatus.IN_PROGRESS: {EngagementStatus.COMPLETED, EngagementStatus.CANCELLED},
    EngagementStatus.COMPLETED: set(),
    EngagementStatus.CANCELLED: set(),
}

_TYPE_NOUN = {
    EngagementType.ORDER: "order",
    EngagementType.INQUIRY: "enquiry",
    EngagementType.APPOINTMENT: "appointment",
    EngagementType.BOOKING: "booking",
}


def _to_read(engagement: Engagement) -> EngagementRead:
    read = EngagementRead.model_validate(engagement, from_attributes=True)
    read.customer_name = engagement.customer.name if engagement.customer else None
    read.customer_phone = engagement.customer.phone if engagement.customer else ""
    return read


@router.get("", response_model=list[EngagementRead])
async def list_engagements(
    restaurant_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
    type_filter: EngagementType | None = None,
    status_filter: EngagementStatus | None = None,
    branch_id: uuid.UUID | None = None,
):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    effective_branch_id = resolve_branch_scope(user, branch_id)
    repo = EngagementRepository(db)
    engagements = await repo.list_with_items(tenant_id, type_filter, status_filter, effective_branch_id)
    return [_to_read(e) for e in engagements]


@router.get("/{engagement_id}", response_model=EngagementRead)
async def get_engagement(restaurant_id: uuid.UUID, engagement_id: uuid.UUID, db: DbSession, user: CurrentUser):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    repo = EngagementRepository(db)
    engagement = await repo.get_with_items(engagement_id, tenant_id)
    if not engagement:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return _to_read(engagement)


@router.patch("/{engagement_id}/status", response_model=EngagementRead)
async def update_engagement_status(
    restaurant_id: uuid.UUID, engagement_id: uuid.UUID, payload: EngagementStatusUpdate, db: DbSession, user: CurrentUser
):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    repo = EngagementRepository(db)
    engagement = await repo.get_with_items(engagement_id, tenant_id)
    if not engagement:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    previous_status = engagement.status
    new_status = payload.status
    if new_status not in _LEGAL_TRANSITIONS.get(previous_status, set()):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot transition from '{previous_status.value}' to '{new_status.value}'",
        )

    engagement.status = new_status
    await repo.commit()
    # Same live-update signal orders.py broadcasts on a status change (order_status_
    # changed) -- generic_flow_engine.py's _create_engagement already broadcasts
    # "engagement_created" for the initial write; this is that event's status-change
    # counterpart, so the Orders/Bookings/Leads page can update live like the legacy one.
    await ws_manager.broadcast(
        tenant_id, {"type": "engagement_status_changed", "engagement_id": str(engagement.id), "status": engagement.status.value}
    )

    restaurant = await RestaurantRepository(db).get(tenant_id)
    customer = await CustomerRepository(db).get(engagement.customer_id, tenant_id)
    if restaurant and customer:
        # Niche-appropriate status wording where the business has customized it (see
        # NicheTemplate.terminology.status_labels), same source Bot Preview/the real
        # engine's own notify_business() reads from -- falls back to a plain
        # Title-Cased status name for a business with no niche_type/customization.
        status_label = new_status.value.replace("_", " ").title()
        if restaurant.niche_type:
            template = await NicheTemplateRepository(db).get_by_code(restaurant.niche_type)
            if template and isinstance(template.terminology, dict):
                status_label = template.terminology.get("status_labels", {}).get(new_status.value, status_label)
        type_noun = _TYPE_NOUN.get(engagement.type, "request")
        message = f"Update on your {type_noun} (Ref: {engagement.reference_number}): {status_label}."
        try:
            await send_generic_message(
                db, _sender, restaurant, engagement.customer_id, customer.phone, OutboundMessage.text(customer.phone, message)
            )
            await db.commit()
        except Exception:
            # Same reasoning as orders.py's identical guard -- a WhatsApp send failure
            # must never fail the status-update request itself; the status change
            # already committed above.
            logger.warning(
                "Failed to send WhatsApp status-update message for engagement %s (reference_number=%s, status=%s)",
                engagement.id, engagement.reference_number, engagement.status.value, exc_info=True,
            )

    return _to_read(engagement)
