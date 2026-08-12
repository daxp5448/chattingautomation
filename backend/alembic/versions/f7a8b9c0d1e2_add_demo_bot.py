"""add demo bot support

Revision ID: f7a8b9c0d1e2
Revises: e2f3a4b5c6d7
Create Date: 2026-08-08

Additive only. Adds `is_demo`/`demo_sends_via_restaurant_id` to `restaurants` (both
default/NULL for every existing row -- Prince Corner and every other real business is
unaffected) and a new `demo_sessions` table. See app/services/demo_bot_service.py for
what these support: Phase 1 Item 4, "one WhatsApp number, 'Hi' -> select industry -> run
a complete demo of that niche -> try another industry."
"""
import sqlalchemy as sa
from alembic import op

from app.db.types import GUID

# revision identifiers, used by Alembic.
revision = "f7a8b9c0d1e2"
down_revision = "e2f3a4b5c6d7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "restaurants",
        sa.Column("is_demo", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "restaurants",
        sa.Column(
            "demo_sends_via_restaurant_id",
            GUID(),
            sa.ForeignKey("restaurants.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    op.create_table(
        "demo_sessions",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("customer_phone", sa.String(length=30), nullable=False),
        sa.Column(
            "active_restaurant_id", GUID(), sa.ForeignKey("restaurants.id", ondelete="SET NULL"), nullable=True
        ),
        sa.UniqueConstraint("customer_phone", name="uq_demo_session_customer_phone"),
    )
    op.create_index("ix_demo_sessions_customer_phone", "demo_sessions", ["customer_phone"])


def downgrade() -> None:
    op.drop_table("demo_sessions")
    op.drop_column("restaurants", "demo_sends_via_restaurant_id")
    op.drop_column("restaurants", "is_demo")
