"""add whatsapp_quick_customize_flow_id and draft_mode

Revision ID: d8e9f0a1b2c3
Revises: c7d8e9f0a1b2
Create Date: 2026-08-20

Additive only -- two new nullable/defaulted columns on restaurants, no changes to any
existing column or constraint. See Restaurant.whatsapp_quick_customize_flow_id's
docstring: a second, independent WhatsApp Flow slot for a manually-built static Flow
(nfm_reply submission path), distinct from whatsapp_flow_order_id's auto-provisioned
dynamic Flow. NULL/false for every existing restaurant -- inert until an Owner opts in.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd8e9f0a1b2c3'
down_revision: Union[str, None] = 'c7d8e9f0a1b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('restaurants', sa.Column('whatsapp_quick_customize_flow_id', sa.String(length=50), nullable=True))
    op.add_column('restaurants', sa.Column('whatsapp_quick_customize_flow_draft_mode', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column('restaurants', 'whatsapp_quick_customize_flow_draft_mode')
    op.drop_column('restaurants', 'whatsapp_quick_customize_flow_id')
