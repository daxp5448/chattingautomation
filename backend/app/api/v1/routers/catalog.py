"""CRUD for a generic-engine business's own live catalog (CatalogCategory/CatalogItem) --
the counterpart of menu.py for niche-provisioned businesses. Until this router existed,
there was no way for an Owner/Manager (or Super Admin testing a Demo Bot restaurant) to
ever view or edit their catalog after niche_provisioning.py's one-time copy from the
template at signup -- menu.py's /categories and /products endpoints operate on a
completely different set of tables (the legacy Category/Product models, for
Custom/Legacy-niche businesses only) and return nothing for a niche-provisioned business.
See generic_flow_engine.py for the customer-facing read side of these same tables.
"""

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.deps import CurrentUser, DbSession, require_roles, resolve_tenant_id
from app.models.catalog import CatalogCategory, CatalogItem
from app.models.enums import UserRole
from app.models.user import User
from app.repositories.catalog_repository import CatalogCategoryRepository, CatalogItemRepository
from app.schemas.catalog import (
    CatalogCategoryCreate,
    CatalogCategoryRead,
    CatalogCategoryUpdate,
    CatalogItemCreate,
    CatalogItemRead,
    CatalogItemUpdate,
)
from app.services import image_storage_service
from app.services.image_storage_service import ImageStorageError

router = APIRouter(prefix="/restaurants/{restaurant_id}", tags=["catalog"])

# Same bar as menu.py's _MANAGE_MENU: restaurant-configuration territory, not
# order-fulfillment territory.
_MANAGE_CATALOG = require_roles(UserRole.OWNER, UserRole.MANAGER)

# CatalogCategory.image_url is a plain string, not a real CatalogItem row -- the
# Universal Image Processing Pipeline (images.py) requires a catalog_item_id
# (CheckConstraint("catalog_item_id IS NOT NULL"), see app/models/image.py), so category
# icons need the same simple "upload -> permanent URL" pattern niche_templates.py already
# uses for template images, just restaurant-scoped and Owner/Manager-gated instead of
# Super-Admin-only.
_ALLOWED_CONTENT_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
_MAX_UPLOAD_BYTES = 8 * 1024 * 1024


@router.post("/catalog-categories/upload-image")
async def upload_catalog_category_image(
    restaurant_id: uuid.UUID, file: UploadFile = File(...), user: User = Depends(_MANAGE_CATALOG)
) -> dict[str, str]:
    tenant_id = resolve_tenant_id(user, restaurant_id)
    ext = _ALLOWED_CONTENT_TYPES.get(file.content_type or "")
    if ext is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only JPEG, PNG, or WebP images are allowed")
    content = await file.read()
    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Image exceeds the {_MAX_UPLOAD_BYTES // (1024 * 1024)}MB limit")

    key = f"catalog/{tenant_id}/{uuid.uuid4()}{ext}"
    try:
        image_storage_service.upload_bytes(key, content, file.content_type)
    except ImageStorageError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to upload image") from exc

    return {"url": f"{settings.PUBLIC_MEDIA_BASE_URL}/{key}"}


# --- Categories ---------------------------------------------------------------------


@router.post("/catalog-categories", response_model=CatalogCategoryRead, status_code=status.HTTP_201_CREATED)
async def create_catalog_category(
    restaurant_id: uuid.UUID, payload: CatalogCategoryCreate, db: DbSession, user: User = Depends(_MANAGE_CATALOG)
):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    repo = CatalogCategoryRepository(db)
    category = CatalogCategory(restaurant_id=tenant_id, **payload.model_dump())
    category = await repo.create(category)
    await repo.commit()
    return category


@router.get("/catalog-categories", response_model=list[CatalogCategoryRead])
async def list_catalog_categories(restaurant_id: uuid.UUID, db: DbSession, user: CurrentUser):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    repo = CatalogCategoryRepository(db)
    # Deliberately repo.list(), not list_visible() -- an admin editing the catalog must
    # see hidden categories too, unlike the customer-facing flow engine's read site.
    categories = await repo.list(restaurant_id=tenant_id)
    return sorted(categories, key=lambda c: c.display_order)


@router.patch("/catalog-categories/{category_id}", response_model=CatalogCategoryRead)
async def update_catalog_category(
    restaurant_id: uuid.UUID,
    category_id: uuid.UUID,
    payload: CatalogCategoryUpdate,
    db: DbSession,
    user: User = Depends(_MANAGE_CATALOG),
):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    repo = CatalogCategoryRepository(db)
    category = await repo.get(category_id, tenant_id)
    if not category:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(category, field, value)
    await repo.commit()
    return category


@router.delete("/catalog-categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_catalog_category(
    restaurant_id: uuid.UUID, category_id: uuid.UUID, db: DbSession, user: User = Depends(_MANAGE_CATALOG)
):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    repo = CatalogCategoryRepository(db)
    category = await repo.get(category_id, tenant_id)
    if not category:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")
    try:
        await repo.delete(category)
        await repo.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Can't delete this category: it still has items or other data referencing it",
        )


# --- Items ----------------------------------------------------------------------------


@router.post("/catalog-items", response_model=CatalogItemRead, status_code=status.HTTP_201_CREATED)
async def create_catalog_item(
    restaurant_id: uuid.UUID, payload: CatalogItemCreate, db: DbSession, user: User = Depends(_MANAGE_CATALOG)
):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    repo = CatalogItemRepository(db)
    item = CatalogItem(restaurant_id=tenant_id, **payload.model_dump())
    item = await repo.create(item)
    await repo.commit()
    return item


@router.get("/catalog-items", response_model=list[CatalogItemRead])
async def list_catalog_items(restaurant_id: uuid.UUID, db: DbSession, user: CurrentUser):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    repo = CatalogItemRepository(db)
    # Deliberately repo.list(), not list_by_category() -- this lists every item across
    # every category in one call (the admin catalog page groups them client-side), and
    # includes unavailable items too, unlike the customer-facing flow engine's read site.
    items = await repo.list(restaurant_id=tenant_id)
    return sorted(items, key=lambda i: i.display_order)


@router.patch("/catalog-items/{item_id}", response_model=CatalogItemRead)
async def update_catalog_item(
    restaurant_id: uuid.UUID,
    item_id: uuid.UUID,
    payload: CatalogItemUpdate,
    db: DbSession,
    user: User = Depends(_MANAGE_CATALOG),
):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    repo = CatalogItemRepository(db)
    item = await repo.get(item_id, tenant_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    await repo.commit()
    return item


@router.delete("/catalog-items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_catalog_item(
    restaurant_id: uuid.UUID, item_id: uuid.UUID, db: DbSession, user: User = Depends(_MANAGE_CATALOG)
):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    repo = CatalogItemRepository(db)
    item = await repo.get(item_id, tenant_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
    try:
        await repo.delete(item)
        await repo.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Can't delete this item: it has existing orders or other data referencing it",
        )
