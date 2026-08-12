import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError

from app.core.deps import CurrentUser, DbSession, require_roles, resolve_tenant_id
from app.models.branch import Branch
from app.models.enums import UserRole
from app.models.user import User
from app.repositories.branch_repository import BranchRepository
from app.schemas.branch import BranchCreate, BranchRead, BranchUpdate

router = APIRouter(prefix="/restaurants/{restaurant_id}/branches", tags=["branches"])

# Creating/editing/deleting branches is restaurant-configuration territory, not
# order-fulfillment territory -- cashier/kitchen accounts only need to read branch data
# (e.g. to know where they work), not restructure the restaurant's branch list.
_MANAGE_BRANCHES = require_roles(UserRole.OWNER, UserRole.MANAGER)


@router.post("", response_model=BranchRead, status_code=status.HTTP_201_CREATED)
async def create_branch(
    restaurant_id: uuid.UUID, payload: BranchCreate, db: DbSession, user: User = Depends(_MANAGE_BRANCHES)
):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    repo = BranchRepository(db)
    branch = Branch(restaurant_id=tenant_id, **payload.model_dump())
    branch = await repo.create(branch)
    await repo.commit()
    return branch


@router.get("", response_model=list[BranchRead])
async def list_branches(restaurant_id: uuid.UUID, db: DbSession, user: CurrentUser):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    repo = BranchRepository(db)
    return await repo.list(restaurant_id=tenant_id)


@router.patch("/{branch_id}", response_model=BranchRead)
async def update_branch(
    restaurant_id: uuid.UUID,
    branch_id: uuid.UUID,
    payload: BranchUpdate,
    db: DbSession,
    user: User = Depends(_MANAGE_BRANCHES),
):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    repo = BranchRepository(db)
    branch = await repo.get(branch_id, tenant_id)
    if not branch:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Branch not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(branch, field, value)
    await repo.commit()
    return branch


@router.delete("/{branch_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_branch(
    restaurant_id: uuid.UUID, branch_id: uuid.UUID, db: DbSession, user: User = Depends(_MANAGE_BRANCHES)
):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    repo = BranchRepository(db)
    branch = await repo.get(branch_id, tenant_id)
    if not branch:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Branch not found")
    try:
        await repo.delete(branch)
        await repo.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Can't delete this branch: it has existing orders or other data referencing it",
        )
