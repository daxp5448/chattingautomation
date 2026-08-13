"""add image caption/alt_text/display_order/is_active

Revision ID: 7f8a9b0c1d2e
Revises: 6d9d6e1f2a00
Create Date: 2026-08-13

Additive only. Lets Super Admin curate multiple images per catalog item (caption, display
order, enable/disable) instead of the bot only ever using whichever image was uploaded
first -- see app/models/image.py and app/services/image_presenter.py.
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "7f8a9b0c1d2e"
down_revision = "6d9d6e1f2a00"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("images", sa.Column("caption", sa.String(length=1024), nullable=True))
    op.add_column("images", sa.Column("alt_text", sa.String(length=300), nullable=True))
    op.add_column("images", sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("images", sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade() -> None:
    op.drop_column("images", "is_active")
    op.drop_column("images", "display_order")
    op.drop_column("images", "alt_text")
    op.drop_column("images", "caption")
