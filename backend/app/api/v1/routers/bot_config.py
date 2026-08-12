import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError

from app.core.deps import CurrentUser, DbSession, require_roles, resolve_tenant_id
from app.models.bot_config import BotButton
from app.models.enums import UserRole
from app.models.user import User
from app.repositories.bot_config_repository import BotButtonRepository, BotMessageRepository
from app.schemas.bot_config import (
    BotButtonCreate,
    BotButtonRead,
    BotButtonUpdate,
    BotMessageRead,
    BotMessageUpsert,
)

router = APIRouter(prefix="/restaurants/{restaurant_id}/bot", tags=["bot-builder"])

# Editing bot messages/buttons is restaurant-configuration territory -- cashier/kitchen
# accounts can read the bot's current config but not change what it says or does.
_MANAGE_BOT_CONFIG = require_roles(UserRole.OWNER, UserRole.MANAGER)


@router.get("/messages", response_model=list[BotMessageRead])
async def list_messages(restaurant_id: uuid.UUID, db: DbSession, user: CurrentUser):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    repo = BotMessageRepository(db)
    return await repo.list(restaurant_id=tenant_id)


@router.put("/messages", response_model=BotMessageRead)
async def upsert_message(
    restaurant_id: uuid.UUID, payload: BotMessageUpsert, db: DbSession, user: User = Depends(_MANAGE_BOT_CONFIG)
):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    repo = BotMessageRepository(db)
    message = await repo.upsert(tenant_id, payload.key, payload.content)
    await repo.commit()
    return message


@router.get("/buttons", response_model=list[BotButtonRead])
async def list_buttons(restaurant_id: uuid.UUID, db: DbSession, user: CurrentUser):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    repo = BotButtonRepository(db)
    buttons = await repo.list(restaurant_id=tenant_id)
    return sorted(buttons, key=lambda b: b.display_order)


@router.post("/buttons", response_model=BotButtonRead, status_code=status.HTTP_201_CREATED)
async def create_button(
    restaurant_id: uuid.UUID, payload: BotButtonCreate, db: DbSession, user: User = Depends(_MANAGE_BOT_CONFIG)
):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    repo = BotButtonRepository(db)
    button = BotButton(restaurant_id=tenant_id, **payload.model_dump())
    button = await repo.create(button)
    await repo.commit()
    return button


@router.patch("/buttons/{button_id}", response_model=BotButtonRead)
async def update_button(
    restaurant_id: uuid.UUID,
    button_id: uuid.UUID,
    payload: BotButtonUpdate,
    db: DbSession,
    user: User = Depends(_MANAGE_BOT_CONFIG),
):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    repo = BotButtonRepository(db)
    button = await repo.get(button_id, tenant_id)
    if not button:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Button not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(button, field, value)
    await repo.commit()
    return button


@router.delete("/buttons/{button_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_button(
    restaurant_id: uuid.UUID, button_id: uuid.UUID, db: DbSession, user: User = Depends(_MANAGE_BOT_CONFIG)
):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    repo = BotButtonRepository(db)
    button = await repo.get(button_id, tenant_id)
    if not button:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Button not found")
    try:
        await repo.delete(button)
        await repo.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Can't delete this button: it has existing data referencing it",
        )
