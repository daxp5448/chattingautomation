"""add display_devices

Revision ID: c3d4e5f6a7b8
Revises: a1b2c3d4e5f6
Create Date: 2026-08-06 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import app.db.types


# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'display_devices',
        sa.Column('restaurant_id', app.db.types.GUID(), nullable=False),
        sa.Column('branch_id', app.db.types.GUID(), nullable=True),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('token_hash', sa.String(length=128), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', app.db.types.GUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['branch_id'], ['branches.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['restaurant_id'], ['restaurants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_display_devices_restaurant_id'), 'display_devices', ['restaurant_id'], unique=False)
    op.create_index(op.f('ix_display_devices_branch_id'), 'display_devices', ['branch_id'], unique=False)
    op.create_index(op.f('ix_display_devices_token_hash'), 'display_devices', ['token_hash'], unique=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_display_devices_token_hash'), table_name='display_devices')
    op.drop_index(op.f('ix_display_devices_branch_id'), table_name='display_devices')
    op.drop_index(op.f('ix_display_devices_restaurant_id'), table_name='display_devices')
    op.drop_table('display_devices')
