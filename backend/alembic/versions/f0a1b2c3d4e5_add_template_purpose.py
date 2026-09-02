"""add whatsapp_templates.purpose

Revision ID: f0a1b2c3d4e5
Revises: e9f0a1b2c3d4
Create Date: 2026-08-31

Additive only -- one new column, 'general' default for every existing template row.
Lets template_purpose_mapping.py recommend a tenant's own approved templates for their
niche's typical Broadcast Campaign use cases (see app/models/enums.py::TemplatePurpose).
Nothing is reclassified automatically; an Owner sets a real purpose explicitly per
template going forward.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f0a1b2c3d4e5'
down_revision: Union[str, None] = 'e9f0a1b2c3d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('whatsapp_templates', sa.Column('purpose', sa.String(length=30), nullable=False, server_default='general'))


def downgrade() -> None:
    op.drop_column('whatsapp_templates', 'purpose')
