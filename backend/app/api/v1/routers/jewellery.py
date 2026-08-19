import uuid

from fastapi import APIRouter, Query

from app.core.deps import CurrentUser, DbSession, resolve_tenant_id
from app.repositories.jewellery_design_repository import JewelleryDesignRepository
from app.schemas.jewellery import JewelleryDesignPage, JewelleryDesignRead

router = APIRouter(prefix="/restaurants/{restaurant_id}/jewellery", tags=["jewellery"])


@router.get("/materials", response_model=list[str])
async def list_jewellery_materials(restaurant_id: uuid.UUID, db: DbSession, user: CurrentUser):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    repo = JewelleryDesignRepository(db)
    return await repo.list_materials(tenant_id)


@router.get("/categories", response_model=list[str])
async def list_jewellery_categories(restaurant_id: uuid.UUID, material: str, db: DbSession, user: CurrentUser):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    repo = JewelleryDesignRepository(db)
    return await repo.list_categories(tenant_id, material)


@router.get("/designs", response_model=JewelleryDesignPage)
async def list_jewellery_designs(
    restaurant_id: uuid.UUID,
    material: str,
    category: str,
    db: DbSession,
    user: CurrentUser,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    repo = JewelleryDesignRepository(db)
    designs = await repo.list_designs(tenant_id, material, category, offset, limit)
    total = await repo.count_designs(tenant_id, material, category)
    return JewelleryDesignPage(
        total=total,
        offset=offset,
        limit=limit,
        items=[JewelleryDesignRead.model_validate(d) for d in designs],
    )
