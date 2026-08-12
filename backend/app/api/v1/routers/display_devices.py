"""POS/kitchen display devices: staff-authenticated management endpoints plus a
public, token-authenticated read-only orders feed for unattended screens (a tablet at
the counter or in the kitchen) that must never require a staff login.
"""

import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.deps import CurrentUser, DbSession, require_roles, resolve_tenant_id
from app.core.display_tokens import generate_display_token, hash_display_token
from app.db.base import utcnow
from app.models.display_device import DisplayDevice
from app.models.enums import UserRole
from app.models.order import Order
from app.models.user import User
from app.repositories.display_device_repository import DisplayDeviceRepository
from app.schemas.display_device import (
    DisplayDeviceCreate,
    DisplayDeviceCreateResponse,
    DisplayDeviceRead,
    PosOrderRead,
)

router = APIRouter(prefix="/restaurants/{restaurant_id}/display-devices", tags=["display-devices"])
pos_router = APIRouter(prefix="/pos/{restaurant_id}", tags=["pos"])

# Minting/revoking a POS/kitchen display device token is restaurant-configuration
# territory -- a kitchen/cashier account shouldn't be able to mint new device tokens for
# the restaurant, only owner/manager can.
_MANAGE_DISPLAY_DEVICES = require_roles(UserRole.OWNER, UserRole.MANAGER)


@router.post("", response_model=DisplayDeviceCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_display_device(
    restaurant_id: uuid.UUID,
    payload: DisplayDeviceCreate,
    db: DbSession,
    user: User = Depends(_MANAGE_DISPLAY_DEVICES),
):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    raw_token, token_hash = generate_display_token()
    device = DisplayDevice(
        restaurant_id=tenant_id,
        branch_id=payload.branch_id,
        name=payload.name,
        token_hash=token_hash,
    )
    repo = DisplayDeviceRepository(db)
    device = await repo.create(device)
    await repo.commit()
    # The raw token is returned here and only here -- it is never derivable from
    # token_hash again, so this response is the device's one-time secret reveal.
    return DisplayDeviceCreateResponse(id=device.id, name=device.name, token=raw_token)


@router.get("", response_model=list[DisplayDeviceRead])
async def list_display_devices(restaurant_id: uuid.UUID, db: DbSession, user: CurrentUser):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    repo = DisplayDeviceRepository(db)
    return await repo.list(restaurant_id=tenant_id)


@router.delete("/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_display_device(
    restaurant_id: uuid.UUID, device_id: uuid.UUID, db: DbSession, user: User = Depends(_MANAGE_DISPLAY_DEVICES)
):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    repo = DisplayDeviceRepository(db)
    device = await repo.get(device_id, tenant_id)
    if not device:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Display device not found")
    if device.revoked_at is None:
        device.revoked_at = utcnow()
        await repo.commit()


# --- Public, token-authenticated read-only orders feed ---------------------------------

_RATE_LIMIT_MAX_REQUESTS = 60
_RATE_LIMIT_WINDOW_SECONDS = 60.0
# Tiny in-memory sliding window, keyed by token hash rather than IP -- a shared
# restaurant Wi-Fi/NAT could otherwise put multiple legitimate screens behind one IP.
# Single-process only, matching ws_manager's ConnectionManager in this same codebase;
# fine at this scale, a multi-process deployment would move this to Redis.
_pos_request_log: dict[str, deque[float]] = defaultdict(deque)


def _check_rate_limit(token_hash: str) -> None:
    now = time.monotonic()
    window_start = now - _RATE_LIMIT_WINDOW_SECONDS
    log = _pos_request_log[token_hash]
    while log and log[0] < window_start:
        log.popleft()
    if len(log) >= _RATE_LIMIT_MAX_REQUESTS:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many requests")
    log.append(now)


async def resolve_display_device(db: DbSession, restaurant_id: uuid.UUID, token: str) -> DisplayDevice:
    """Shared auth-resolution helper for the token query param: hash it, look up an
    active device scoped to this restaurant, 401 on any mismatch. Used by both the
    REST POS endpoint and (indirectly, via the same lookup shape) the WS device-token
    path, and directly unit-tested since a real device/browser isn't exercised here."""
    token_hash = hash_display_token(token)
    _check_rate_limit(token_hash)
    repo = DisplayDeviceRepository(db)
    device = await repo.get_active_by_token_hash(token_hash, restaurant_id)
    if not device:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or revoked display link")
    return device


@pos_router.get("/orders", response_model=list[PosOrderRead])
async def pos_list_orders(
    restaurant_id: uuid.UUID, db: DbSession, token: str = Query(...)
):
    device = await resolve_display_device(db, restaurant_id, token)

    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    stmt = (
        select(Order)
        .options(selectinload(Order.items))
        .where(Order.restaurant_id == restaurant_id, Order.created_at >= today_start)
        .order_by(Order.created_at.desc())
    )
    if device.branch_id is not None:
        stmt = stmt.where(Order.branch_id == device.branch_id)
    result = await db.execute(stmt)
    return list(result.scalars().all())
