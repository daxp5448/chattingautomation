"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import { useLiveSocket } from "@/lib/useLiveSocket";
import type { PosOrder } from "@/lib/types";

// Deliberately NOT importing apiFetch from lib/api.ts: that helper attaches the staff
// bearer token from localStorage, which never exists on this unauthenticated,
// no-login POS/kitchen-display route. Auth here is a single raw token read from the
// URL and sent as a query param on every request instead.
const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000/api/v1";

const COLUMNS: { status: PosOrder["status"][]; label: string }[] = [
  { status: ["pending", "accepted"], label: "Pending" },
  { status: ["preparing"], label: "Preparing" },
  { status: ["ready"], label: "Ready" },
];

function useNow(intervalMs: number): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}

function elapsedLabel(createdAt: string, now: number): string {
  const minutes = Math.max(0, Math.floor((now - new Date(createdAt).getTime()) / 60000));
  if (minutes < 1) return "just now";
  if (minutes === 1) return "1 min ago";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  const rem = minutes % 60;
  return `${hours}h ${rem}m ago`;
}

function OrderCard({ order, now }: { order: PosOrder; now: number }) {
  return (
    <div className="rounded-2xl border-2 border-slate-700 bg-slate-800 p-5 shadow-lg">
      <div className="flex items-baseline justify-between">
        <span className="text-3xl font-bold text-white">#{order.order_number}</span>
        <span className="rounded-full bg-slate-700 px-3 py-1 text-sm font-medium text-slate-200">
          {order.fulfillment_type === "pickup" ? "Pickup" : "Delivery"}
        </span>
      </div>
      <p className="mt-1 text-lg font-medium text-amber-400">{elapsedLabel(order.created_at, now)}</p>
      <ul className="mt-4 space-y-1.5">
        {order.items.map((item, idx) => (
          <li key={idx} className="flex items-baseline gap-2 text-xl text-slate-100">
            <span className="font-bold text-emerald-400">{item.quantity}x</span>
            <span>{item.name_snapshot}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function DisplayBoard({ restaurantId, token }: { restaurantId: string; token: string }) {
  const [orders, setOrders] = useState<PosOrder[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const now = useNow(15000);

  const load = useCallback(async () => {
    try {
      const response = await fetch(
        `${API_BASE_URL}/pos/${restaurantId}/orders?token=${encodeURIComponent(token)}`
      );
      if (!response.ok) {
        if (response.status === 401) {
          setError("invalid");
        } else {
          setError("network");
        }
        return;
      }
      const data = (await response.json()) as PosOrder[];
      setOrders(data);
      setError(null);
    } catch {
      setError("network");
    }
  }, [restaurantId, token]);

  useEffect(() => {
    load();
    const poll = setInterval(load, 30000);
    return () => clearInterval(poll);
  }, [load]);

  useLiveSocket(
    restaurantId,
    (event) => {
      if (event.type === "order_created" || event.type === "order_status_changed" || event.type === "payment_success") {
        load();
      }
    },
    { deviceToken: token }
  );

  if (error === "invalid") {
    return (
      <div className="flex h-screen flex-col items-center justify-center bg-slate-900 px-8 text-center">
        <p className="text-3xl font-semibold text-white">This display link is invalid or has been revoked</p>
        <p className="mt-3 text-lg text-slate-400">Ask the restaurant owner for a new one from their dashboard.</p>
      </div>
    );
  }

  if (orders === null) {
    return (
      <div className="flex h-screen items-center justify-center bg-slate-900">
        <p className="text-xl text-slate-400">Loading orders...</p>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-900 p-6">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-bold text-white">Live Orders</h1>
        <span className="flex items-center gap-2 rounded-full bg-emerald-900/40 px-4 py-1.5 text-sm font-medium text-emerald-400">
          <span className="h-2 w-2 rounded-full bg-emerald-400" /> Live
        </span>
      </div>
      {error === "network" && (
        <p className="mb-4 rounded-lg bg-red-900/40 px-4 py-2 text-sm text-red-300">
          Having trouble reaching the server -- still showing the last known orders.
        </p>
      )}
      <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
        {COLUMNS.map((col) => {
          const columnOrders = orders
            .filter((o) => col.status.includes(o.status))
            .sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime());
          return (
            <div key={col.label} className="rounded-2xl bg-slate-800/40 p-4">
              <h2 className="mb-4 text-xl font-bold uppercase tracking-wide text-slate-300">
                {col.label} <span className="text-slate-500">({columnOrders.length})</span>
              </h2>
              <div className="space-y-4">
                {columnOrders.map((order) => (
                  <OrderCard key={order.id} order={order} now={now} />
                ))}
                {columnOrders.length === 0 && <p className="text-sm text-slate-600">No orders</p>}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default function PosDisplayPage() {
  const params = useParams<{ restaurantId: string }>();
  const searchParams = useSearchParams();
  const token = searchParams.get("token");
  const restaurantId = params.restaurantId;

  if (!token) {
    return (
      <div className="flex h-screen flex-col items-center justify-center bg-slate-900 px-8 text-center">
        <p className="text-3xl font-semibold text-white">This display link is invalid or has been revoked</p>
        <p className="mt-3 text-lg text-slate-400">Ask the restaurant owner for a new one from their dashboard.</p>
      </div>
    );
  }

  return <DisplayBoard restaurantId={restaurantId} token={token} />;
}
