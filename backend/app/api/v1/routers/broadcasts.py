import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.deps import CurrentUser, DbSession, require_feature, require_roles, resolve_tenant_id
from app.models.broadcast import BroadcastCampaign, BroadcastRecipient
from app.models.enums import BroadcastRecipientStatus, BroadcastStatus, TemplateCategory, TemplateStatus, UserRole
from app.models.user import User
from app.repositories.broadcast_repository import BroadcastCampaignRepository, BroadcastRecipientRepository
from app.repositories.customer_repository import CustomerRepository
from app.repositories.restaurant_repository import RestaurantRepository
from app.repositories.whatsapp_template_repository import WhatsAppTemplateRepository
from app.schemas.broadcast import (
    BroadcastCampaignCreate,
    BroadcastCampaignRead,
    BroadcastCampaignUpdate,
    BroadcastRecipientRead,
    SegmentPreview,
)
from app.services import broadcast_service

router = APIRouter(prefix="/restaurants/{restaurant_id}/broadcasts", tags=["broadcasts"])

# Managing campaigns is restaurant-configuration/marketing territory, same gating as
# coupons/whatsapp-templates.
_MANAGE_BROADCASTS = require_roles(UserRole.OWNER, UserRole.MANAGER)

_EDITABLE_STATUSES = {BroadcastStatus.DRAFT}
_STARTABLE_STATUSES = {BroadcastStatus.DRAFT}
_CANCELLABLE_STATUSES = {BroadcastStatus.SCHEDULED, BroadcastStatus.SENDING}


async def _get_campaign_or_404(repo: BroadcastCampaignRepository, campaign_id: uuid.UUID, tenant_id: uuid.UUID) -> BroadcastCampaign:
    campaign = await repo.get(campaign_id, tenant_id)
    if not campaign:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")
    return campaign


@router.get("", response_model=list[BroadcastCampaignRead])
async def list_campaigns(restaurant_id: uuid.UUID, db: DbSession, user: CurrentUser):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    repo = BroadcastCampaignRepository(db)
    return await repo.list(restaurant_id=tenant_id)


@router.get("/{campaign_id}", response_model=BroadcastCampaignRead)
async def get_campaign(restaurant_id: uuid.UUID, campaign_id: uuid.UUID, db: DbSession, user: CurrentUser):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    repo = BroadcastCampaignRepository(db)
    return await _get_campaign_or_404(repo, campaign_id, tenant_id)


@router.get("/{campaign_id}/recipients", response_model=list[BroadcastRecipientRead])
async def list_recipients(
    restaurant_id: uuid.UUID, campaign_id: uuid.UUID, db: DbSession, user: CurrentUser,
    limit: int = Query(default=200, ge=1, le=1000), offset: int = Query(default=0, ge=0),
):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    campaign_repo = BroadcastCampaignRepository(db)
    await _get_campaign_or_404(campaign_repo, campaign_id, tenant_id)
    recipients = await BroadcastRecipientRepository(db).list_for_campaign(campaign_id)
    return recipients[offset:offset + limit]


@router.get("/{campaign_id}/segment-preview", response_model=SegmentPreview)
async def preview_segment(restaurant_id: uuid.UUID, campaign_id: uuid.UUID, db: DbSession, user: CurrentUser):
    """Live count of currently-matching customers -- NOT the frozen recipient snapshot
    (that only exists once the campaign has actually started, see `start` below)."""
    tenant_id = resolve_tenant_id(user, restaurant_id)
    campaign_repo = BroadcastCampaignRepository(db)
    campaign = await _get_campaign_or_404(campaign_repo, campaign_id, tenant_id)
    matching = await CustomerRepository(db).list_by_tags(tenant_id, campaign.segment_tags)
    return SegmentPreview(matching_customers=len(matching))


@router.post("", response_model=BroadcastCampaignRead, status_code=status.HTTP_201_CREATED)
async def create_campaign(
    restaurant_id: uuid.UUID,
    payload: BroadcastCampaignCreate,
    db: DbSession,
    user: User = Depends(_MANAGE_BROADCASTS),
    _feature: None = Depends(require_feature("broadcasts")),
):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    template = await WhatsAppTemplateRepository(db).get(payload.template_id, tenant_id)
    if not template:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown template_id for this business")

    repo = BroadcastCampaignRepository(db)
    campaign = BroadcastCampaign(restaurant_id=tenant_id, status=BroadcastStatus.DRAFT, **payload.model_dump())
    campaign = await repo.create(campaign)
    await repo.commit()
    return campaign


@router.patch("/{campaign_id}", response_model=BroadcastCampaignRead)
async def update_campaign(
    restaurant_id: uuid.UUID,
    campaign_id: uuid.UUID,
    payload: BroadcastCampaignUpdate,
    db: DbSession,
    user: User = Depends(_MANAGE_BROADCASTS),
    _feature: None = Depends(require_feature("broadcasts")),
):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    repo = BroadcastCampaignRepository(db)
    campaign = await _get_campaign_or_404(repo, campaign_id, tenant_id)
    if campaign.status not in _EDITABLE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Campaign status is '{campaign.status.value}' -- only a draft campaign can be edited",
        )
    updates = payload.model_dump(exclude_unset=True)
    if "template_id" in updates:
        template = await WhatsAppTemplateRepository(db).get(updates["template_id"], tenant_id)
        if not template:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown template_id for this business")
    for field, value in updates.items():
        setattr(campaign, field, value)
    await repo.commit()
    return campaign


@router.post("/{campaign_id}/start", response_model=BroadcastCampaignRead)
async def start_campaign(
    restaurant_id: uuid.UUID,
    campaign_id: uuid.UUID,
    db: DbSession,
    user: User = Depends(_MANAGE_BROADCASTS),
    _feature: None = Depends(require_feature("broadcasts")),
):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    campaign_repo = BroadcastCampaignRepository(db)
    campaign = await _get_campaign_or_404(campaign_repo, campaign_id, tenant_id)
    if campaign.status not in _STARTABLE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Campaign status is '{campaign.status.value}' -- only a draft campaign can be started",
        )

    template = await WhatsAppTemplateRepository(db).get(campaign.template_id, tenant_id)
    if not template or template.status != TemplateStatus.APPROVED:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Template is not approved -- cannot start")

    try:
        broadcast_service.validate_variable_count(template, campaign.variable_template)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    restaurant = await RestaurantRepository(db).get(tenant_id)
    if not restaurant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Business not found")

    matching = await CustomerRepository(db).list_by_tags(tenant_id, campaign.segment_tags)
    if template.category == TemplateCategory.MARKETING:
        matching = [c for c in matching if c.marketing_opt_in]

    if len(matching) > restaurant.broadcast_daily_cap:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"{len(matching)} matching customers exceeds this business's broadcast_daily_cap "
                f"({restaurant.broadcast_daily_cap}) -- narrow the segment, or raise the cap in business "
                "settings once your real Meta messaging tier is confirmed"
            ),
        )
    if not matching:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No customers match this segment -- nothing to send")

    for customer in matching:
        db.add(BroadcastRecipient(campaign_id=campaign.id, customer_id=customer.id, status=BroadcastRecipientStatus.PENDING))
    campaign.total_recipients = len(matching)

    now = datetime.now(timezone.utc)
    if campaign.scheduled_at is not None and campaign.scheduled_at > now:
        # Left SCHEDULED for the beat-task dispatcher (app/tasks/broadcast_dispatch.py) to
        # pick up once due -- deliberately NOT Celery's apply_async(eta=...), which risks
        # duplicate delivery on this project's Redis broker (default visibility_timeout
        # exceeded for anything scheduled more than ~1h out).
        campaign.status = BroadcastStatus.SCHEDULED
        await campaign_repo.commit()
        return campaign

    campaign.status = BroadcastStatus.SENDING
    campaign.started_at = now
    await campaign_repo.commit()

    await broadcast_service.enqueue_broadcast_send(campaign.id)
    return campaign


@router.post("/{campaign_id}/cancel", response_model=BroadcastCampaignRead)
async def cancel_campaign(
    restaurant_id: uuid.UUID, campaign_id: uuid.UUID, db: DbSession, user: User = Depends(_MANAGE_BROADCASTS)
):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    repo = BroadcastCampaignRepository(db)
    campaign = await _get_campaign_or_404(repo, campaign_id, tenant_id)
    if campaign.status not in _CANCELLABLE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Campaign status is '{campaign.status.value}' -- only a scheduled or sending campaign can be cancelled",
        )
    campaign.status = BroadcastStatus.CANCELLED
    campaign.completed_at = datetime.now(timezone.utc)
    await repo.commit()
    return campaign


@router.delete("/{campaign_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_campaign(
    restaurant_id: uuid.UUID, campaign_id: uuid.UUID, db: DbSession, user: User = Depends(_MANAGE_BROADCASTS)
):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    repo = BroadcastCampaignRepository(db)
    campaign = await _get_campaign_or_404(repo, campaign_id, tenant_id)
    if campaign.status != BroadcastStatus.DRAFT:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only a draft campaign can be deleted")
    await repo.delete(campaign)
    await repo.commit()
