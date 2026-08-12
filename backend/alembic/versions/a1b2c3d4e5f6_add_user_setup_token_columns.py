"""add user setup token columns

Revision ID: a1b2c3d4e5f6
Revises: 86ee99a92963
Create Date: 2026-08-06 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '86ee99a92963'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # One-time account-setup flow (POST /restaurants + POST /auth/setup): replaces
    # returning a plaintext temporary password with a hashed, expiring setup token.
    # Nullable so existing users are unaffected.
    op.add_column('users', sa.Column('setup_token_hash', sa.String(length=64), nullable=True))
    op.add_column('users', sa.Column('setup_token_expires_at', sa.DateTime(timezone=False), nullable=True))
    op.create_index(op.f('ix_users_setup_token_hash'), 'users', ['setup_token_hash'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_users_setup_token_hash'), table_name='users')
    op.drop_column('users', 'setup_token_expires_at')
    op.drop_column('users', 'setup_token_hash')
