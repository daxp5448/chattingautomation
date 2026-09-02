"""add conversation_settings and default_personality

Revision ID: e9f0a1b2c3d4
Revises: d8e9f0a1b2c3
Create Date: 2026-08-31

Additive only -- two new JSON columns, empty-dict default for every existing row.
restaurants.conversation_settings: per-tenant conversational tone (tone/language/
emoji_level/response_length/business_personality), read generically by
generic_flow_engine.py's conversational_style.humanize(). niche_templates.
default_personality: each niche's default tone, merged onto a newly-provisioned
business's own conversation_settings (see niche_provisioning.py). Empty dict means
humanize() no-ops entirely -- zero behavior change until explicitly configured.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e9f0a1b2c3d4'
down_revision: Union[str, None] = 'd8e9f0a1b2c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('restaurants', sa.Column('conversation_settings', sa.JSON(), nullable=False, server_default='{}'))
    op.add_column('niche_templates', sa.Column('default_personality', sa.JSON(), nullable=False, server_default='{}'))


def downgrade() -> None:
    op.drop_column('niche_templates', 'default_personality')
    op.drop_column('restaurants', 'conversation_settings')
