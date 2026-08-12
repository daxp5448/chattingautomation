import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.deps import CurrentUser, DbSession, require_roles
from app.models.enums import UserRole
from app.models.niche_template import NicheTemplate
from app.models.user import User
from app.repositories.niche_template_repository import NicheTemplateRepository
from app.schemas.niche_template import (
    NicheTemplateCreate,
    NicheTemplateFullRead,
    NicheTemplateSummary,
    NicheTemplateUpdate,
)
from app.services.flow_shape_validation import FlowShapeError, validate_entry_step, validate_flow_graph
from app.services.image_storage_service import ImageStorageError, upload_bytes

router = APIRouter(prefix="/niche-templates", tags=["niche-templates"])

# Editing niche templates (as opposed to picking one at business-creation time) is
# platform-wide config, same bar as image_type_profiles.py's registry -- Super Admin only.
_require_super_admin = require_roles(UserRole.SUPER_ADMIN)

# Deliberately NOT the Universal Image Processing Pipeline (app/api/v1/routers/images.py)
# -- that's built around a real restaurant_id + CatalogItem row and returns 30-day
# presigned URLs meant to be re-fetched (see image_storage_service.py::public_url's own
# docstring). A NicheTemplate has neither a restaurant nor real CatalogItem rows -- its
# `default_catalog`/`welcome_banner_image` are just plain string URLs baked into JSON, so
# this needs a PERMANENT (non-expiring) URL instead, same requirement
# backend/scripts/demo_asset_upload.py already solved for the 12 demo niches' own photos.
# One upload endpoint, not scoped to any single template/field -- the frontend uploads a
# file, gets a URL back, and decides where that URL goes (welcome banner, a category
# image, an item image, ...).
_ALLOWED_CONTENT_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
_MAX_UPLOAD_BYTES = 8 * 1024 * 1024


@router.post("/upload-image")
async def upload_niche_template_image(
    file: UploadFile = File(...), user: User = Depends(_require_super_admin)
) -> dict[str, str]:
    ext = _ALLOWED_CONTENT_TYPES.get(file.content_type or "")
    if ext is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only JPEG, PNG, or WebP images are allowed")
    content = await file.read()
    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Image exceeds the {_MAX_UPLOAD_BYTES // (1024 * 1024)}MB limit")

    key = f"niche-templates/uploads/{uuid.uuid4()}{ext}"
    try:
        upload_bytes(key, content, file.content_type)
    except ImageStorageError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to upload image") from exc

    return {"url": f"{settings.PUBLIC_MEDIA_BASE_URL}/{key}"}


def _validate_flow_steps(default_flow_steps: list[dict]) -> None:
    if not default_flow_steps:
        return
    # Matches app/services/niche_provisioning.py's own rule for a new business's
    # FlowDefinition.entry_step_id exactly: the first step in the list, always.
    entry_step_id = default_flow_steps[0].get("step_id")
    try:
        validate_entry_step(default_flow_steps, entry_step_id)
        validate_flow_graph(default_flow_steps)
    except FlowShapeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("", response_model=list[NicheTemplateSummary])
async def list_niche_templates(db: DbSession, user: CurrentUser):
    # Read-only, no tenant scoping needed -- every authenticated user (super_admin
    # creating a business, or a business admin curious what's available) can see the
    # catalog of available niches; nothing sensitive is in a template.
    return await NicheTemplateRepository(db).list_all()


@router.get("/{template_id}", response_model=NicheTemplateFullRead)
async def get_niche_template(template_id: uuid.UUID, db: DbSession, user: CurrentUser):
    template = await NicheTemplateRepository(db).get(template_id)
    if template is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Niche template not found")
    return template


@router.post("", response_model=NicheTemplateFullRead, status_code=status.HTTP_201_CREATED)
async def create_niche_template(
    payload: NicheTemplateCreate, db: DbSession, user: User = Depends(_require_super_admin)
):
    _validate_flow_steps(payload.default_flow_steps)
    repo = NicheTemplateRepository(db)
    template = NicheTemplate(**payload.model_dump())
    try:
        template = await repo.create(template)
        await repo.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"code '{payload.code}' already exists") from exc
    return template


@router.patch("/{template_id}", response_model=NicheTemplateFullRead)
async def update_niche_template(
    template_id: uuid.UUID, payload: NicheTemplateUpdate, db: DbSession, user: User = Depends(_require_super_admin)
):
    repo = NicheTemplateRepository(db)
    template = await repo.get(template_id)
    if template is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Niche template not found")

    updates = payload.model_dump(exclude_unset=True)
    if "default_flow_steps" in updates:
        _validate_flow_steps(updates["default_flow_steps"])
    for field, value in updates.items():
        setattr(template, field, value)
    # Marks this row as no longer sync-managed -- see
    # app/services/niche_template_sync.py::sync_niche_templates, which now skips any row
    # with this flag set instead of reverting the edit on the next seed re-run.
    template.is_customized = True
    await repo.commit()
    return template


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_niche_template(template_id: uuid.UUID, db: DbSession, user: User = Depends(_require_super_admin)):
    repo = NicheTemplateRepository(db)
    template = await repo.get(template_id)
    if template is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Niche template not found")
    # No FK from any provisioned business back to its template -- provision_from_template
    # only ever reads-then-copies (confirmed via design review) -- so this is always safe;
    # it only removes this niche from the "Add Business" picker going forward.
    await repo.delete(template)
    await repo.commit()
