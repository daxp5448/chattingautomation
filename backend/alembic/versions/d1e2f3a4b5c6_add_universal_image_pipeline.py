"""add universal image processing pipeline

Revision ID: d1e2f3a4b5c6
Revises: c9d0e1f2a3b4
Create Date: 2026-08-07

Additive only -- no existing table/column is altered or dropped. `images` attaches to
`catalog_items` via a real, nullable, typed FK (not a polymorphic owner_type/owner_id
pair -- see app/models/image.py's docstring for why); `CatalogItem.images` (the existing
JSON URL-list column) is left completely untouched by this migration, so nothing that
already reads it breaks.

Schema only -- no seed data here. See app/services/image_type_profile_defaults.py's
module docstring for why the 10 default ImageTypeProfile rows are seeded via an explicit,
idempotent sync function/deploy script instead of migration data (this project's test
suite builds its schema via Base.metadata.create_all, never by running migrations, so
migration-only seed data would be invisible to every test).
"""
import sqlalchemy as sa
from alembic import op

from app.db.types import GUID

# revision identifiers, used by Alembic.
revision = "d1e2f3a4b5c6"
down_revision = "c9d0e1f2a3b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "image_type_profiles",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("label", sa.String(length=100), nullable=False),
        sa.Column("variant_specs", sa.JSON(), nullable=False),
        sa.Column("max_upload_size_bytes", sa.Integer(), nullable=False),
        sa.UniqueConstraint("code", name="uq_image_type_profile_code"),
    )
    op.create_index("ix_image_type_profiles_code", "image_type_profiles", ["code"])

    op.create_table(
        "images",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("restaurant_id", GUID(), sa.ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("image_type", sa.String(length=50), nullable=False),
        sa.Column("catalog_item_id", GUID(), sa.ForeignKey("catalog_items.id", ondelete="CASCADE"), nullable=True),
        sa.Column("original_key", sa.String(length=500), nullable=False),
        sa.Column("original_format", sa.String(length=20), nullable=False),
        sa.Column("original_width", sa.Integer(), nullable=False),
        sa.Column("original_height", sa.Integer(), nullable=False),
        sa.Column("original_size_bytes", sa.Integer(), nullable=False),
        sa.Column("variants", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("failure_reason", sa.String(length=500), nullable=True),
        sa.Column("crop_box", sa.JSON(), nullable=True),
        sa.Column("resolution_warning", sa.Boolean(), nullable=False),
        sa.Column("low_quality_reason", sa.String(length=100), nullable=True),
        sa.Column("replaced_by_image_id", GUID(), sa.ForeignKey("images.id", ondelete="SET NULL"), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("catalog_item_id IS NOT NULL", name="ck_image_has_owner"),
    )
    op.create_index("ix_images_restaurant_id", "images", ["restaurant_id"])
    op.create_index("ix_images_image_type", "images", ["image_type"])
    op.create_index("ix_images_catalog_item_id", "images", ["catalog_item_id"])
    op.create_index("ix_images_status", "images", ["status"])


def downgrade() -> None:
    op.drop_table("images")
    op.drop_table("image_type_profiles")
