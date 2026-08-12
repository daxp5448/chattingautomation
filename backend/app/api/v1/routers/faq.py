import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError

from app.core.deps import CurrentUser, DbSession, require_feature, require_roles, resolve_tenant_id
from app.models.enums import UserRole
from app.models.faq import FaqEntry
from app.models.user import User
from app.repositories.faq_repository import FaqRepository
from app.schemas.faq import FaqEntryCreate, FaqEntryRead, FaqEntryUpdate

router = APIRouter(prefix="/restaurants/{restaurant_id}/faq", tags=["faq"])

# Editing FAQ content is restaurant-configuration territory -- cashier/kitchen accounts
# can read it (e.g. to answer a handed-over conversation) but not edit it.
_MANAGE_FAQ = require_roles(UserRole.OWNER, UserRole.MANAGER)


@router.post("", response_model=FaqEntryRead, status_code=status.HTTP_201_CREATED)
async def create_faq_entry(
    restaurant_id: uuid.UUID,
    payload: FaqEntryCreate,
    db: DbSession,
    user: User = Depends(_MANAGE_FAQ),
    _feature: None = Depends(require_feature("faq_autoresponder")),
):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    repo = FaqRepository(db)
    entry = FaqEntry(restaurant_id=tenant_id, **payload.model_dump())
    entry = await repo.create(entry)
    await repo.commit()
    return entry


@router.get("", response_model=list[FaqEntryRead])
async def list_faq_entries(restaurant_id: uuid.UUID, db: DbSession, user: CurrentUser):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    repo = FaqRepository(db)
    entries = await repo.list(restaurant_id=tenant_id)
    return sorted(entries, key=lambda e: e.display_order)


@router.patch("/{faq_id}", response_model=FaqEntryRead)
async def update_faq_entry(
    restaurant_id: uuid.UUID,
    faq_id: uuid.UUID,
    payload: FaqEntryUpdate,
    db: DbSession,
    user: User = Depends(_MANAGE_FAQ),
    _feature: None = Depends(require_feature("faq_autoresponder")),
):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    repo = FaqRepository(db)
    entry = await repo.get(faq_id, tenant_id)
    if not entry:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="FAQ entry not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(entry, field, value)
    await repo.commit()
    return entry


@router.delete("/{faq_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_faq_entry(
    restaurant_id: uuid.UUID, faq_id: uuid.UUID, db: DbSession, user: User = Depends(_MANAGE_FAQ)
):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    repo = FaqRepository(db)
    entry = await repo.get(faq_id, tenant_id)
    if not entry:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="FAQ entry not found")
    try:
        await repo.delete(entry)
        await repo.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Can't delete this FAQ entry: it has existing data referencing it",
        )
