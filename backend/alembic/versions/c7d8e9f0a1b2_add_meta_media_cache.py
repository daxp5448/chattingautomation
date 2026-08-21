"""add meta_media_cache table

Revision ID: c7d8e9f0a1b2
Revises: b6c7d8e9f0a1
Create Date: 2026-08-19

Additive only -- one new table, no changes to any existing column or constraint. See
MetaMediaCache's docstring: a generic (phone_number_id, image_url) -> media_id cache used
by catalog item/category/flow-step images and restaurant welcome banners, alongside
JewelleryDesign's own already-existing inline meta_media_id columns (a separate mechanism
for a separate model, not replaced by this table).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.db.types import GUID

# revision identifiers, used by Alembic.
revision: str = 'c7d8e9f0a1b2'
down_revision: Union[str, None] = 'b6c7d8e9f0a1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'meta_media_cache',
        sa.Column('id', GUID(), nullable=False),
        sa.Column('restaurant_id', GUID(), nullable=False),
        sa.Column('phone_number_id', sa.String(length=50), nullable=False),
        sa.Column('image_url', sa.String(length=1000), nullable=False),
        sa.Column('media_id', sa.String(length=200), nullable=False),
        sa.Column('uploaded_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['restaurant_id'], ['restaurants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('phone_number_id', 'image_url', name='uq_meta_media_cache_phone_url'),
    )
    op.create_index(op.f('ix_meta_media_cache_restaurant_id'), 'meta_media_cache', ['restaurant_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_meta_media_cache_restaurant_id'), table_name='meta_media_cache')
    op.drop_table('meta_media_cache')
