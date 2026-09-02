import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError

from app.core.deps import CurrentUser, DbSession, require_feature, require_roles, resolve_tenant_id
from app.core.security import decrypt_secret
from app.db.base import utcnow
from app.models.enums import TemplateStatus, UserRole
from app.models.user import User
from app.models.whatsapp_template import WhatsAppTemplate
from app.repositories.restaurant_repository import RestaurantRepository
from app.repositories.whatsapp_template_repository import WhatsAppTemplateRepository
from app.schemas.whatsapp_template import (
    WhatsAppTemplateCreate,
    WhatsAppTemplateRead,
    WhatsAppTemplateTestSend,
    WhatsAppTemplateUpdate,
)
from app.services import whatsapp_template_client
from app.services.template_purpose_mapping import recommend_templates
from app.services.whatsapp_client import GraphAPIWhatsAppSender, OutboundMessage

router = APIRouter(prefix="/restaurants/{restaurant_id}/whatsapp-templates", tags=["whatsapp-templates"])

# Managing templates is restaurant-configuration territory, same gating as coupons.
_MANAGE_TEMPLATES = require_roles(UserRole.OWNER, UserRole.MANAGER)

# Swap for InMemoryWhatsAppSender in tests, same module-level-singleton pattern as
# app/api/v1/routers/payments.py's _sender.
_sender = GraphAPIWhatsAppSender()

# Editable only in these two states -- see app/models/whatsapp_template.py's docstring.
_EDITABLE_STATUSES = {TemplateStatus.DRAFT, TemplateStatus.REJECTED}


async def _get_restaurant_or_404(db, tenant_id: uuid.UUID):
    restaurant = await RestaurantRepository(db).get(tenant_id)
    if not restaurant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Business not found")
    return restaurant


async def _get_template_or_404(repo: WhatsAppTemplateRepository, template_id: uuid.UUID, tenant_id: uuid.UUID) -> WhatsAppTemplate:
    template = await repo.get(template_id, tenant_id)
    if not template:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
    return template


@router.get("", response_model=list[WhatsAppTemplateRead])
async def list_templates(restaurant_id: uuid.UUID, db: DbSession, user: CurrentUser):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    repo = WhatsAppTemplateRepository(db)
    return await repo.list(restaurant_id=tenant_id)


@router.get("/recommendations", response_model=dict[str, WhatsAppTemplateRead | None])
async def get_template_recommendations(restaurant_id: uuid.UUID, db: DbSession, user: CurrentUser):
    """Niche-aware template recommendation for Broadcast Campaigns -- the one place
    templates are actually usable (see template_purpose_mapping.py's module docstring
    for why this never touches the live conversation). Declared BEFORE /{template_id}
    so "recommendations" is never matched as a template_id path param. Read-only, same
    permission bar as list/get above -- this never mutates anything.
    """
    tenant_id = resolve_tenant_id(user, restaurant_id)
    restaurant = await _get_restaurant_or_404(db, tenant_id)
    templates = await WhatsAppTemplateRepository(db).list(restaurant_id=tenant_id)
    recommended = recommend_templates(templates, restaurant.niche_type)
    return {purpose.value: template for purpose, template in recommended.items()}


@router.get("/{template_id}", response_model=WhatsAppTemplateRead)
async def get_template(restaurant_id: uuid.UUID, template_id: uuid.UUID, db: DbSession, user: CurrentUser):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    repo = WhatsAppTemplateRepository(db)
    return await _get_template_or_404(repo, template_id, tenant_id)


@router.post("", response_model=WhatsAppTemplateRead, status_code=status.HTTP_201_CREATED)
async def create_template(
    restaurant_id: uuid.UUID,
    payload: WhatsAppTemplateCreate,
    db: DbSession,
    user: User = Depends(_MANAGE_TEMPLATES),
    _feature: None = Depends(require_feature("whatsapp_template_manager")),
):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    repo = WhatsAppTemplateRepository(db)
    if await repo.get_by_name(tenant_id, payload.name):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A template with this name already exists")
    template = WhatsAppTemplate(restaurant_id=tenant_id, status=TemplateStatus.DRAFT, **payload.model_dump())
    template = await repo.create(template)
    await repo.commit()
    return template


@router.patch("/{template_id}", response_model=WhatsAppTemplateRead)
async def update_template(
    restaurant_id: uuid.UUID,
    template_id: uuid.UUID,
    payload: WhatsAppTemplateUpdate,
    db: DbSession,
    user: User = Depends(_MANAGE_TEMPLATES),
    _feature: None = Depends(require_feature("whatsapp_template_manager")),
):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    repo = WhatsAppTemplateRepository(db)
    template = await _get_template_or_404(repo, template_id, tenant_id)
    if template.status not in _EDITABLE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Template status is '{template.status.value}' -- only a draft or rejected template can be edited",
        )
    updates = payload.model_dump(exclude_unset=True)
    if "name" in updates and updates["name"] != template.name:
        if await repo.get_by_name(tenant_id, updates["name"]):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A template with this name already exists")
    for field, value in updates.items():
        setattr(template, field, value)
    await repo.commit()
    return template


@router.post("/{template_id}/submit", response_model=WhatsAppTemplateRead)
async def submit_template(
    restaurant_id: uuid.UUID,
    template_id: uuid.UUID,
    db: DbSession,
    user: User = Depends(_MANAGE_TEMPLATES),
    _feature: None = Depends(require_feature("whatsapp_template_manager")),
):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    repo = WhatsAppTemplateRepository(db)
    template = await _get_template_or_404(repo, template_id, tenant_id)
    if template.status not in _EDITABLE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Template status is '{template.status.value}' -- only a draft or rejected template can be submitted",
        )
    restaurant = await _get_restaurant_or_404(db, tenant_id)

    try:
        result = await whatsapp_template_client.create_template(restaurant, template)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Template submission failed: {exc}") from exc

    # Only mutate local state now that the gateway call above actually succeeded.
    template.meta_template_id = str(result.get("id") or "")
    template.status = TemplateStatus.PENDING
    template.rejection_reason = None
    template.submitted_at = utcnow()
    await repo.commit()
    return template


@router.post("/{template_id}/test-send", status_code=status.HTTP_204_NO_CONTENT)
async def test_send_template(
    restaurant_id: uuid.UUID,
    template_id: uuid.UUID,
    payload: WhatsAppTemplateTestSend,
    db: DbSession,
    user: User = Depends(_MANAGE_TEMPLATES),
    _feature: None = Depends(require_feature("whatsapp_template_manager")),
):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    repo = WhatsAppTemplateRepository(db)
    template = await _get_template_or_404(repo, template_id, tenant_id)
    if template.status != TemplateStatus.APPROVED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Template status is '{template.status.value}' -- only an approved template can be test-sent",
        )
    restaurant = await _get_restaurant_or_404(db, tenant_id)

    try:
        await _sender.send(
            restaurant.whatsapp_phone_number_id or "",
            decrypt_secret(restaurant.whatsapp_access_token_encrypted or ""),
            OutboundMessage.template(payload.to_phone, template.name, template.language, payload.variable_values),
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Test send failed: {exc}") from exc


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(
    restaurant_id: uuid.UUID, template_id: uuid.UUID, db: DbSession, user: User = Depends(_MANAGE_TEMPLATES)
):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    repo = WhatsAppTemplateRepository(db)
    template = await _get_template_or_404(repo, template_id, tenant_id)

    if template.meta_template_id:
        restaurant = await _get_restaurant_or_404(db, tenant_id)
        try:
            await whatsapp_template_client.delete_template(restaurant, template.name)
        except httpx.HTTPStatusError as exc:
            # A 404 from Meta means it's already gone there -- safe to delete locally too.
            if exc.response.status_code != status.HTTP_404_NOT_FOUND:
                raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Failed to delete on Meta's side: {exc}") from exc
        except Exception as exc:
            # Deliberately NOT deleting the local row here -- see app/services/
            # whatsapp_template_client.py::delete_template's docstring: deleting local
            # first would risk orphaning the name on Meta's side with nothing left to
            # retry or even notice the orphan.
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Failed to delete on Meta's side: {exc}") from exc

    try:
        await repo.delete(template)
        await repo.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Can't delete this template: other data references it")
