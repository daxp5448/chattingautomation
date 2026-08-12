"""add restaurant state column and restaurant_invoice_counters table

Revision ID: b7c8d9e0f1a2
Revises: f6a7b8c9d0e1
Create Date: 2026-08-07

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

import app.db.types

# revision identifiers, used by Alembic.
revision: str = "b7c8d9e0f1a2"
down_revision: Union[str, None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("restaurants", sa.Column("state", sa.String(length=100), nullable=True))

    op.create_table(
        "restaurant_invoice_counters",
        sa.Column("restaurant_id", app.db.types.GUID(), nullable=False),
        sa.Column("financial_year", sa.String(length=10), nullable=False),
        sa.Column("next_number", sa.Integer(), nullable=False),
        sa.Column("id", app.db.types.GUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["restaurant_id"], ["restaurants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("restaurant_id", "financial_year", name="uq_invoice_counter_restaurant_fy"),
    )
    op.create_index(
        op.f("ix_restaurant_invoice_counters_restaurant_id"),
        "restaurant_invoice_counters",
        ["restaurant_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_restaurant_invoice_counters_restaurant_id"), table_name="restaurant_invoice_counters"
    )
    op.drop_table("restaurant_invoice_counters")
    op.drop_column("restaurants", "state")
