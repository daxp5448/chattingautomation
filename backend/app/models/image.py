import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID


class Image(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One uploaded image and every derivative generated from it -- the core entity of the
    Universal Image Processing Pipeline (see app/services/image_pipeline.py).

    The uploaded original is never modified or regenerated: `original_key` is written once
    at upload time and every derivative (including a later manual crop) is always
    re-derived from that same original, never from another derivative. "Replace" never
    overwrites this row -- it creates a NEW Image row and links `replaced_by_image_id` on
    this one, so `restore` can always repoint back to a specific historical version.

    Ownership is a real, typed, nullable FK per consuming model (`catalog_item_id` is the
    only one this pilot adds), never a polymorphic owner_type/owner_id pair -- matching
    every other table in this codebase (CatalogItem.category_id, EngagementItem.
    engagement_id, etc.), which keeps DB-level referential integrity and selectinload
    working. Add one more nullable FK column (+ widen the owner-count CheckConstraint)
    per future consuming model rather than a generic polymorphic column pair; genericity
    lives in the service layer (image_pipeline.py), not the schema.

    `restaurant_id` is denormalized directly onto this table (not derived by joining
    through the owner) specifically so every query can filter `WHERE restaurant_id = :tenant_id`
    the same way every other tenant-scoped table in this codebase does -- see
    app/core/deps.py::resolve_tenant_id, and BaseRepository.get's automatic restaurant_id
    filter, which this table participates in like any other tenant-scoped model.
    """

    __tablename__ = "images"
    __table_args__ = (
        # Exactly one owner column must be set. Only one owner column exists in this
        # pilot (catalog_item_id) so this is trivially "IS NOT NULL" for now -- widen the
        # OR/count expression here as more nullable owner FKs are added later, rather than
        # ever making an owner column NOT NULL outright (that would block a future image
        # attaching to a different owner kind without a migration touching this column).
        CheckConstraint("catalog_item_id IS NOT NULL", name="ck_image_has_owner"),
    )

    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    image_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)

    # --- Owner columns (one per consuming model, all nullable -- see class docstring) ---
    catalog_item_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("catalog_items.id", ondelete="CASCADE"), nullable=True, index=True
    )

    original_key: Mapped[str] = mapped_column(String(500), nullable=False)
    original_format: Mapped[str] = mapped_column(String(20), nullable=False)
    original_width: Mapped[int] = mapped_column(Integer, nullable=False)
    original_height: Mapped[int] = mapped_column(Integer, nullable=False)
    original_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)

    # {variant_name: {"key", "format", "width", "height", "size_bytes"}}
    variants: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # "processing" | "ready" | "failed"
    status: Mapped[str] = mapped_column(String(20), default="processing", nullable=False, index=True)
    failure_reason: Mapped[str | None] = mapped_column(String(500))

    # Last manual crop applied, in original-pixel space: {"x", "y", "width", "height"}.
    crop_box: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # Honest heuristic flags, deliberately NOT a scored "quality_score: float" -- a fake-
    # precision number invites being treated as a real ML/perceptual quality metric later
    # (e.g. an auto-reject threshold) when the underlying check is only "is this resolution/
    # file size below what this image_type's profile expects." See low_quality_reason for
    # which specific heuristic tripped, if any.
    resolution_warning: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    low_quality_reason: Mapped[str | None] = mapped_column(String(100))

    replaced_by_image_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("images.id", ondelete="SET NULL"), nullable=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
