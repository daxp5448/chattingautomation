"""add catalog_category_id and flow_definition_id/flow_step_id image owners

Revision ID: 8b9c0d1e2f3a
Revises: 7f8a9b0c1d2e
Create Date: 2026-08-15

Additive only. Extends the Universal Image Processing Pipeline (see
app/models/image.py's docstring) with two more owner shapes, following the exact
same "one more nullable FK column + widen the owner-count CheckConstraint" pattern
catalog_item_id already used -- so images can attach to a catalog category (a
category's own gallery, not just its items') or to a specific flow step (a welcome
banner, a gallery step) instead of only ever being sourced from a catalog item or a
restaurant-level cover/logo fallback. `flow_step_id` has no FK: flow steps are JSON
entries inside FlowDefinition.steps, not rows of their own, so it's a plain string
matched against a step's `step_id` at read time, always paired with flow_definition_id.

The existing `ck_image_has_owner` CheckConstraint required `catalog_item_id IS NOT
NULL`. This migration widens it to require exactly one of the three owner shapes.

Postgres: a plain batch ALTER (no table rebuild needed there, so this is exactly as
cheap/safe as any other additive migration in this project).

SQLite: dropping/adding a CHECK constraint has no direct ALTER TABLE equivalent --
SQLite always requires a full table rebuild (rename, create the new shape, copy rows,
drop the old one). Done by hand with raw SQL here rather than via
`op.batch_alter_table`, because this project's tables were never given an explicit
`naming_convention` (see app/db/base.py) -- every real dev/prod SQLite file, since this
project builds schema via `Base.metadata.create_all()` rather than migrations, ends up
with UNNAMED foreign key constraints. Alembic's batch mode has to copy those unnamed
constraints across during the rebuild and raises "Constraint must have a name" trying
to do so (confirmed against a real dev.db in this environment; passing
`naming_convention=` to `batch_alter_table` did not resolve it against the installed
alembic==1.13.2). Rows and FKs are copied through unchanged; only the CHECK constraint
and 3 new nullable columns actually change.
"""
import sqlalchemy as sa
from alembic import op

from app.db.types import GUID

# revision identifiers, used by Alembic.
revision = "8b9c0d1e2f3a"
down_revision = "7f8a9b0c1d2e"
branch_labels = None
depends_on = None

_NEW_CONSTRAINT = (
    "(CASE WHEN catalog_item_id IS NOT NULL THEN 1 ELSE 0 END + "
    "CASE WHEN catalog_category_id IS NOT NULL THEN 1 ELSE 0 END + "
    "CASE WHEN flow_definition_id IS NOT NULL AND flow_step_id IS NOT NULL THEN 1 ELSE 0 END) = 1"
)
_OLD_CONSTRAINT = "catalog_item_id IS NOT NULL"

_SQLITE_COMMON_COLUMNS = (
    "restaurant_id, image_type, catalog_item_id, original_key, original_format, "
    "original_width, original_height, original_size_bytes, variants, status, "
    "failure_reason, crop_box, resolution_warning, low_quality_reason, "
    "replaced_by_image_id, deleted_at, caption, alt_text, display_order, is_active, "
    "id, created_at, updated_at"
)


def _sqlite_rebuild(new_check_expr: str, include_new_columns: bool) -> None:
    op.execute("ALTER TABLE images RENAME TO images_old")
    new_columns_sql = (
        """
        catalog_category_id CHAR(32),
        flow_definition_id CHAR(32),
        flow_step_id VARCHAR(100),
        """
        if include_new_columns
        else ""
    )
    fk_new_columns_sql = (
        """
        FOREIGN KEY(catalog_category_id) REFERENCES catalog_categories (id) ON DELETE CASCADE,
        FOREIGN KEY(flow_definition_id) REFERENCES flow_definitions (id) ON DELETE CASCADE,
        """
        if include_new_columns
        else ""
    )
    select_columns = _SQLITE_COMMON_COLUMNS
    insert_columns = _SQLITE_COMMON_COLUMNS
    if include_new_columns:
        insert_columns += ", catalog_category_id, flow_definition_id, flow_step_id"
        select_columns += ", NULL, NULL, NULL"
    op.execute(
        f"""
        CREATE TABLE images (
            restaurant_id CHAR(32) NOT NULL,
            image_type VARCHAR(50) NOT NULL,
            catalog_item_id CHAR(32),
            {new_columns_sql}
            original_key VARCHAR(500) NOT NULL,
            original_format VARCHAR(20) NOT NULL,
            original_width INTEGER NOT NULL,
            original_height INTEGER NOT NULL,
            original_size_bytes INTEGER NOT NULL,
            variants JSON NOT NULL,
            status VARCHAR(20) NOT NULL,
            failure_reason VARCHAR(500),
            crop_box JSON,
            resolution_warning BOOLEAN NOT NULL,
            low_quality_reason VARCHAR(100),
            replaced_by_image_id CHAR(32),
            deleted_at DATETIME,
            caption VARCHAR(1024),
            alt_text VARCHAR(300),
            display_order INTEGER NOT NULL,
            is_active BOOLEAN NOT NULL,
            id CHAR(32) NOT NULL,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL,
            PRIMARY KEY (id),
            CONSTRAINT ck_image_has_owner CHECK ({new_check_expr}),
            FOREIGN KEY(restaurant_id) REFERENCES restaurants (id) ON DELETE CASCADE,
            FOREIGN KEY(catalog_item_id) REFERENCES catalog_items (id) ON DELETE CASCADE,
            {fk_new_columns_sql}
            FOREIGN KEY(replaced_by_image_id) REFERENCES images (id) ON DELETE SET NULL
        )
        """
    )
    op.execute(f"INSERT INTO images ({insert_columns}) SELECT {select_columns} FROM images_old")
    op.execute("DROP TABLE images_old")


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        _sqlite_rebuild(_NEW_CONSTRAINT, include_new_columns=True)
    else:
        with op.batch_alter_table("images") as batch_op:
            batch_op.drop_constraint("ck_image_has_owner", type_="check")
            batch_op.add_column(
                sa.Column(
                    "catalog_category_id",
                    GUID(),
                    sa.ForeignKey("catalog_categories.id", ondelete="CASCADE"),
                    nullable=True,
                )
            )
            batch_op.add_column(
                sa.Column(
                    "flow_definition_id",
                    GUID(),
                    sa.ForeignKey("flow_definitions.id", ondelete="CASCADE"),
                    nullable=True,
                )
            )
            batch_op.add_column(sa.Column("flow_step_id", sa.String(length=100), nullable=True))
            batch_op.create_check_constraint("ck_image_has_owner", _NEW_CONSTRAINT)

    op.create_index("ix_images_catalog_category_id", "images", ["catalog_category_id"])
    op.create_index("ix_images_flow_definition_id", "images", ["flow_definition_id"])
    op.create_index("ix_images_flow_step_id", "images", ["flow_step_id"])


def downgrade() -> None:
    op.drop_index("ix_images_flow_step_id", table_name="images")
    op.drop_index("ix_images_flow_definition_id", table_name="images")
    op.drop_index("ix_images_catalog_category_id", table_name="images")

    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        _sqlite_rebuild(_OLD_CONSTRAINT, include_new_columns=False)
    else:
        with op.batch_alter_table("images") as batch_op:
            batch_op.drop_constraint("ck_image_has_owner", type_="check")
            batch_op.drop_column("flow_step_id")
            batch_op.drop_column("flow_definition_id")
            batch_op.drop_column("catalog_category_id")
            batch_op.create_check_constraint("ck_image_has_owner", _OLD_CONSTRAINT)
