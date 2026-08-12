"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch, ApiError } from "@/lib/api";
import { RequireRestaurant } from "@/components/RequireRestaurant";
import { useLiveSocket } from "@/lib/useLiveSocket";
import type { Order } from "@/lib/types";

const STATUS_FLOW: Record<Order["status"], Order["status"] | null> = {
  pending: "accepted",
  accepted: "preparing",
  preparing: "ready",
  ready: "completed",
  completed: null,
  cancelled: null,
  refunded: null,
};

const STATUS_COLORS: Record<string, string> = {
  pending: "bg-amber-100 text-amber-700",
  accepted: "bg-blue-100 text-blue-700",
  preparing: "bg-indigo-100 text-indigo-700",
  ready: "bg-purple-100 text-purple-700",
  completed: "bg-emerald-100 text-emerald-700",
  cancelled: "bg-red-100 text-red-700",
  refunded: "bg-slate-100 text-slate-600",
};

function OrdersForRestaurant({ restaurantId }: { restaurantId: string }) {
  const [orders, setOrders] = useState<Order[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const data = await apiFetch<Order[]>(`/restaurants/${restaurantId}/orders`);
      setOrders(data);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load orders");
    } finally {
      setLoading(false);
    }
  }, [restaurantId]);

  useEffect(() => {
    load();
  }, [load]);

  useLiveSocket(restaurantId, (event) => {
    if (event.type === "order_created" || event.type === "order_status_changed" || event.type === "payment_success") {
      load();
    }
  });

  async function advance(order: Order) {
    const next = STATUS_FLOW[order.status];
    if (!next) return;
    try {
      await apiFetch(`/restaurants/${restaurantId}/orders/${order.id}/status`, {
        method: "PATCH",
        body: JSON.stringify({ status: next }),
      });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to update order");
    }
  }

  async function cancel(order: Order) {
    try {
      await apiFetch(`/restaurants/${restaurantId}/orders/${order.id}/status`, {
        method: "PATCH",
        body: JSON.stringify({ status: "cancelled" }),
      });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to cancel order");
    }
  }

  async function refund(order: Order) {
    if (!window.confirm(`Refund order #${order.order_number}? This will process a real refund through Razorpay and cannot be undone.`)) {
      return;
    }
    try {
      await apiFetch(`/orders/${order.id}/refund`, { method: "POST" });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to refund order");
    }
  }

  if (loading) {
    return (
      <div className="flex items-center gap-3 text-sm text-slate-500">
        <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-primary" />
        Loading orders...
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Live Orders</h1>
          <p className="text-sm text-slate-500">Updates instantly as customers order on WhatsApp.</p>
        </div>
        <span className="flex items-center gap-1.5 rounded-full bg-emerald-50 px-3 py-1 text-xs font-medium text-emerald-600">
          <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" /> Live
        </span>
      </div>
      {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

      <div className="space-y-3">
        {orders.map((order) => {
          const next = STATUS_FLOW[order.status];
          return (
            <div key={order.id} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <div className="flex items-start justify-between">
                <div>
                  <p className="font-medium text-slate-800">
                    🧾 {order.order_number}{" "}
                    <span className="ml-1 rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-500">
                      {order.fulfillment_type === "pickup" ? "🏪 Pickup" : "🚚 Delivery"}
                    </span>
                  </p>
                  <p className="text-xs text-slate-400">{new Date(order.created_at).toLocaleString()}</p>
                  <p className="mt-1 text-xs text-slate-500">
                    👤 {order.customer_name || "Unknown"} · {order.customer_phone}
                  </p>
                  {order.fulfillment_type === "delivery" && order.delivery_address?.address && (
                    <p className="mt-0.5 text-xs text-slate-500">📍 {order.delivery_address.address}</p>
                  )}
                  {order.notes && <p className="mt-0.5 text-xs italic text-slate-500">📝 {order.notes}</p>}
                </div>
                <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${STATUS_COLORS[order.status]}`}>{order.status}</span>
              </div>

              <ul className="mt-2 space-y-0.5 text-sm text-slate-600">
                {order.items.map((item) => (
                  <li key={item.id}>
                    {item.quantity} x {item.name_snapshot}
                  </li>
                ))}
              </ul>

              <div className="mt-3 flex items-center justify-between border-t border-slate-100 pt-3">
                <div className="text-sm">
                  <p className="font-medium text-slate-800">
                    Total: {order.total} {order.discount > 0 && <span className="text-xs text-emerald-600">(-{order.discount} coupon/points)</span>}
                  </p>
                  <p className="text-xs text-slate-400">Payment: {order.payment_method} ({order.payment_status})</p>
                </div>
                <div className="flex items-center gap-2">
                  {order.invoice_url && (
                    <a href={order.invoice_url} target="_blank" rel="noreferrer" className="rounded-md border border-slate-300 px-3 py-1 text-xs font-medium text-slate-700 hover:bg-slate-50">
                      📄 Invoice
                    </a>
                  )}
                  {next && (
                    <button onClick={() => advance(order)} className="rounded-md bg-primary px-3 py-1 text-xs font-medium text-white shadow-sm">
                      Mark {next}
                    </button>
                  )}
                  {order.payment_status === "paid" && (
                    <button onClick={() => refund(order)} className="rounded-md border border-red-300 px-3 py-1 text-xs font-medium text-red-600 hover:bg-red-50">
                      Refund
                    </button>
                  )}
                  {order.status !== "cancelled" && order.status !== "completed" && (
                    <button onClick={() => cancel(order)} className="rounded-md border border-red-300 px-3 py-1 text-xs font-medium text-red-600 hover:bg-red-50">
                      Cancel
                    </button>
                  )}
                </div>
              </div>
            </div>
          );
        })}
        {orders.length === 0 && (
          <p className="rounded-xl border border-dashed border-slate-300 p-8 text-center text-sm text-slate-400">
            No orders yet — they&apos;ll show up here the moment a customer checks out on WhatsApp.
          </p>
        )}
      </div>
    </div>
  );
}

export default function OrdersPage() {
  return <RequireRestaurant>{(restaurantId) => <OrdersForRestaurant restaurantId={restaurantId} />}</RequireRestaurant>;
}
