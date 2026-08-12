"""Super-Admin CRUD for FeaturePackage (app/models/feature_package.py) -- same
"Super Admin curates, business consumes" pattern as niche_templates.py/api_endpoints.py.
Assigning a package to a business happens in restaurants.py (create/update), which
snapshot-copies feature_codes into Restaurant.enabled_features -- editing a package here
never retroactively changes a business already assigned to it. See
app/core/feature_registry.py for the fixed code catalog and app/core/deps.py::require_feature
for enforcement.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.deps import CurrentUser, DbSession, require_roles
from app.core.feature_registry import FEATURE_REGISTRY
from app.models.enums import UserRole
from app.models.feature_package import FeaturePackage
from app.models.user import User
from app.repositories.feature_package_repository import FeaturePackageRepository
from app.schemas.feature_package import FeaturePackageCreate, FeaturePackageRead, FeaturePackageUpdate

router = APIRouter(prefix="/feature-packages", tags=["feature-packages"])

_require_super_admin = require_roles(UserRole.SUPER_ADMIN)


@router.get("/registry")
async def list_feature_registry(user: CurrentUser) -> dict[str, str]:
    """The fixed catalog packages are built from -- powers the checkbox list in the
    Feature Packages admin page. Read-only, any authenticated user (same trust level as
    GET /feature-packages below)."""
    return FEATURE_REGISTRY


@router.get("", response_model=list[FeaturePackageRead])
async def list_feature_packages(db: DbSession, user: CurrentUser):
    # Read-only, no tenant scoping -- any authenticated user needs to see the catalog to
    # populate the "Add Restaurant" package dropdown, same reasoning as api_endpoints.py's
    # own open list endpoint.
    return await FeaturePackageRepository(db).list()


@router.post("", response_model=FeaturePackageRead, status_code=status.HTTP_201_CREATED)
async def create_feature_package(payload: FeaturePackageCreate, db: DbSession, user: User = Depends(_require_super_admin)):
    repo = FeaturePackageRepository(db)
    package = FeaturePackage(**payload.model_dump())
    package = await repo.create(package)
    await repo.commit()
    return package


@router.patch("/{package_id}", response_model=FeaturePackageRead)
async def update_feature_package(
    package_id: uuid.UUID, payload: FeaturePackageUpdate, db: DbSession, user: User = Depends(_require_super_admin)
):
    repo = FeaturePackageRepository(db)
    package = await repo.get(package_id)
    if package is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Feature package not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(package, field, value)
    await repo.commit()
    return package


@router.delete("/{package_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_feature_package(package_id: uuid.UUID, db: DbSession, user: User = Depends(_require_super_admin)):
    repo = FeaturePackageRepository(db)
    package = await repo.get(package_id)
    if package is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Feature package not found")
    # A restaurant that referenced this package keeps its already-snapshotted
    # enabled_features untouched (that's the whole point of snapshot-at-assignment, see
    # FeaturePackage's docstring) -- only feature_package_id (a plain nullable FK with
    # ondelete=SET NULL) is affected, purely cosmetic ("which package is shown as
    # selected"). No FK-restrict block needed, unlike a row an active flow step can
    # reference by id (e.g. ApiEndpoint).
    await repo.delete(package)
    await repo.commit()
