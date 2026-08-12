"""add is_customized flag to niche_templates and image_type_profiles

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-08-08

Additive only. Closes a real bug (found during design review of the Niche & Flow
Management feature): both tables' seed-sync functions
(app/services/niche_template_sync.py, app/services/image_type_profile_defaults.py)
unconditionally overwrote every existing row on each re-run of their seed scripts, which
would silently revert any Super-Admin edit made through the now-added PATCH endpoints the
next time `python -m app.scripts.seed_niche_templates` / `seed_image_type_profiles` runs
(a normal, repeatable deploy step, not one-time bootstrap). This column lets a customized
row opt out of being overwritten.
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "e2f3a4b5c6d7"
down_revision = "d1e2f3a4b5c6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "niche_templates",
        sa.Column("is_customized", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "image_type_profiles",
        sa.Column("is_customized", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("image_type_profiles", "is_customized")
    op.drop_column("niche_templates", "is_customized")
