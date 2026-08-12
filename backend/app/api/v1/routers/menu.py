import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.deps import CurrentUser, DbSession, require_roles, resolve_branch_scope, resolve_tenant_id
from app.models.branch import Branch
from app.models.category import Category
from app.models.enums import UserRole
from app.models.product import Addon, Product
from app.models.user import User
from app.repositories.menu_repository import AddonRepository, CategoryRepository, ProductRepository
from app.schemas.menu import (
    AddonCreate,
    AddonRead,
    CategoryCreate,
    CategoryRead,
    CategoryUpdate,
    ProductCreate,
    ProductRead,
    ProductUpdate,
)

router = APIRouter(prefix="/restaurants/{restaurant_id}", tags=["menu"])

# Editing the menu (categories, products, addons) is restaurant-configuration territory,
# not order-fulfillment territory -- cashier/kitchen accounts can read the menu (they need
# it to take/prepare orders) but not restructure it.
_MANAGE_MENU = require_roles(UserRole.OWNER, UserRole.MANAGER)


# --- Categories -----------------------------------------------------------------


@router.post("/categories", response_model=CategoryRead, status_code=status.HTTP_201_CREATED)
async def create_category(
    restaurant_id: uuid.UUID, payload: CategoryCreate, db: DbSession, user: User = Depends(_MANAGE_MENU)
):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    repo = CategoryRepository(db)
    category = Category(restaurant_id=tenant_id, **payload.model_dump())
    category = await repo.create(category)
    await repo.commit()
    return category


@router.get("/categories", response_model=list[CategoryRead])
async def list_categories(restaurant_id: uuid.UUID, db: DbSession, user: CurrentUser):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    repo = CategoryRepository(db)
    categories = await repo.list(restaurant_id=tenant_id)
    return sorted(categories, key=lambda c: c.display_order)


@router.patch("/categories/{category_id}", response_model=CategoryRead)
async def update_category(
    restaurant_id: uuid.UUID,
    category_id: uuid.UUID,
    payload: CategoryUpdate,
    db: DbSession,
    user: User = Depends(_MANAGE_MENU),
):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    repo = CategoryRepository(db)
    category = await repo.get(category_id, tenant_id)
    if not category:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(category, field, value)
    await repo.commit()
    return category


@router.delete("/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_category(
    restaurant_id: uuid.UUID, category_id: uuid.UUID, db: DbSession, user: User = Depends(_MANAGE_MENU)
):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    repo = CategoryRepository(db)
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
            detail="Can't delete this category: it has existing products or other data referencing it",
        )


# --- Products ---------------------------------------------------------------------


@router.post("/products", response_model=ProductRead, status_code=status.HTTP_201_CREATED)
async def create_product(
    restaurant_id: uuid.UUID, payload: ProductCreate, db: DbSession, user: User = Depends(_MANAGE_MENU)
):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    repo = ProductRepository(db)
    data = payload.model_dump(exclude={"branch_ids", "addon_ids"})
    product = Product(restaurant_id=tenant_id, **data)

    if payload.branch_ids:
        result = await db.execute(select(Branch).where(Branch.id.in_(payload.branch_ids), Branch.restaurant_id == tenant_id))
        product.branches = list(result.scalars().all())
    if payload.addon_ids:
        result = await db.execute(select(Addon).where(Addon.id.in_(payload.addon_ids), Addon.restaurant_id == tenant_id))
        product.addons = list(result.scalars().all())

    product = await repo.create(product)
    await repo.commit()
    return await repo.get_with_relations(product.id, tenant_id)


@router.get("/products", response_model=list[ProductRead])
async def list_products(
    restaurant_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
    branch_id: uuid.UUID | None = Query(default=None),
):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    # A cashier/kitchen account pinned to one branch (user.branch_id) is restricted to
    # that branch's products; owner/manager/super_admin (and branch-less staff) are
    # unrestricted. See app/core/deps.py::resolve_branch_scope for the full contract --
    # raises 403 if this caller explicitly asked for a branch that isn't their own.
    effective_branch_id = resolve_branch_scope(user, branch_id)
    repo = ProductRepository(db)
    # TODO: pass branch_id=effective_branch_id once menu_repository.py's ProductRepository
    # supports filtering by branch (joining the product_branch table -- a product with no
    # branch assigned there should count as "available at every branch"). Until that
    # param exists, this still returns every one of the restaurant's products regardless
    # of effective_branch_id.
    return await repo.list(restaurant_id=tenant_id)


@router.patch("/products/{product_id}", response_model=ProductRead)
async def update_product(
    restaurant_id: uuid.UUID,
    product_id: uuid.UUID,
    payload: ProductUpdate,
    db: DbSession,
    user: User = Depends(_MANAGE_MENU),
):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    repo = ProductRepository(db)
    product = await repo.get_with_relations(product_id, tenant_id)
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    updates = payload.model_dump(exclude_unset=True, exclude={"branch_ids", "addon_ids"})
    for field, value in updates.items():
        setattr(product, field, value)

    if payload.branch_ids is not None:
        result = await db.execute(select(Branch).where(Branch.id.in_(payload.branch_ids), Branch.restaurant_id == tenant_id))
        product.branches = list(result.scalars().all())
    if payload.addon_ids is not None:
        result = await db.execute(select(Addon).where(Addon.id.in_(payload.addon_ids), Addon.restaurant_id == tenant_id))
        product.addons = list(result.scalars().all())

    await repo.commit()
    return await repo.get_with_relations(product.id, tenant_id)


@router.delete("/products/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(
    restaurant_id: uuid.UUID, product_id: uuid.UUID, db: DbSession, user: User = Depends(_MANAGE_MENU)
):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    repo = ProductRepository(db)
    product = await repo.get(product_id, tenant_id)
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    try:
        await repo.delete(product)
        await repo.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Can't delete this product: it has existing orders or other data referencing it",
        )


# --- Addons -------------------------------------------------------------------


@router.post("/addons", response_model=AddonRead, status_code=status.HTTP_201_CREATED)
async def create_addon(
    restaurant_id: uuid.UUID, payload: AddonCreate, db: DbSession, user: User = Depends(_MANAGE_MENU)
):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    repo = AddonRepository(db)
    addon = Addon(restaurant_id=tenant_id, name=payload.name, price=payload.price)
    addon = await repo.create(addon)
    await repo.commit()
    return addon


@router.get("/addons", response_model=list[AddonRead])
async def list_addons(restaurant_id: uuid.UUID, db: DbSession, user: CurrentUser):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    repo = AddonRepository(db)
    return await repo.list(restaurant_id=tenant_id)
