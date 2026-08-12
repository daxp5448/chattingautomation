import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError

from app.core.deps import DbSession, require_roles
from app.models.enums import UserRole
from app.models.image_type_profile import ImageTypeProfile
from app.models.user import User
from app.repositories.image_type_profile_repository import ImageTypeProfileRepository
from app.schemas.image import ImageTypeProfileCreate, ImageTypeProfileRead, ImageTypeProfileUpdate

router = APIRouter(prefix="/image-type-profiles", tags=["image-type-profiles"])

# Global, platform-wide config (not tenant-scoped) -- the "add a new image type / change a
# size profile without a deploy" surface named in the Business OS vision's Super Admin
# module list ("Image Library"). Write access is Super Admin only; read access is any
# authenticated user (the image upload endpoint itself needs to look up a profile by
# code regardless of who's uploading, same "nothing sensitive in a template" reasoning
# niche_templates.py's read endpoint already uses).
_require_super_admin = require_roles(UserRole.SUPER_ADMIN)


@router.get("", response_model=list[ImageTypeProfileRead])
async def list_image_type_profiles(db: DbSession, user: User = Depends(_require_super_admin)):
    return await ImageTypeProfileRepository(db).list_all()


@router.post("", response_model=ImageTypeProfileRead, status_code=status.HTTP_201_CREATED)
async def create_image_type_profile(
    payload: ImageTypeProfileCreate, db: DbSession, user: User = Depends(_require_super_admin)
):
    repo = ImageTypeProfileRepository(db)
    profile = ImageTypeProfile(**payload.model_dump())
    try:
        profile = await repo.create(profile)
        await repo.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"code '{payload.code}' already exists") from exc
    return profile


@router.patch("/{profile_id}", response_model=ImageTypeProfileRead)
async def update_image_type_profile(
    profile_id: uuid.UUID, payload: ImageTypeProfileUpdate, db: DbSession, user: User = Depends(_require_super_admin)
):
    repo = ImageTypeProfileRepository(db)
    profile = await repo.get(profile_id)
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image type profile not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(profile, field, value)
    # Marks this row as no longer sync-managed -- see
    # app/services/image_type_profile_defaults.py::sync_default_profiles, which now skips
    # any row with this flag set instead of reverting the edit on the next seed re-run.
    profile.is_customized = True
    await repo.commit()
    return profile
