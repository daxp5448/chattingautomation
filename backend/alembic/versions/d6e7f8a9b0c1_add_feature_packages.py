"""add feature packages

Revision ID: d6e7f8a9b0c1
Revises: c5d6e7f8a9b0
Create Date: 2026-08-11

Additive only. New Super-Admin-owned `feature_packages` table, plus two new NULLABLE
columns on `restaurants` (`feature_package_id`, `enabled_features`). See
app/models/feature_package.py, app/models/restaurant.py.

No backfill: `enabled_features IS NULL` means "never assigned a package" and is treated as
UNRESTRICTED by app/core/deps.py::require_feature -- every restaurant that exists before
this migration (including the live Prince Corner restaurant, and every demo restaurant
app/services/demo_restaurant_sync.py creates) stays NULL and is completely unaffected.
"""
import sqlalchemy as sa
from alembic import op

from app.db.types import GUID

# revision identifiers, used by Alembic.
revision = "d6e7f8a9b0c1"
down_revision = "c5d6e7f8a9b0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "feature_packages",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.String(length=1000), nullable=True),
        sa.Column("feature_codes", sa.JSON(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
    )
    op.add_column(
        "restaurants",
        sa.Column("feature_package_id", GUID(), sa.ForeignKey("feature_packages.id", ondelete="SET NULL"), nullable=True),
    )
    op.add_column("restaurants", sa.Column("enabled_features", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("restaurants", "enabled_features")
    op.drop_column("restaurants", "feature_package_id")
    op.drop_table("feature_packages")
