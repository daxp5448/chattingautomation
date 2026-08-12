from typing import Any

from sqlalchemy import JSON, Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ImageTypeProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The "no deploy needed" registry behind the Universal Image Processing Pipeline: a
    Super Admin adding a new image type (e.g. "vehicle") or changing a size profile edits
    a row here, not code -- see app/services/image_pipeline.py, which reads `variant_specs`
    to decide what derivative sizes to generate for a given `Image.image_type`.

    `code` is a plain, globally unique string (not a DB enum) -- same reasoning as
    CatalogItem.price_type: this list must be able to grow without a migration.
    """

    __tablename__ = "image_type_profiles"

    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    # [{"variant_name": "thumbnail", "target_context": "thumbnail", "width": 300,
    #   "height": 300, "crop_mode": "cover", "format": "webp"}, ...]
    # target_context in {whatsapp, thumbnail, banner, gallery, website}; crop_mode in
    # {cover, contain}. Validated at the schema layer, not a DB constraint, so new
    # target_contexts/crop_modes can be introduced without a migration either.
    variant_specs: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    max_upload_size_bytes: Mapped[int] = mapped_column(Integer, default=10 * 1024 * 1024)

    # Set the moment a Super Admin PATCHes this row (see
    # app/api/v1/routers/image_type_profiles.py). app/services/image_type_profile_defaults
    # .py's seed sync skips a customized row entirely on re-run instead of overwriting it --
    # a real, previously-shipped bug (found during design review of the sibling Niche & Flow
    # Management feature): without this flag, re-running the seed script (a normal,
    # repeatable deploy step, not one-time bootstrap) silently reverted any admin edit.
    is_customized: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
