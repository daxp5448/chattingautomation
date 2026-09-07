"""add restaurants.is_demo_billing_paid

Revision ID: ba4c449c3cf8
Revises: 581fcd22e760
Create Date: 2026-09-04

Additive only. DEMO ONLY -- no real payment gateway is involved (see
app/api/v1/routers/billing.py's docstring). Backs the internal "7-day free trial, then a
fake Pay Now screen" demo: True once an owner clicks Pay Now after their trial ends. Not
read by webhook gating, dashboard blocking, or anything else in the platform.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'ba4c449c3cf8'
down_revision: Union[str, None] = '581fcd22e760'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('restaurants', sa.Column('is_demo_billing_paid', sa.Boolean(), nullable=False, server_default='false'))


def downgrade() -> None:
    op.drop_column('restaurants', 'is_demo_billing_paid')
