"""add media_id cache columns to jewellery_designs

Revision ID: b6c7d8e9f0a1
Revises: a5b6c7d8e9f0
Create Date: 2026-08-19

Additive only -- three new nullable columns on jewellery_designs, no changes to any
existing column or constraint. See JewelleryDesign.meta_media_id's docstring: NULL for
every existing design until the send path lazily uploads and caches one.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b6c7d8e9f0a1'
down_revision: Union[str, None] = 'a5b6c7d8e9f0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('jewellery_designs', sa.Column('meta_media_id', sa.String(length=200), nullable=True))
    op.add_column('jewellery_designs', sa.Column('meta_media_id_phone_number_id', sa.String(length=50), nullable=True))
    op.add_column('jewellery_designs', sa.Column('meta_media_id_uploaded_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('jewellery_designs', 'meta_media_id_uploaded_at')
    op.drop_column('jewellery_designs', 'meta_media_id_phone_number_id')
    op.drop_column('jewellery_designs', 'meta_media_id')
