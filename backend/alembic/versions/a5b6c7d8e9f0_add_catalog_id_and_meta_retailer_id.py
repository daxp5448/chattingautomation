"""add whatsapp_catalog_id and meta_retailer_id

Revision ID: a5b6c7d8e9f0
Revises: 9c1d2e3f4a5b
Create Date: 2026-08-16

Additive only -- two new nullable columns, no changes to any existing column or
constraint:
  - restaurants.whatsapp_catalog_id: the Meta/Facebook Commerce Catalog id connected to
    a business's WABA (see Restaurant.whatsapp_catalog_id's docstring). NULL for every
    existing restaurant.
  - jewellery_designs.meta_retailer_id: the retailer_id a design was synced to in that
    catalog (see JewelleryDesign.meta_retailer_id's docstring). NULL for every existing
    design.

Groundwork for the real native WhatsApp Multi-Product Message carousel -- both columns
are unused/inert until a restaurant is explicitly given a catalog_id, so this migration
changes zero runtime behavior on its own.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a5b6c7d8e9f0'
down_revision: Union[str, None] = '9c1d2e3f4a5b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('restaurants', sa.Column('whatsapp_catalog_id', sa.String(length=50), nullable=True))
    op.add_column('jewellery_designs', sa.Column('meta_retailer_id', sa.String(length=200), nullable=True))


def downgrade() -> None:
    op.drop_column('jewellery_designs', 'meta_retailer_id')
    op.drop_column('restaurants', 'whatsapp_catalog_id')
