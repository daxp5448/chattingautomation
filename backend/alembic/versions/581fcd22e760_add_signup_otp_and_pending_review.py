"""add signup OTP columns and pending_review restaurant status

Revision ID: 581fcd22e760
Revises: f0a1b2c3d4e5
Create Date: 2026-09-03

Additive only. Supports the public self-serve signup flow (POST /signup,
POST /signup/verify-otp, POST /signup/resend-otp): a new PENDING_REVIEW value on the
Postgres-native restaurantstatus enum (a self-signed-up restaurant sits here, blocked from
real WhatsApp traffic in webhook.py's _BLOCKED_STATUSES, until a Super Admin approves it to
'active'), plus four nullable/zero-defaulted columns on users mirroring the existing
setup_token_hash/setup_token_expires_at pair, but for a typed 6-digit OTP instead of a
clicked link -- see app/core/security.py::hash_otp/generate_otp.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '581fcd22e760'
down_revision: Union[str, None] = 'f0a1b2c3d4e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Postgres 12+ allows ALTER TYPE ... ADD VALUE inside a transaction as long as the new
    # value isn't used by anything else in that same transaction -- true here, matching
    # e5f6a7b8c9d0's precedent for adding 'CANCELLED' the same way.
    op.execute("ALTER TYPE restaurantstatus ADD VALUE IF NOT EXISTS 'PENDING_REVIEW'")

    op.add_column('users', sa.Column('otp_hash', sa.String(length=64), nullable=True))
    op.create_index('ix_users_otp_hash', 'users', ['otp_hash'])
    op.add_column('users', sa.Column('otp_expires_at', sa.DateTime(), nullable=True))
    op.add_column('users', sa.Column('otp_attempts', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('users', sa.Column('otp_resend_count', sa.Integer(), nullable=False, server_default='0'))


def downgrade() -> None:
    op.drop_column('users', 'otp_resend_count')
    op.drop_column('users', 'otp_attempts')
    op.drop_column('users', 'otp_expires_at')
    op.drop_index('ix_users_otp_hash', table_name='users')
    op.drop_column('users', 'otp_hash')
    # Postgres has no ALTER TYPE ... DROP VALUE -- same limitation e5f6a7b8c9d0 already
    # documented for 'CANCELLED'. Rebuilding the enum type is only safe if no restaurant is
    # currently pending_review; not attempted here since this app has no automated
    # rollback path that runs against a live database.
    raise NotImplementedError(
        "Cannot automatically downgrade: Postgres does not support removing an enum "
        "value. Rebuild the restaurantstatus type by hand if this is truly required."
    )
