"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch, ApiError } from "@/lib/api";
import { RequireRestaurant } from "@/components/RequireRestaurant";
import { useCurrentRestaurant } from "@/lib/restaurant";
import { useLiveSocket } from "@/lib/useLiveSocket";
import type { ComponentType } from "react";
import type { Engagement, Order, Restaurant } from "@/lib/types";
import { type IconProps, IconReceipt, IconStore, IconTruck, IconUser, IconMapPin, IconFileText, IconMail, IconCalendar, IconBed } from "@/components/icons";

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
                  <p className="flex items-center gap-1.5 font-medium text-slate-800">
                    <IconReceipt size={13} className="text-slate-400" /> {order.order_number}{" "}
                    <span className="ml-1 inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-500">
                      {order.fulfillment_type === "pickup" ? (
                        <>
                          <IconStore size={11} /> Pickup
                        </>
                      ) : (
                        <>
                          <IconTruck size={11} /> Delivery
                        </>
                      )}
                    </span>
                  </p>
                  <p className="text-xs text-slate-400">{new Date(order.created_at).toLocaleString()}</p>
                  <p className="mt-1 flex items-center gap-1.5 text-xs text-slate-500">
                    <IconUser size={12} className="text-slate-400" /> {order.customer_name || "Unknown"} · {order.customer_phone}
                  </p>
                  {order.fulfillment_type === "delivery" && order.delivery_address?.address && (
                    <p className="mt-0.5 flex items-center gap-1.5 text-xs text-slate-500">
                      <IconMapPin size={12} className="text-slate-400" /> {order.delivery_address.address}
                    </p>
                  )}
                  {order.notes && (
                    <p className="mt-0.5 flex items-center gap-1.5 text-xs italic text-slate-500">
                      <IconFileText size={12} className="text-slate-400" /> {order.notes}
                    </p>
                  )}
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
                    <a href={order.invoice_url} target="_blank" rel="noreferrer" className="flex items-center gap-1.5 rounded-md border border-slate-300 px-3 py-1 text-xs font-medium text-slate-700 hover:bg-slate-50">
                      <IconFileText size={12} /> Invoice
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

// --- Generic engine: Orders/Bookings/Appointments/Leads (Engagement) ----------------------

const ENGAGEMENT_STATUS_FLOW: Record<Engagement["status"], Engagement["status"] | null> = {
  new: "confirmed",
  confirmed: "in_progress",
  in_progress: "completed",
  completed: null,
  cancelled: null,
};

const ENGAGEMENT_STATUS_LABELS: Record<Engagement["status"], string> = {
  new: "New",
  confirmed: "Confirmed",
  in_progress: "In Progress",
  completed: "Completed",
  cancelled: "Cancelled",
};

const ENGAGEMENT_STATUS_COLORS: Record<string, string> = {
  new: "bg-amber-100 text-amber-700",
  confirmed: "bg-blue-100 text-blue-700",
  in_progress: "bg-indigo-100 text-indigo-700",
  completed: "bg-emerald-100 text-emerald-700",
  cancelled: "bg-red-100 text-red-700",
};

const TYPE_LABELS: Record<Engagement["type"], string> = {
  order: "Order",
  inquiry: "Lead",
  appointment: "Appointment",
  booking: "Booking",
};

const TYPE_ICONS: Record<Engagement["type"], ComponentType<IconProps>> = {
  order: IconReceipt,
  inquiry: IconMail,
  appointment: IconCalendar,
  booking: IconBed,
};

function _detailLabel(key: string): string {
  return key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function GenericEngagementsForRestaurant({ restaurantId }: { restaurantId: string }) {
  const { nicheTerminology } = useCurrentRestaurant();
  const [engagements, setEngagements] = useState<Engagement[]>([]);
  const [typeFilter, setTypeFilter] = useState<Engagement["type"] | "all">("all");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const catalogNoun = (nicheTerminology?.item_label as string | undefined) || "item";

  const load = useCallback(async () => {
    try {
      const query = typeFilter === "all" ? "" : `?type_filter=${typeFilter}`;
      const data = await apiFetch<Engagement[]>(`/restaurants/${restaurantId}/engagements${query}`);
      setEngagements(data);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [restaurantId, typeFilter]);

  useEffect(() => {
    load();
  }, [load]);

  useLiveSocket(restaurantId, (event) => {
    if (event.type === "engagement_created" || event.type === "engagement_status_changed") {
      load();
    }
  });

  async function updateStatus(engagement: Engagement, next: Engagement["status"]) {
    try {
      await apiFetch(`/restaurants/${restaurantId}/engagements/${engagement.id}/status`, {
        method: "PATCH",
        body: JSON.stringify({ status: next }),
      });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to update status");
    }
  }

  const presentTypes = Array.from(new Set(engagements.map((e) => e.type)));

  if (loading) {
    return (
      <div className="flex items-center gap-3 text-sm text-slate-500">
        <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-primary" />
        Loading...
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Orders / Bookings / Appointments / Leads</h1>
          <p className="text-sm text-slate-500">Updates instantly as customers complete their journey on WhatsApp.</p>
        </div>
        <span className="flex items-center gap-1.5 rounded-full bg-emerald-50 px-3 py-1 text-xs font-medium text-emerald-600">
          <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" /> Live
        </span>
      </div>
      {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

      {presentTypes.length > 1 && (
        <div className="flex flex-wrap gap-1.5">
          <button
            onClick={() => setTypeFilter("all")}
            className={`rounded-full px-3 py-1 text-xs font-medium ${typeFilter === "all" ? "bg-primary text-white" : "bg-slate-100 text-slate-600"}`}
          >
            All
          </button>
          {presentTypes.map((t) => (
            <button
              key={t}
              onClick={() => setTypeFilter(t)}
              className={`rounded-full px-3 py-1 text-xs font-medium ${typeFilter === t ? "bg-primary text-white" : "bg-slate-100 text-slate-600"}`}
            >
              <span className="inline-flex items-center gap-1">
                {(() => {
                  const TIcon = TYPE_ICONS[t];
                  return <TIcon size={11} />;
                })()}
                {TYPE_LABELS[t]}
              </span>
            </button>
          ))}
        </div>
      )}

      <div className="space-y-3">
        {engagements.map((engagement) => {
          const next = ENGAGEMENT_STATUS_FLOW[engagement.status];
          const detailEntries = Object.entries(engagement.details || {}).filter(([, v]) => v !== null && v !== "");
          return (
            <div key={engagement.id} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <div className="flex items-start justify-between">
                <div>
                  <p className="flex items-center gap-1.5 font-medium text-slate-800">
                    {(() => {
                      const TIcon = TYPE_ICONS[engagement.type];
                      return <TIcon size={13} className="text-slate-400" />;
                    })()}
                    {engagement.reference_number}{" "}
                    <span className="ml-1 rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-500">
                      {TYPE_LABELS[engagement.type]}
                    </span>
                  </p>
                  <p className="text-xs text-slate-400">{new Date(engagement.created_at).toLocaleString()}</p>
                  <p className="mt-1 flex items-center gap-1.5 text-xs text-slate-500">
                    <IconUser size={12} className="text-slate-400" /> {engagement.customer_name || "Unknown"} · {engagement.customer_phone}
                  </p>
                </div>
                <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${ENGAGEMENT_STATUS_COLORS[engagement.status]}`}>
                  {ENGAGEMENT_STATUS_LABELS[engagement.status]}
                </span>
              </div>

              {engagement.type === "order" && engagement.items.length > 0 && (
                <ul className="mt-2 space-y-0.5 text-sm text-slate-600">
                  {engagement.items.map((item) => (
                    <li key={item.id}>
                      {item.quantity} x {item.name_snapshot}
                    </li>
                  ))}
                </ul>
              )}

              {engagement.type !== "order" && detailEntries.length > 0 && (
                <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-0.5 text-xs text-slate-600 sm:grid-cols-3">
                  {detailEntries.map(([key, value]) => (
                    <div key={key}>
                      <dt className="text-slate-400">{_detailLabel(key)}</dt>
                      <dd className="font-medium text-slate-700">{String(value)}</dd>
                    </div>
                  ))}
                </dl>
              )}

              <div className="mt-3 flex items-center justify-between border-t border-slate-100 pt-3">
                <div className="text-sm">
                  {engagement.type === "order" && (
                    <p className="font-medium text-slate-800">
                      Total: {engagement.total}
                      {engagement.discount > 0 && <span className="ml-1 text-xs text-emerald-600">(-{engagement.discount})</span>}
                    </p>
                  )}
                  {engagement.requires_payment && (
                    <p className="text-xs text-slate-400">Payment: {engagement.payment_method || "-"} ({engagement.payment_status})</p>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  {next && (
                    <button onClick={() => updateStatus(engagement, next)} className="rounded-md bg-primary px-3 py-1 text-xs font-medium text-white shadow-sm">
                      Mark {ENGAGEMENT_STATUS_LABELS[next]}
                    </button>
                  )}
                  {engagement.status !== "cancelled" && engagement.status !== "completed" && (
                    <button onClick={() => updateStatus(engagement, "cancelled")} className="rounded-md border border-red-300 px-3 py-1 text-xs font-medium text-red-600 hover:bg-red-50">
                      Cancel
                    </button>
                  )}
                </div>
              </div>
            </div>
          );
        })}
        {engagements.length === 0 && (
          <p className="rounded-xl border border-dashed border-slate-300 p-8 text-center text-sm text-slate-400">
            Nothing yet — {catalogNoun} orders, bookings, appointments, and leads will show up here the moment a customer completes the
            WhatsApp flow.
          </p>
        )}
      </div>
    </div>
  );
}

// --- Router: legacy Order table vs generic Engagement, same split menu/page.tsx and
// messages/page.tsx already use (a business's real activity lives in one storage or the
// other depending on Restaurant.uses_generic_engine, never both). ------------------------

function OrdersRouter({ restaurantId }: { restaurantId: string }) {
  const [usesGenericEngine, setUsesGenericEngine] = useState<boolean | null>(null);

  useEffect(() => {
    apiFetch<Restaurant>(`/restaurants/${restaurantId}`)
      .then((r) => setUsesGenericEngine(r.uses_generic_engine))
      .catch(() => setUsesGenericEngine(false));
  }, [restaurantId]);

  if (usesGenericEngine === null) {
    return (
      <div className="flex items-center gap-3 text-sm text-slate-500">
        <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-primary" />
        Loading...
      </div>
    );
  }

  return usesGenericEngine ? (
    <GenericEngagementsForRestaurant restaurantId={restaurantId} />
  ) : (
    <OrdersForRestaurant restaurantId={restaurantId} />
  );
}

export default function OrdersPage() {
  return <RequireRestaurant>{(restaurantId) => <OrdersRouter restaurantId={restaurantId} />}</RequireRestaurant>;
}
