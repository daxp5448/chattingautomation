"""add cancelled restaurant status

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-08-06

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Postgres 12+ allows ALTER TYPE ... ADD VALUE inside a transaction as long as the
    # new value isn't used by anything else in that same transaction, which is the case
    # here -- nothing in this migration reads/writes rows using 'CANCELLED'.
    op.execute("ALTER TYPE restaurantstatus ADD VALUE IF NOT EXISTS 'CANCELLED'")


def downgrade() -> None:
    # Postgres has no ALTER TYPE ... DROP VALUE. Downgrading would require rebuilding the
    # enum type from scratch (create a new type, cast every restaurants.status value
    # across, drop the old type, rename) and is only safe if no row is actually using
    # 'CANCELLED' -- not attempted here since this app has no automated rollback path
    # that runs against a live database. If a downgrade is ever genuinely needed, do it
    # by hand after confirming no restaurant is currently cancelled.
    raise NotImplementedError(
        "Cannot automatically downgrade: Postgres does not support removing an enum "
        "value. Rebuild the restaurantstatus type by hand if this is truly required."
    )
