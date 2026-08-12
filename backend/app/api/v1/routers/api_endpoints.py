"""Super-Admin CRUD for the API_CALL step's allowlist (app/models/api_endpoint.py) --
same "Super Admin curates, business consumes" pattern as niche_templates.py/
image_type_profiles.py. A business/flow author never types a raw URL; they pick from
this catalog in the visual Flow Builder. See app/services/api_endpoint_client.py for
the SSRF protections applied at actual call time.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.deps import CurrentUser, DbSession, require_roles
from app.models.api_endpoint import ApiEndpoint
from app.models.enums import UserRole
from app.models.user import User
from app.repositories.api_endpoint_repository import ApiEndpointRepository
from app.schemas.api_endpoint import ApiEndpointCreate, ApiEndpointRead, ApiEndpointUpdate

router = APIRouter(prefix="/api-endpoints", tags=["api-endpoints"])

_require_super_admin = require_roles(UserRole.SUPER_ADMIN)


@router.get("", response_model=list[ApiEndpointRead])
async def list_api_endpoints(db: DbSession, user: CurrentUser):
    # Read-only, no tenant scoping needed -- any authenticated flow-builder user needs to
    # see the catalog to pick an endpoint for an API_CALL step; nothing sensitive is
    # exposed here (allowed_headers values are Super-Admin-set integration secrets, e.g.
    # an API key -- deliberately still readable by any staff, matching this endpoint's
    # "curated, not secret" trust model; a business that needs a truly secret credential
    # should not put it in a header a business-side flow author can already see the
    # rendered request use).
    return await ApiEndpointRepository(db).list()


@router.post("", response_model=ApiEndpointRead, status_code=status.HTTP_201_CREATED)
async def create_api_endpoint(payload: ApiEndpointCreate, db: DbSession, user: User = Depends(_require_super_admin)):
    repo = ApiEndpointRepository(db)
    endpoint = ApiEndpoint(**payload.model_dump())
    endpoint = await repo.create(endpoint)
    await repo.commit()
    return endpoint


@router.patch("/{endpoint_id}", response_model=ApiEndpointRead)
async def update_api_endpoint(
    endpoint_id: uuid.UUID, payload: ApiEndpointUpdate, db: DbSession, user: User = Depends(_require_super_admin)
):
    repo = ApiEndpointRepository(db)
    endpoint = await repo.get(endpoint_id)
    if endpoint is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API endpoint not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(endpoint, field, value)
    await repo.commit()
    return endpoint


@router.delete("/{endpoint_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_api_endpoint(endpoint_id: uuid.UUID, db: DbSession, user: User = Depends(_require_super_admin)):
    repo = ApiEndpointRepository(db)
    endpoint = await repo.get(endpoint_id)
    if endpoint is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API endpoint not found")
    # A flow step referencing a since-deleted endpoint_id fails at call time (see
    # api_endpoint_client.py::call_api_endpoint -- "missing or inactive" is raised, the
    # engine treats it as best-effort and continues the flow), not a hard delete-time
    # block -- no FK from flow step JSON back to this row (same reasoning as
    # niche_templates.py's own unrestricted delete).
    await repo.delete(endpoint)
    await repo.commit()
