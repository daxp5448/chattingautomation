"""add idempotency and integrity constraints

Adds:
- messages.wa_message_id (nullable, unique, indexed) -- inbound WhatsApp webhook
  idempotency (app/services/flow_engine.py::process_inbound_message).
- uq_coupon_redemption_coupon_order on coupon_redemptions(coupon_id, order_id) -- DB-level
  backstop against double-redeeming a coupon for the same order.
- CHECK constraints on orders/order_items/products/coupons/customers so negative money
  amounts, non-positive quantities, and negative loyalty points can never be persisted,
  regardless of what application-layer validation does or doesn't catch.

Uses `op.batch_alter_table` throughout: on Postgres (the real deployment target) this is a
transparent passthrough to plain ALTER TABLE, but it's also what lets this same migration
run against SQLite (e.g. a local smoke-test DB), which has no ALTER-based support for
adding constraints at all and requires batch mode's copy-and-move strategy instead.

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-08-06 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- inbound WhatsApp message idempotency -------------------------------------------
    with op.batch_alter_table('messages') as batch_op:
        batch_op.add_column(sa.Column('wa_message_id', sa.String(length=255), nullable=True))
        batch_op.create_index(op.f('ix_messages_wa_message_id'), ['wa_message_id'], unique=True)

    # --- coupon redemption race backstop --------------------------------------------------
    with op.batch_alter_table('coupon_redemptions') as batch_op:
        batch_op.create_unique_constraint('uq_coupon_redemption_coupon_order', ['coupon_id', 'order_id'])

    # --- non-negative / positive value CHECK constraints ----------------------------------
    with op.batch_alter_table('orders') as batch_op:
        batch_op.create_check_constraint('ck_order_subtotal_non_negative', 'subtotal >= 0')
        batch_op.create_check_constraint('ck_order_tax_non_negative', 'tax >= 0')
        batch_op.create_check_constraint('ck_order_discount_non_negative', 'discount >= 0')
        batch_op.create_check_constraint('ck_order_delivery_charge_non_negative', 'delivery_charge >= 0')
        batch_op.create_check_constraint('ck_order_total_non_negative', 'total >= 0')

    with op.batch_alter_table('order_items') as batch_op:
        batch_op.create_check_constraint('ck_order_item_quantity_positive', 'quantity > 0')
        batch_op.create_check_constraint('ck_order_item_price_snapshot_non_negative', 'price_snapshot >= 0')

    with op.batch_alter_table('products') as batch_op:
        batch_op.create_check_constraint('ck_product_price_non_negative', 'price >= 0')
        batch_op.create_check_constraint(
            'ck_product_discount_price_non_negative', 'discount_price IS NULL OR discount_price >= 0'
        )
        batch_op.create_check_constraint(
            'ck_product_stock_quantity_non_negative', 'stock_quantity IS NULL OR stock_quantity >= 0'
        )

    with op.batch_alter_table('coupons') as batch_op:
        batch_op.create_check_constraint('ck_coupon_value_non_negative', 'value >= 0')

    with op.batch_alter_table('customers') as batch_op:
        batch_op.create_check_constraint('ck_customer_loyalty_points_non_negative', 'loyalty_points >= 0')


def downgrade() -> None:
    with op.batch_alter_table('customers') as batch_op:
        batch_op.drop_constraint('ck_customer_loyalty_points_non_negative', type_='check')

    with op.batch_alter_table('coupons') as batch_op:
        batch_op.drop_constraint('ck_coupon_value_non_negative', type_='check')

    with op.batch_alter_table('products') as batch_op:
        batch_op.drop_constraint('ck_product_stock_quantity_non_negative', type_='check')
        batch_op.drop_constraint('ck_product_discount_price_non_negative', type_='check')
        batch_op.drop_constraint('ck_product_price_non_negative', type_='check')

    with op.batch_alter_table('order_items') as batch_op:
        batch_op.drop_constraint('ck_order_item_price_snapshot_non_negative', type_='check')
        batch_op.drop_constraint('ck_order_item_quantity_positive', type_='check')

    with op.batch_alter_table('orders') as batch_op:
        batch_op.drop_constraint('ck_order_total_non_negative', type_='check')
        batch_op.drop_constraint('ck_order_delivery_charge_non_negative', type_='check')
        batch_op.drop_constraint('ck_order_discount_non_negative', type_='check')
        batch_op.drop_constraint('ck_order_tax_non_negative', type_='check')
        batch_op.drop_constraint('ck_order_subtotal_non_negative', type_='check')

    with op.batch_alter_table('coupon_redemptions') as batch_op:
        batch_op.drop_constraint('uq_coupon_redemption_coupon_order', type_='unique')

    with op.batch_alter_table('messages') as batch_op:
        batch_op.drop_index(op.f('ix_messages_wa_message_id'))
        batch_op.drop_column('wa_message_id')
