"""add restaurant trial_ends_at

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-08-06

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "f6a7b8c9d0e1"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("restaurants", sa.Column("trial_ends_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("restaurants", "trial_ends_at")
