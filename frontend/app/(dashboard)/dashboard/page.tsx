"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch, ApiError } from "@/lib/api";
import { RequireRestaurant } from "@/components/RequireRestaurant";
import { useLiveSocket } from "@/lib/useLiveSocket";
import type { DashboardStats } from "@/lib/types";

const TILES: { key: keyof DashboardStats; label: string; icon: string; accent: string; format?: (v: number) => string }[] = [
  { key: "total_orders", label: "Today's Orders", icon: "🧾", accent: "bg-blue-50 text-blue-600" },
  { key: "revenue", label: "Today's Revenue", icon: "💰", accent: "bg-emerald-50 text-emerald-600", format: (v) => v.toFixed(2) },
  { key: "pending_orders", label: "Pending Orders", icon: "⏳", accent: "bg-amber-50 text-amber-600" },
  { key: "cancelled_orders", label: "Cancelled Orders", icon: "🚫", accent: "bg-red-50 text-red-600" },
  { key: "completed_orders", label: "Completed Orders", icon: "✅", accent: "bg-emerald-50 text-emerald-600" },
  { key: "total_customers", label: "Total Customers", icon: "👥", accent: "bg-violet-50 text-violet-600" },
  { key: "average_order_value", label: "Average Order Value", icon: "📈", accent: "bg-blue-50 text-blue-600", format: (v) => v.toFixed(2) },
];

function DashboardForRestaurant({ restaurantId }: { restaurantId: string }) {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setStats(await apiFetch<DashboardStats>(`/restaurants/${restaurantId}/dashboard/stats`));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load dashboard stats");
    }
  }, [restaurantId]);

  useEffect(() => {
    load();
  }, [load]);

  useLiveSocket(restaurantId, () => load());

  if (error) return <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>;
  if (!stats) {
    return (
      <div className="flex items-center gap-3 text-sm text-slate-500">
        <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-primary" />
        Loading dashboard...
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Dashboard</h1>
        <p className="text-sm text-slate-500">Live snapshot of today&apos;s activity — updates automatically as orders come in.</p>
      </div>
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
        {TILES.map(({ key, label, icon, accent, format }) => {
          const raw = stats[key];
          const value = typeof raw === "number" ? (format ? format(raw) : raw) : raw ?? "-";
          return (
            <div key={key} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <div className={`mb-2 flex h-9 w-9 items-center justify-center rounded-lg text-lg ${accent}`}>{icon}</div>
              <p className="text-xs font-medium uppercase tracking-wide text-slate-400">{label}</p>
              <p className="mt-1 text-2xl font-semibold text-slate-900">{value}</p>
            </div>
          );
        })}
        <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <div className="mb-2 flex h-9 w-9 items-center justify-center rounded-lg bg-orange-50 text-lg text-orange-600">🍕</div>
          <p className="text-xs font-medium uppercase tracking-wide text-slate-400">Most Ordered Item</p>
          <p className="mt-1 text-2xl font-semibold text-slate-900">{stats.most_ordered_item || "-"}</p>
        </div>
      </div>
    </div>
  );
}

export default function DashboardPage() {
  return <RequireRestaurant>{(restaurantId) => <DashboardForRestaurant restaurantId={restaurantId} />}</RequireRestaurant>;
}
