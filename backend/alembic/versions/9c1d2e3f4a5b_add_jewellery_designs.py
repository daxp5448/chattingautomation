"""add jewellery_designs table

Revision ID: 9c1d2e3f4a5b
Revises: 8b9c0d1e2f3a
Create Date: 2026-08-16

Additive only. New, standalone table for the jewellery-only Material -> Category ->
Design browsing carousel (see app/models/jewellery_design.py's docstring for why this
is a dedicated table instead of reusing CatalogItem/Image). No existing table is
touched by this migration.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.db.types import GUID

# revision identifiers, used by Alembic.
revision: str = '9c1d2e3f4a5b'
down_revision: Union[str, None] = '8b9c0d1e2f3a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'jewellery_designs',
        sa.Column('id', GUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('restaurant_id', GUID(), nullable=False),
        sa.Column('material', sa.String(length=50), nullable=False),
        sa.Column('category', sa.String(length=50), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('design_code', sa.String(length=50), nullable=True),
        sa.Column('image_key', sa.String(length=500), nullable=False),
        sa.Column('thumbnail_key', sa.String(length=500), nullable=True),
        sa.Column('source', sa.String(length=20), nullable=False, server_default='unsplash'),
        sa.Column('source_id', sa.String(length=200), nullable=True),
        sa.Column('display_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.ForeignKeyConstraint(['restaurant_id'], ['restaurants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_jewellery_designs_restaurant_id'), 'jewellery_designs', ['restaurant_id'], unique=False
    )
    op.create_index(
        'ix_jewellery_designs_restaurant_material_category',
        'jewellery_designs',
        ['restaurant_id', 'material', 'category'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index('ix_jewellery_designs_restaurant_material_category', table_name='jewellery_designs')
    op.drop_index(op.f('ix_jewellery_designs_restaurant_id'), table_name='jewellery_designs')
    op.drop_table('jewellery_designs')
