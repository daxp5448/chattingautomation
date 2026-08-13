"""add analytics events table

Revision ID: e621d6324d9e
Revises: 6604ae969fbe
Create Date: 2026-08-13 07:02:12.899660

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.db.types import GUID

# revision identifiers, used by Alembic.
revision: str = 'e621d6324d9e'
down_revision: Union[str, None] = '6604ae969fbe'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'analytics_events',
        sa.Column('id', GUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('restaurant_id', GUID(), nullable=False),
        sa.Column('customer_id', GUID(), nullable=True),
        sa.Column('event_type', sa.String(length=64), nullable=False),
        sa.Column('step_id', sa.String(length=200), nullable=True),
        sa.Column('niche_code', sa.String(length=100), nullable=True),
        sa.Column('details', sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['restaurant_id'], ['restaurants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_analytics_events_customer_id'), 'analytics_events', ['customer_id'], unique=False)
    op.create_index(op.f('ix_analytics_events_event_type'), 'analytics_events', ['event_type'], unique=False)
    op.create_index(op.f('ix_analytics_events_niche_code'), 'analytics_events', ['niche_code'], unique=False)
    op.create_index(op.f('ix_analytics_events_restaurant_id'), 'analytics_events', ['restaurant_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_analytics_events_restaurant_id'), table_name='analytics_events')
    op.drop_index(op.f('ix_analytics_events_niche_code'), table_name='analytics_events')
    op.drop_index(op.f('ix_analytics_events_event_type'), table_name='analytics_events')
    op.drop_index(op.f('ix_analytics_events_customer_id'), table_name='analytics_events')
    op.drop_table('analytics_events')
