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

    Ownership is a real, typed, nullable FK per consuming model, never a polymorphic
    owner_type/owner_id pair -- matching every other table in this codebase
    (CatalogItem.category_id, EngagementItem.engagement_id, etc.), which keeps DB-level
    referential integrity and selectinload working. `catalog_item_id` was the pilot;
    `catalog_category_id` and `flow_definition_id`+`flow_step_id` (images-in-the-flow,
    not just in catalog items) were added the same way -- one more nullable FK column (+
    widened owner-count CheckConstraint) per consuming model, never a generic polymorphic
    column pair; genericity lives in the service layer (image_presenter.py), not the
    schema. `flow_step_id` has no FK of its own (steps are JSON dicts inside
    FlowDefinition.steps, not their own rows) -- it's a plain string matched against a
    step's `step_id` at read time, always paired with flow_definition_id.

    `restaurant_id` is denormalized directly onto this table (not derived by joining
    through the owner) specifically so every query can filter `WHERE restaurant_id = :tenant_id`
    the same way every other tenant-scoped table in this codebase does -- see
    app/core/deps.py::resolve_tenant_id, and BaseRepository.get's automatic restaurant_id
    filter, which this table participates in like any other tenant-scoped model.
    """

    __tablename__ = "images"
    __table_args__ = (
        # Exactly one owner "shape" must be set: catalog_item_id alone, catalog_category_id
        # alone, or flow_definition_id+flow_step_id together. Counts each shape as 0/1 and
        # requires the total to be exactly 1 -- widen this the same way (one more CASE term)
        # if another owner column is ever added, rather than making any owner column NOT
        # NULL outright (that would block a future image attaching to a different owner
        # kind without a migration touching this column).
        CheckConstraint(
            "(CASE WHEN catalog_item_id IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN catalog_category_id IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN flow_definition_id IS NOT NULL AND flow_step_id IS NOT NULL THEN 1 ELSE 0 END) = 1",
            name="ck_image_has_owner",
        ),
    )

    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    image_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)

    # --- Owner columns (one shape per consuming model, all nullable -- see class docstring) ---
    catalog_item_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("catalog_items.id", ondelete="CASCADE"), nullable=True, index=True
    )
    catalog_category_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("catalog_categories.id", ondelete="CASCADE"), nullable=True, index=True
    )
    flow_definition_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("flow_definitions.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # Matched against a step dict's `step_id` at read time (see FlowDefinition.steps'
    # docstring) -- not a DB FK, since steps are JSON entries, not rows of their own.
    flow_step_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)

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

    # --- Per-image WhatsApp presentation metadata --------------------------------------
    # A catalog item can carry more than one image (front/side/detail/worn-on-hand, etc.)
    # -- these three fields are what let Super Admin curate that set instead of the engine
    # only ever having "the first image somebody happened to upload." See
    # app/services/image_presenter.py, which is the one place that reads all three when
    # deciding what the bot actually sends.
    caption: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    alt_text: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # Lower sorts first. Defaults to 0 (not an auto-incrementing "next" value) -- every
    # pre-existing image before this column existed sorts identically to a freshly
    # uploaded one with no order set yet, both landing at upload/created_at order via the
    # repository's stable secondary sort. A Super Admin only needs to set this once they
    # actually want a specific order.
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Lets an admin temporarily hide one image from the bot (e.g. a bad angle) without
    # deleting it -- distinct from deleted_at, which is permanent/irreversible from the
    # customer-facing side. Defaults True so every pre-existing image stays visible.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
