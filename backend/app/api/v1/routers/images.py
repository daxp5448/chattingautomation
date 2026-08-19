import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status

from app.core.deps import CurrentUser, DbSession, require_roles, resolve_tenant_id
from app.db.base import utcnow
from app.models.enums import UserRole
from app.models.image import Image
from app.models.user import User
from app.repositories.catalog_repository import CatalogCategoryRepository, CatalogItemRepository
from app.repositories.flow_definition_repository import FlowDefinitionRepository
from app.repositories.image_repository import ImageRepository
from app.repositories.image_type_profile_repository import ImageTypeProfileRepository
from app.schemas.image import (
    CatalogItemRef,
    ImageAttachRequest,
    ImageCropRequest,
    ImageLibraryEntry,
    ImageMetadataUpdate,
    ImageRead,
)
from app.services import image_pipeline, image_storage_service
from app.services.image_pipeline import ImageValidationError

router = APIRouter(prefix="/restaurants/{restaurant_id}/images", tags=["images"])

# Uploading/replacing/cropping is catalog-configuration territory, same bar as menu.py's
# category/product management -- cashier/kitchen accounts don't touch it.
_MANAGE_IMAGES = require_roles(UserRole.OWNER, UserRole.MANAGER)


def _populate_urls(read: ImageRead, image: Image) -> None:
    urls: dict[str, str] = {}
    if image.status == "ready":
        urls["original"] = image_storage_service.public_url(image.original_key)
        for name, variant in (image.variants or {}).items():
            urls[name] = image_storage_service.public_url(variant["key"])
    read.urls = urls


def _with_urls(image: Image) -> ImageRead:
    read = ImageRead.model_validate(image)
    _populate_urls(read, image)
    return read


async def _resolve_owner(
    db: DbSession,
    tenant_id: uuid.UUID,
    *,
    catalog_item_id: uuid.UUID | None,
    catalog_category_id: uuid.UUID | None,
    flow_definition_id: uuid.UUID | None,
    flow_step_id: str | None,
) -> dict:
    """Validates exactly one owner shape is set and that the referenced owner exists within
    this tenant, returning the Image-constructor kwargs for it. Shared by upload_image and
    attach_image so the two entry points into image ownership can never diverge on
    validation -- mirrors the DB's own ck_image_has_owner constraint.
    """
    if (flow_definition_id is None) != (flow_step_id is None):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "flow_definition_id and flow_step_id must be set together")

    shapes_set = sum([
        catalog_item_id is not None,
        catalog_category_id is not None,
        flow_definition_id is not None,
    ])
    if shapes_set != 1:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Exactly one of catalog_item_id, catalog_category_id, or "
            "flow_definition_id+flow_step_id must be set",
        )

    if catalog_item_id is not None:
        item = await CatalogItemRepository(db).get(catalog_item_id, tenant_id)
        if item is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "catalog_item_id not found")
        return {"catalog_item_id": catalog_item_id}

    if catalog_category_id is not None:
        category = await CatalogCategoryRepository(db).get(catalog_category_id, tenant_id)
        if category is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "catalog_category_id not found")
        return {"catalog_category_id": catalog_category_id}

    flow = await FlowDefinitionRepository(db).get(flow_definition_id, tenant_id)
    if flow is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "flow_definition_id not found")
    if not any(s.get("step_id") == flow_step_id for s in flow.steps):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "flow_step_id not found in this flow")
    return {"flow_definition_id": flow_definition_id, "flow_step_id": flow_step_id}


async def _get_owned_image(db: DbSession, tenant_id: uuid.UUID, image_id: uuid.UUID) -> Image:
    """Loads an Image scoped to `tenant_id` -- BaseRepository.get's restaurant_id filter is
    what actually enforces tenant isolation here (an id from another tenant simply won't
    match the WHERE clause and comes back as None -> 404), the same mechanism every other
    tenant-scoped repository lookup in this codebase relies on. GUID unguessability alone
    is never treated as sufficient isolation.
    """
    image = await ImageRepository(db).get(image_id, tenant_id)
    if image is None or image.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")
    return image


@router.post("", response_model=ImageRead, status_code=status.HTTP_201_CREATED)
async def upload_image(
    restaurant_id: uuid.UUID,
    db: DbSession,
    image_type: str = Form(...),
    catalog_item_id: uuid.UUID | None = Form(None),
    catalog_category_id: uuid.UUID | None = Form(None),
    flow_definition_id: uuid.UUID | None = Form(None),
    flow_step_id: str | None = Form(None),
    file: UploadFile = File(...),
    caption: str | None = Form(None),
    alt_text: str | None = Form(None),
    display_order: int = Form(0),
    user: User = Depends(_MANAGE_IMAGES),
):
    tenant_id = resolve_tenant_id(user, restaurant_id)

    profile = await ImageTypeProfileRepository(db).get_by_code(image_type)
    if profile is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown image_type '{image_type}'")

    owner_kwargs = await _resolve_owner(
        db,
        tenant_id,
        catalog_item_id=catalog_item_id,
        catalog_category_id=catalog_category_id,
        flow_definition_id=flow_definition_id,
        flow_step_id=flow_step_id,
    )

    raw_bytes = await file.read()
    try:
        validated = image_pipeline.validate_upload(raw_bytes, profile.max_upload_size_bytes)
    except ImageValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    new_id = uuid.uuid4()
    image = Image(
        id=new_id,
        restaurant_id=tenant_id,
        image_type=image_type,
        original_key=f"images/{new_id}/original.{validated.format.lower()}",
        original_format=validated.format.lower(),
        original_width=validated.width,
        original_height=validated.height,
        original_size_bytes=validated.size_bytes,
        status="processing",
        caption=caption,
        alt_text=alt_text,
        display_order=display_order,
        **owner_kwargs,
    )
    repo = ImageRepository(db)
    image = await repo.create(image)

    # Original upload is synchronous and load-bearing -- a real, surfaced failure here
    # (never a silent no-op) since the whole point of this endpoint is "the file is now
    # durably stored." See image_storage_service's module docstring for why this doesn't
    # reuse storage_service.py's best-effort client.
    try:
        image_storage_service.upload_bytes(image.original_key, raw_bytes, f"image/{validated.format.lower()}")
    except image_storage_service.ImageStorageError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to store image") from exc

    await repo.commit()
    await image_pipeline.enqueue_processing(image.id)
    # In production this is a no-op (real Celery dispatch is async, nothing has changed
    # yet by the time we get here) -- but process_image() commits via its own separate
    # session (matches app/tasks/reconciliation.py's pattern), so `image` (this session's
    # own copy) must be refreshed to reflect it whenever processing DID complete
    # synchronously, as it always does in tests (see conftest.py's _sync_image_processing).
    await db.refresh(image)
    return _with_urls(image)


@router.get("/library", response_model=list[ImageLibraryEntry])
async def list_image_library(
    restaurant_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
    search: str | None = Query(None, description="Filter by the owning catalog item's name (substring, case-insensitive)"),
    image_type: str | None = Query(None, description="Filter by exact image_type code"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """Restaurant-wide browse/search across every image, regardless of which catalog item
    it belongs to -- powers the Media Library page. Deliberately a separate path from the
    catalog_item_id-required `GET ""` below (that endpoint's contract is unchanged and
    still used by the per-item image widget). Must stay registered before `/{image_id}`
    below: FastAPI/Starlette matches routes in declaration order, and "library" would
    otherwise be captured by `/{image_id}`'s UUID path param (and 422, never falling
    through to this route).
    """
    tenant_id = resolve_tenant_id(user, restaurant_id)
    rows = await ImageRepository(db).list_for_restaurant(
        tenant_id, search=search, image_type=image_type, limit=limit, offset=offset
    )
    entries: list[ImageLibraryEntry] = []
    for image, item in rows:
        entry = ImageLibraryEntry.model_validate(image)
        _populate_urls(entry, image)
        entry.catalog_item = CatalogItemRef.model_validate(item) if item is not None else None
        entries.append(entry)
    return entries


@router.get("/{image_id}", response_model=ImageRead)
async def get_image(restaurant_id: uuid.UUID, image_id: uuid.UUID, db: DbSession, user: CurrentUser):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    image = await _get_owned_image(db, tenant_id, image_id)
    return _with_urls(image)


@router.get("", response_model=list[ImageRead])
async def list_images(
    restaurant_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
    catalog_item_id: uuid.UUID | None = Query(None),
    catalog_category_id: uuid.UUID | None = Query(None),
    flow_definition_id: uuid.UUID | None = Query(None),
    flow_step_id: str | None = Query(None),
):
    """Images for exactly one owner -- pass catalog_item_id, catalog_category_id, or the
    flow_definition_id+flow_step_id pair (never more than one shape at once).
    """
    tenant_id = resolve_tenant_id(user, restaurant_id)
    if catalog_item_id is not None:
        images = await ImageRepository(db).list_for_catalog_item(catalog_item_id, tenant_id)
    elif catalog_category_id is not None:
        images = await ImageRepository(db).list_for_catalog_category(catalog_category_id, tenant_id)
    elif flow_definition_id is not None and flow_step_id is not None:
        images = await ImageRepository(db).list_for_flow_step(flow_definition_id, flow_step_id, tenant_id)
    else:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Provide catalog_item_id, catalog_category_id, or flow_definition_id+flow_step_id",
        )
    return [_with_urls(img) for img in images]


@router.post("/{image_id}/attach", response_model=ImageRead, status_code=status.HTTP_201_CREATED)
async def attach_image(
    restaurant_id: uuid.UUID,
    image_id: uuid.UUID,
    payload: ImageAttachRequest,
    db: DbSession,
    user: User = Depends(_MANAGE_IMAGES),
):
    """The 'Choose From Media Library' reuse path: clones an already-uploaded, already-
    processed image's storage fields (same original_key/variants -- no re-upload, no
    reprocessing, status is 'ready' immediately) onto a new row against a new owner, with
    its own fresh caption/display_order. The source image is untouched -- one physical
    upload can end up attached to several owners this way (e.g. the same product shot
    reused across two categories) without duplicating storage.
    """
    tenant_id = resolve_tenant_id(user, restaurant_id)
    source = await _get_owned_image(db, tenant_id, image_id)
    if source.status != "ready":
        raise HTTPException(status.HTTP_409_CONFLICT, "Source image is not ready yet")

    owner_kwargs = await _resolve_owner(
        db,
        tenant_id,
        catalog_item_id=payload.catalog_item_id,
        catalog_category_id=payload.catalog_category_id,
        flow_definition_id=payload.flow_definition_id,
        flow_step_id=payload.flow_step_id,
    )

    new_image = Image(
        id=uuid.uuid4(),
        restaurant_id=tenant_id,
        image_type=source.image_type,
        original_key=source.original_key,
        original_format=source.original_format,
        original_width=source.original_width,
        original_height=source.original_height,
        original_size_bytes=source.original_size_bytes,
        variants=dict(source.variants or {}),
        status="ready",
        resolution_warning=source.resolution_warning,
        low_quality_reason=source.low_quality_reason,
        caption=payload.caption,
        alt_text=payload.alt_text,
        display_order=payload.display_order,
        **owner_kwargs,
    )
    repo = ImageRepository(db)
    new_image = await repo.create(new_image)
    await repo.commit()
    return _with_urls(new_image)


@router.patch("/{image_id}", response_model=ImageRead)
async def update_image_metadata(
    restaurant_id: uuid.UUID,
    image_id: uuid.UUID,
    payload: ImageMetadataUpdate,
    db: DbSession,
    user: User = Depends(_MANAGE_IMAGES),
):
    """Caption/alt text/display order/enable-disable -- metadata only, never touches the
    stored bytes or triggers reprocessing (see upload/replace/crop for those). This is
    what the per-item image gallery editor (Flow Builder / Catalog) saves through when an
    admin edits a caption, drags to reorder, or toggles an image off without deleting it.
    """
    tenant_id = resolve_tenant_id(user, restaurant_id)
    image = await _get_owned_image(db, tenant_id, image_id)

    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(image, field, value)

    repo = ImageRepository(db)
    await repo.commit()
    return _with_urls(image)


@router.post("/{image_id}/crop", response_model=ImageRead)
async def crop_image(
    restaurant_id: uuid.UUID,
    image_id: uuid.UUID,
    payload: ImageCropRequest,
    db: DbSession,
    user: User = Depends(_MANAGE_IMAGES),
):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    image = await _get_owned_image(db, tenant_id, image_id)
    if image.status != "ready":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Image is not ready yet")

    repo = ImageRepository(db)
    image.crop_box = payload.model_dump()
    image.status = "processing"
    await repo.commit()
    # Always regenerates every variant from original_key, never from a previous
    # derivative -- see process_image's docstring.
    await image_pipeline.enqueue_processing(image.id)
    await db.refresh(image)  # see upload_image's identical comment on why this is needed
    return _with_urls(image)


@router.post("/{image_id}/replace", response_model=ImageRead, status_code=status.HTTP_201_CREATED)
async def replace_image(
    restaurant_id: uuid.UUID,
    image_id: uuid.UUID,
    db: DbSession,
    file: UploadFile = File(...),
    user: User = Depends(_MANAGE_IMAGES),
):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    old_image = await _get_owned_image(db, tenant_id, image_id)

    profile = await ImageTypeProfileRepository(db).get_by_code(old_image.image_type)
    max_size = profile.max_upload_size_bytes if profile else image_pipeline.MAX_UPLOAD_BYTES

    raw_bytes = await file.read()
    try:
        validated = image_pipeline.validate_upload(raw_bytes, max_size)
    except ImageValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    new_id = uuid.uuid4()
    repo = ImageRepository(db)
    new_image = Image(
        id=new_id,
        restaurant_id=tenant_id,
        image_type=old_image.image_type,
        catalog_item_id=old_image.catalog_item_id,
        catalog_category_id=old_image.catalog_category_id,
        flow_definition_id=old_image.flow_definition_id,
        flow_step_id=old_image.flow_step_id,
        original_key=f"images/{new_id}/original.{validated.format.lower()}",
        original_format=validated.format.lower(),
        original_width=validated.width,
        original_height=validated.height,
        original_size_bytes=validated.size_bytes,
        status="processing",
    )
    new_image = await repo.create(new_image)

    try:
        image_storage_service.upload_bytes(new_image.original_key, raw_bytes, f"image/{validated.format.lower()}")
    except image_storage_service.ImageStorageError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to store image") from exc

    # Never overwrites the old row -- links it forward instead, so `restore` always has
    # a specific, real historical Image to repoint back to.
    old_image.replaced_by_image_id = new_image.id
    await repo.commit()
    await image_pipeline.enqueue_processing(new_image.id)
    await db.refresh(new_image)  # see upload_image's identical comment on why this is needed
    return _with_urls(new_image)


@router.post("/{image_id}/restore", response_model=ImageRead)
async def restore_image(
    restaurant_id: uuid.UUID,
    image_id: uuid.UUID,
    db: DbSession,
    user: User = Depends(_MANAGE_IMAGES),
):
    """Repoints to an older, specific historical Image (identified by `image_id`) as the
    one to use going forward -- implemented as marking it "current" by clearing whatever
    replaced it, mirroring `replace`'s own forward-linking. Does not delete or resurrect
    rows; every version stays exactly as it was.
    """
    tenant_id = resolve_tenant_id(user, restaurant_id)
    image = await _get_owned_image(db, tenant_id, image_id)
    if image.status != "ready":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Image is not ready")

    repo = ImageRepository(db)
    image.replaced_by_image_id = None
    await repo.commit()
    return _with_urls(image)


@router.delete("/{image_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_image(
    restaurant_id: uuid.UUID,
    image_id: uuid.UUID,
    db: DbSession,
    user: User = Depends(_MANAGE_IMAGES),
):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    image = await _get_owned_image(db, tenant_id, image_id)
    repo = ImageRepository(db)
    image.deleted_at = utcnow()
    await repo.commit()
