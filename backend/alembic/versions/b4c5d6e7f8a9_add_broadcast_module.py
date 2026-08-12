"""add broadcast module

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
Create Date: 2026-08-09

Additive only. Adds `marketing_opt_in` to `customers` and `broadcast_daily_cap` to
`restaurants` (both default/safe for every existing row), plus new `broadcast_campaigns`
and `broadcast_recipients` tables. See app/models/broadcast.py. Phase 2 Item 2.
"""
import sqlalchemy as sa
from alembic import op

from app.db.types import GUID

# revision identifiers, used by Alembic.
revision = "b4c5d6e7f8a9"
down_revision = "a3b4c5d6e7f8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "customers",
        sa.Column("marketing_opt_in", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "restaurants",
        sa.Column("broadcast_daily_cap", sa.Integer(), nullable=False, server_default="250"),
    )

    op.create_table(
        "broadcast_campaigns",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("restaurant_id", GUID(), sa.ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("template_id", GUID(), sa.ForeignKey("whatsapp_templates.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("segment_tags", sa.JSON(), nullable=False),
        sa.Column("variable_template", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_recipients", sa.Integer(), nullable=False),
        sa.Column("sent_count", sa.Integer(), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("failure_reason", sa.String(length=500), nullable=True),
    )
    op.create_index("ix_broadcast_campaigns_restaurant_id", "broadcast_campaigns", ["restaurant_id"])

    op.create_table(
        "broadcast_recipients",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("campaign_id", GUID(), sa.ForeignKey("broadcast_campaigns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("customer_id", GUID(), sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("error_reason", sa.String(length=500), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("campaign_id", "customer_id", name="uq_broadcast_recipient_campaign_customer"),
    )
    op.create_index("ix_broadcast_recipients_campaign_id", "broadcast_recipients", ["campaign_id"])
    op.create_index("ix_broadcast_recipients_customer_id", "broadcast_recipients", ["customer_id"])


def downgrade() -> None:
    op.drop_table("broadcast_recipients")
    op.drop_table("broadcast_campaigns")
    op.drop_column("restaurants", "broadcast_daily_cap")
    op.drop_column("customers", "marketing_opt_in")
