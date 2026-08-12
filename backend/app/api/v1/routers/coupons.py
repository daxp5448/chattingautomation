import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError

from app.core.deps import CurrentUser, DbSession, require_feature, require_roles, resolve_tenant_id
from app.models.coupon import Coupon
from app.models.enums import UserRole
from app.models.user import User
from app.repositories.coupon_repository import CouponRepository
from app.schemas.coupon import CouponCreate, CouponRead, CouponUpdate

router = APIRouter(prefix="/restaurants/{restaurant_id}/coupons", tags=["coupons"])

# Creating/editing/deleting coupons is restaurant-configuration territory -- cashier/
# kitchen accounts can read active coupons (e.g. to honor one at the counter) but not
# create or change them.
_MANAGE_COUPONS = require_roles(UserRole.OWNER, UserRole.MANAGER)


@router.post("", response_model=CouponRead, status_code=status.HTTP_201_CREATED)
async def create_coupon(
    restaurant_id: uuid.UUID,
    payload: CouponCreate,
    db: DbSession,
    user: User = Depends(_MANAGE_COUPONS),
    _feature: None = Depends(require_feature("coupons")),
):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    repo = CouponRepository(db)
    data = payload.model_dump()
    data["code"] = data["code"].strip().upper()
    if await repo.get_by_code(tenant_id, data["code"]):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Coupon code already exists")
    coupon = Coupon(restaurant_id=tenant_id, **data)
    coupon = await repo.create(coupon)
    await repo.commit()
    return coupon


@router.get("", response_model=list[CouponRead])
async def list_coupons(restaurant_id: uuid.UUID, db: DbSession, user: CurrentUser):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    repo = CouponRepository(db)
    return await repo.list(restaurant_id=tenant_id)


@router.patch("/{coupon_id}", response_model=CouponRead)
async def update_coupon(
    restaurant_id: uuid.UUID,
    coupon_id: uuid.UUID,
    payload: CouponUpdate,
    db: DbSession,
    user: User = Depends(_MANAGE_COUPONS),
    _feature: None = Depends(require_feature("coupons")),
):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    repo = CouponRepository(db)
    coupon = await repo.get(coupon_id, tenant_id)
    if not coupon:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Coupon not found")
    updates = payload.model_dump(exclude_unset=True)
    if "code" in updates and updates["code"]:
        updates["code"] = updates["code"].strip().upper()
    for field, value in updates.items():
        setattr(coupon, field, value)
    await repo.commit()
    return coupon


@router.delete("/{coupon_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_coupon(
    restaurant_id: uuid.UUID, coupon_id: uuid.UUID, db: DbSession, user: User = Depends(_MANAGE_COUPONS)
):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    repo = CouponRepository(db)
    coupon = await repo.get(coupon_id, tenant_id)
    if not coupon:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Coupon not found")
    try:
        await repo.delete(coupon)
        await repo.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Can't delete this coupon: it has existing orders or other data referencing it",
        )
