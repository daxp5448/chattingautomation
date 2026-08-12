import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status

from app.core.deps import CurrentUser, DbSession, require_roles, resolve_tenant_id
from app.db.base import utcnow
from app.models.enums import UserRole
from app.models.image import Image
from app.models.user import User
from app.repositories.catalog_repository import CatalogItemRepository
from app.repositories.image_repository import ImageRepository
from app.repositories.image_type_profile_repository import ImageTypeProfileRepository
from app.schemas.image import ImageCropRequest, ImageRead
from app.services import image_pipeline, image_storage_service
from app.services.image_pipeline import ImageValidationError

router = APIRouter(prefix="/restaurants/{restaurant_id}/images", tags=["images"])

# Uploading/replacing/cropping is catalog-configuration territory, same bar as menu.py's
# category/product management -- cashier/kitchen accounts don't touch it.
_MANAGE_IMAGES = require_roles(UserRole.OWNER, UserRole.MANAGER)


def _with_urls(image: Image) -> ImageRead:
    read = ImageRead.model_validate(image)
    urls: dict[str, str] = {}
    if image.status == "ready":
        urls["original"] = image_storage_service.public_url(image.original_key)
        for name, variant in (image.variants or {}).items():
            urls[name] = image_storage_service.public_url(variant["key"])
    read.urls = urls
    return read


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
    catalog_item_id: uuid.UUID = Form(...),
    file: UploadFile = File(...),
    user: User = Depends(_MANAGE_IMAGES),
):
    tenant_id = resolve_tenant_id(user, restaurant_id)

    profile = await ImageTypeProfileRepository(db).get_by_code(image_type)
    if profile is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown image_type '{image_type}'")

    item = await CatalogItemRepository(db).get(catalog_item_id, tenant_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="catalog_item_id not found")

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
        catalog_item_id=catalog_item_id,
        original_key=f"images/{new_id}/original.{validated.format.lower()}",
        original_format=validated.format.lower(),
        original_width=validated.width,
        original_height=validated.height,
        original_size_bytes=validated.size_bytes,
        status="processing",
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
    catalog_item_id: uuid.UUID = Query(...),
):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    images = await ImageRepository(db).list_for_catalog_item(catalog_item_id, tenant_id)
    return [_with_urls(img) for img in images]


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
