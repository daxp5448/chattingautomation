"""add whatsapp templates

Revision ID: a3b4c5d6e7f8
Revises: f7a8b9c0d1e2
Create Date: 2026-08-09

Additive only. New `whatsapp_templates` table (Phase 2 Item 1: WhatsApp Template Manager)
-- restaurant-scoped, no existing table is touched. See app/models/whatsapp_template.py.
"""
import sqlalchemy as sa
from alembic import op

from app.db.types import GUID

# revision identifiers, used by Alembic.
revision = "a3b4c5d6e7f8"
down_revision = "f7a8b9c0d1e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "whatsapp_templates",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("restaurant_id", GUID(), sa.ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=512), nullable=False),
        sa.Column("category", sa.String(length=20), nullable=False),
        sa.Column("language", sa.String(length=10), nullable=False),
        sa.Column("body_text", sa.String(length=1024), nullable=False),
        sa.Column("variable_examples", sa.JSON(), nullable=False),
        sa.Column("meta_template_id", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("rejection_reason", sa.String(length=1000), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("restaurant_id", "name", name="uq_whatsapp_template_restaurant_name"),
    )
    op.create_index("ix_whatsapp_templates_restaurant_id", "whatsapp_templates", ["restaurant_id"])


def downgrade() -> None:
    op.drop_table("whatsapp_templates")
