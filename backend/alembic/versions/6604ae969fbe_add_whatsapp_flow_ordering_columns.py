"""add whatsapp flow ordering columns

Revision ID: 6604ae969fbe
Revises: d6e7f8a9b0c1
Create Date: 2026-08-12 12:58:21.120179

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '6604ae969fbe'
down_revision: Union[str, None] = 'd6e7f8a9b0c1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Purely additive, nullable columns -- see the approved "WhatsApp Flows for Ordering"
    # plan. Every pre-existing restaurant is unaffected (both stay NULL) until an Owner
    # explicitly opts in.
    op.add_column('restaurants', sa.Column('whatsapp_flow_order_id', sa.String(length=50), nullable=True))
    op.add_column('restaurants', sa.Column('whatsapp_flow_private_key_encrypted', sa.String(length=4000), nullable=True))


def downgrade() -> None:
    op.drop_column('restaurants', 'whatsapp_flow_private_key_encrypted')
    op.drop_column('restaurants', 'whatsapp_flow_order_id')
