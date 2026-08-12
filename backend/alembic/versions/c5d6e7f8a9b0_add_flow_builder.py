"""add drag and drop flow builder

Revision ID: c5d6e7f8a9b0
Revises: b4c5d6e7f8a9
Create Date: 2026-08-10

Additive only. Adds `ui_layout` to `flow_definitions`, `default_ui_layout` to
`niche_templates`, `is_handed_over` to `generic_conversation_states` (all default/safe
for every existing row), plus a new Super-Admin-owned `api_endpoints` table. See
app/models/flow_definition.py, app/models/niche_template.py,
app/models/generic_conversation_state.py, app/models/api_endpoint.py. Phase 2 Item 3.

Adding the 5 new FlowStepType enum values needs no migration -- `steps`/`type` are
plain JSON/string columns, not a native DB enum type.
"""
import sqlalchemy as sa
from alembic import op

from app.db.types import GUID

# revision identifiers, used by Alembic.
revision = "c5d6e7f8a9b0"
down_revision = "b4c5d6e7f8a9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "flow_definitions",
        sa.Column("ui_layout", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "niche_templates",
        sa.Column("default_ui_layout", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "generic_conversation_states",
        sa.Column("is_handed_over", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    op.create_table(
        "api_endpoints",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("url", sa.String(length=2000), nullable=False),
        sa.Column("method", sa.String(length=10), nullable=False),
        sa.Column("allowed_headers", sa.JSON(), nullable=False),
        sa.Column("capturable_context_keys", sa.JSON(), nullable=False),
        sa.Column("timeout_seconds", sa.Float(), nullable=False),
        sa.Column("response_size_cap_bytes", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("api_endpoints")
    op.drop_column("generic_conversation_states", "is_handed_over")
    op.drop_column("niche_templates", "default_ui_layout")
    op.drop_column("flow_definitions", "ui_layout")
