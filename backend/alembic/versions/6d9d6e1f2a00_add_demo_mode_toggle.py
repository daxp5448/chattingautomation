"""add demo mode toggle for a real business's own whatsapp number

Revision ID: 6d9d6e1f2a00
Revises: e621d6324d9e
Create Date: 2026-08-13

Additive only. Adds `demo_mode_enabled`/`demo_enabled_niche_codes` to `restaurants`, both
default/NULL for every existing row (Prince Corner included) -- unaffected until a Super
Admin explicitly flips demo_mode_enabled on for a specific business. See
app/models/restaurant.py's docstring and app/api/v1/routers/webhook.py's routing check.
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "6d9d6e1f2a00"
down_revision = "e621d6324d9e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "restaurants",
        sa.Column("demo_mode_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "restaurants",
        sa.Column("demo_enabled_niche_codes", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("restaurants", "demo_enabled_niche_codes")
    op.drop_column("restaurants", "demo_mode_enabled")
