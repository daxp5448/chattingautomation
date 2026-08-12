import uuid
from datetime import datetime

from sqlalchemy import case, func, select
from sqlalchemy.orm import selectinload

from app.models.enums import OrderStatus, PaymentStatus
from app.models.order import Order, OrderItem
from app.repositories.base import BaseRepository


class OrderRepository(BaseRepository[Order]):
    model = Order

    async def get_with_items(
        self, id_: uuid.UUID, restaurant_id: uuid.UUID, branch_id: uuid.UUID | None = None
    ) -> Order | None:
        stmt = (
            select(Order)
            .options(selectinload(Order.items), selectinload(Order.customer))
            .where(Order.id == id_, Order.restaurant_id == restaurant_id)
        )
        if branch_id is not None:
            # A branch-restricted cashier/kitchen account (see
            # app/core/deps.py::resolve_branch_scope) simply can't find another branch's
            # order through this query -- same as if it didn't exist, no separate 403 path
            # needed here.
            stmt = stmt.where(Order.branch_id == branch_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_with_items(
        self, restaurant_id: uuid.UUID, status: OrderStatus | None = None, branch_id: uuid.UUID | None = None
    ) -> list[Order]:
        stmt = (
            select(Order)
            .options(selectinload(Order.items), selectinload(Order.customer))
            .where(Order.restaurant_id == restaurant_id)
            .order_by(Order.created_at.desc())
        )
        if status is not None:
            stmt = stmt.where(Order.status == status)
        if branch_id is not None:
            stmt = stmt.where(Order.branch_id == branch_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def summary_by_restaurant(self) -> dict[uuid.UUID, dict]:
        """All-time order count + last-order timestamp per restaurant, in one query --
        used only by the super-admin restaurants list (app/api/v1/routers/restaurants.py)
        so "who's actually active" is visible without opening each restaurant in turn.
        """
        stmt = select(Order.restaurant_id, func.count(Order.id), func.max(Order.created_at)).group_by(
            Order.restaurant_id
        )
        result = await self.session.execute(stmt)
        return {row[0]: {"total_orders": row[1], "last_order_at": row[2]} for row in result.all()}

    async def dashboard_stats(self, restaurant_id: uuid.UUID, since: datetime) -> dict:
        # Portable (SQLite + Postgres) CASE-WHEN conditional aggregation collapses what
        # were ~6 sequential round trips into one -- avoiding Postgres-only FILTER syntax
        # so this still runs against the SQLite test DB. This also fixes a real bug: the
        # old `pending_stmt` never applied the `since` window at all (it counted *every*
        # pending order ever, not just ones in this reporting window); now every metric
        # shares the same single WHERE clause.
        not_cancelled = Order.status != OrderStatus.CANCELLED
        stats_stmt = select(
            func.count().label("total_orders"),
            # Gross order value: every non-cancelled order's total, regardless of whether
            # payment actually landed yet. Kept under the original "revenue" name for
            # backward compat with existing callers of dashboard_stats.
            func.coalesce(func.sum(case((not_cancelled, Order.total), else_=0)), 0).label("revenue"),
            # Actually collected: same non-cancelled orders, but only those whose payment
            # has been confirmed PAID. This is the figure that answers "how much money have
            # we actually taken in", which `revenue` alone cannot (e.g. an unpaid Razorpay
            # order counts toward `revenue` but not `paid_revenue`).
            func.coalesce(
                func.sum(case((not_cancelled & (Order.payment_status == PaymentStatus.PAID), Order.total), else_=0)), 0
            ).label("paid_revenue"),
            func.coalesce(func.sum(case((Order.status == OrderStatus.PENDING, 1), else_=0)), 0).label(
                "pending_orders"
            ),
            func.coalesce(func.sum(case((Order.status == OrderStatus.CANCELLED, 1), else_=0)), 0).label(
                "cancelled_orders"
            ),
            func.coalesce(func.sum(case((Order.status == OrderStatus.COMPLETED, 1), else_=0)), 0).label(
                "completed_orders"
            ),
            # No `else_`: CASE falls through to NULL for cancelled rows, and avg() ignores
            # NULLs on both backends -- same "average over non-cancelled orders" semantics
            # as the original separate query, computed in the same pass.
            func.coalesce(func.avg(case((not_cancelled, Order.total))), 0).label("average_order_value"),
        ).where(Order.restaurant_id == restaurant_id, Order.created_at >= since)

        row = (await self.session.execute(stats_stmt)).one()
        total_orders = row.total_orders
        revenue = row.revenue
        paid_revenue = row.paid_revenue
        pending = row.pending_orders
        cancelled = row.cancelled_orders
        completed = row.completed_orders
        avg_order_value = row.average_order_value

        top_item_stmt = (
            select(OrderItem.name_snapshot, func.sum(OrderItem.quantity).label("qty"))
            .join(Order, Order.id == OrderItem.order_id)
            .where(Order.restaurant_id == restaurant_id, Order.created_at >= since)
            .group_by(OrderItem.name_snapshot)
            .order_by(func.sum(OrderItem.quantity).desc())
            .limit(1)
        )
        top_item_row = (await self.session.execute(top_item_stmt)).first()

        return {
            "total_orders": total_orders,
            "revenue": float(revenue),
            "paid_revenue": float(paid_revenue),
            "pending_orders": pending,
            "cancelled_orders": cancelled,
            "completed_orders": completed,
            "average_order_value": float(avg_order_value),
            "most_ordered_item": top_item_row[0] if top_item_row else None,
        }
