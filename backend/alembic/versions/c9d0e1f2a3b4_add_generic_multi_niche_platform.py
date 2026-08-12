"""add generic multi-niche platform tables

Revision ID: c9d0e1f2a3b4
Revises: b7c8d9e0f1a2
Create Date: 2026-08-07

Additive only -- no existing table/column is altered or dropped. This is deliberate: the
generic engine (app/services/generic_flow_engine.py) is a fully parallel system that
existing (legacy) businesses, including the live Prince Corner restaurant, never touch.
See that module's docstring and app/models/restaurant.py::uses_generic_engine.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.types import GUID

# revision identifiers, used by Alembic.
revision = "c9d0e1f2a3b4"
down_revision = "b7c8d9e0f1a2"
branch_labels = None
depends_on = None

# Created once explicitly and reused (create_type=False on every column below) rather
# than letting each `sa.Column(sa.Enum(...))` try to CREATE TYPE its own copy -- Postgres
# would reject the second/third attempt to create a type with a name that already
# exists. SQLite (the test suite's engine) ignores server-side enum types entirely, so
# this distinction only matters for the real Postgres path this migration actually runs against.
engagement_type_enum = postgresql.ENUM("ORDER", "INQUIRY", "APPOINTMENT", "BOOKING", name="engagementtype")
engagement_status_enum = postgresql.ENUM("NEW", "CONFIRMED", "IN_PROGRESS", "COMPLETED", "CANCELLED", name="engagementstatus")


def upgrade() -> None:
    bind = op.get_bind()
    engagement_type_enum.create(bind, checkfirst=True)
    engagement_status_enum.create(bind, checkfirst=True)

    op.add_column("restaurants", sa.Column("uses_generic_engine", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("restaurants", sa.Column("niche_type", sa.String(length=50), nullable=True))
    op.add_column("restaurants", sa.Column("staff_notification_number", sa.String(length=30), nullable=True))

    op.create_table(
        "niche_templates",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column(
            "action_type",
            postgresql.ENUM("ORDER", "INQUIRY", "APPOINTMENT", "BOOKING", name="engagementtype", create_type=False),
            nullable=False,
        ),
        sa.Column("icon", sa.String(length=10), nullable=True),
        sa.Column("welcome_message", sa.String(length=2000), nullable=False),
        sa.Column("welcome_banner_image", sa.String(length=1000), nullable=True),
        sa.Column("welcome_buttons", sa.JSON(), nullable=False),
        sa.Column("default_catalog", sa.JSON(), nullable=False),
        sa.Column("default_flow_steps", sa.JSON(), nullable=False),
        sa.Column("terminology", sa.JSON(), nullable=False),
        sa.Column("default_modules", sa.JSON(), nullable=False),
        sa.UniqueConstraint("code", name="uq_niche_template_code"),
    )
    op.create_index("ix_niche_templates_code", "niche_templates", ["code"])

    op.create_table(
        "catalog_categories",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("restaurant_id", GUID(), sa.ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column("visible", sa.Boolean(), nullable=False),
        sa.Column("image_url", sa.String(length=1000), nullable=True),
    )
    op.create_index("ix_catalog_categories_restaurant_id", "catalog_categories", ["restaurant_id"])

    op.create_table(
        "catalog_items",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("restaurant_id", GUID(), sa.ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("category_id", GUID(), sa.ForeignKey("catalog_categories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.String(length=2000), nullable=True),
        sa.Column("images", sa.JSON(), nullable=False),
        sa.Column("price", sa.Numeric(12, 2), nullable=True),
        sa.Column("price_type", sa.String(length=20), nullable=False),
        sa.Column("available", sa.Boolean(), nullable=False),
        sa.Column("is_featured", sa.Boolean(), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column("stock_quantity", sa.Integer(), nullable=True),
        sa.Column("attributes", sa.JSON(), nullable=False),
        sa.CheckConstraint("price IS NULL OR price >= 0", name="ck_catalog_item_price_non_negative"),
    )
    op.create_index("ix_catalog_items_restaurant_id", "catalog_items", ["restaurant_id"])
    op.create_index("ix_catalog_items_category_id", "catalog_items", ["category_id"])

    op.create_table(
        "staff_members",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("restaurant_id", GUID(), sa.ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("branch_id", GUID(), sa.ForeignKey("branches.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("photo_url", sa.String(length=1000), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("working_hours", sa.JSON(), nullable=False),
    )
    op.create_index("ix_staff_members_restaurant_id", "staff_members", ["restaurant_id"])
    op.create_index("ix_staff_members_branch_id", "staff_members", ["branch_id"])

    op.create_table(
        "engagements",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("restaurant_id", GUID(), sa.ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("branch_id", GUID(), sa.ForeignKey("branches.id", ondelete="SET NULL"), nullable=True),
        sa.Column("customer_id", GUID(), sa.ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("reference_number", sa.String(length=50), nullable=False),
        sa.Column(
            "type",
            postgresql.ENUM("ORDER", "INQUIRY", "APPOINTMENT", "BOOKING", name="engagementtype", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "status",
            postgresql.ENUM("NEW", "CONFIRMED", "IN_PROGRESS", "COMPLETED", "CANCELLED", name="engagementstatus", create_type=False),
            nullable=False,
        ),
        sa.Column("requires_payment", sa.Boolean(), nullable=False),
        sa.Column("payment_status", sa.String(length=20), nullable=False),
        sa.Column("payment_method", sa.String(length=20), nullable=True),
        sa.Column("gateway_metadata", sa.JSON(), nullable=False),
        sa.Column("subtotal", sa.Numeric(12, 2), nullable=False),
        sa.Column("tax", sa.Numeric(12, 2), nullable=False),
        sa.Column("discount", sa.Numeric(12, 2), nullable=False),
        sa.Column("total", sa.Numeric(12, 2), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.UniqueConstraint("reference_number", name="uq_engagement_reference_number"),
        sa.CheckConstraint("subtotal >= 0", name="ck_engagement_subtotal_non_negative"),
        sa.CheckConstraint("tax >= 0", name="ck_engagement_tax_non_negative"),
        sa.CheckConstraint("discount >= 0", name="ck_engagement_discount_non_negative"),
        sa.CheckConstraint("total >= 0", name="ck_engagement_total_non_negative"),
    )
    op.create_index("ix_engagements_restaurant_id", "engagements", ["restaurant_id"])
    op.create_index("ix_engagements_branch_id", "engagements", ["branch_id"])
    op.create_index("ix_engagements_customer_id", "engagements", ["customer_id"])
    op.create_index("ix_engagements_type", "engagements", ["type"])
    op.create_index("ix_engagements_status", "engagements", ["status"])
    op.create_index("ix_engagements_reference_number", "engagements", ["reference_number"])

    op.create_table(
        "engagement_items",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("engagement_id", GUID(), sa.ForeignKey("engagements.id", ondelete="CASCADE"), nullable=False),
        sa.Column("catalog_item_id", GUID(), sa.ForeignKey("catalog_items.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("name_snapshot", sa.String(length=200), nullable=False),
        sa.Column("price_snapshot", sa.Numeric(12, 2), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_engagement_item_quantity_positive"),
        sa.CheckConstraint("price_snapshot >= 0", name="ck_engagement_item_price_snapshot_non_negative"),
    )
    op.create_index("ix_engagement_items_engagement_id", "engagement_items", ["engagement_id"])

    op.create_table(
        "flow_definitions",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("restaurant_id", GUID(), sa.ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("niche_code", sa.String(), nullable=False),
        sa.Column(
            "action_type",
            postgresql.ENUM("ORDER", "INQUIRY", "APPOINTMENT", "BOOKING", name="engagementtype", create_type=False),
            nullable=False,
        ),
        sa.Column("entry_step_id", sa.String(), nullable=False),
        sa.Column("steps", sa.JSON(), nullable=False),
        sa.UniqueConstraint("restaurant_id", name="uq_flow_definition_restaurant"),
    )
    op.create_index("ix_flow_definitions_restaurant_id", "flow_definitions", ["restaurant_id"])

    op.create_table(
        "generic_conversation_states",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("restaurant_id", GUID(), sa.ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("customer_id", GUID(), sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("current_step", sa.String(), nullable=False),
        sa.Column("context", sa.JSON(), nullable=False),
        sa.Column("assigned_staff_id", GUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.UniqueConstraint("customer_id", name="uq_generic_conversation_state_customer"),
    )
    op.create_index("ix_generic_conversation_states_restaurant_id", "generic_conversation_states", ["restaurant_id"])


def downgrade() -> None:
    op.drop_table("generic_conversation_states")
    op.drop_table("flow_definitions")
    op.drop_table("engagement_items")
    op.drop_table("engagements")
    op.drop_table("staff_members")
    op.drop_table("catalog_items")
    op.drop_table("catalog_categories")
    op.drop_table("niche_templates")
    op.drop_column("restaurants", "staff_notification_number")
    op.drop_column("restaurants", "niche_type")
    op.drop_column("restaurants", "uses_generic_engine")
    op.execute("DROP TYPE IF EXISTS engagementtype")
    op.execute("DROP TYPE IF EXISTS engagementstatus")
