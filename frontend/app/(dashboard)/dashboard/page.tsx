"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { apiFetch, ApiError } from "@/lib/api";
import { RequireRestaurant } from "@/components/RequireRestaurant";
import { useAuth } from "@/lib/auth";
import { useLiveSocket } from "@/lib/useLiveSocket";
import type { DashboardStats, Restaurant } from "@/lib/types";

// Platform-wide snapshot, computed entirely from GET /restaurants (already the Businesses
// page's own data source) -- no new backend endpoint needed for this slice. Real orders/
// bookings/leads/conversations aggregated ACROSS every business would need new backend
// aggregate queries (out of scope for this pass); this panel sticks to what's honestly
// derivable from data already in hand rather than guessing or hardcoding those numbers.
function PlatformOverview() {
  const [restaurants, setRestaurants] = useState<Restaurant[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<Restaurant[]>("/restaurants")
      .then(setRestaurants)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Failed to load platform overview"));
  }, []);

  if (error) return <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>;
  if (!restaurants) {
    return (
      <div className="flex items-center gap-3 text-sm text-slate-500">
        <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-primary" />
        Loading platform overview...
      </div>
    );
  }

  // Demo/showcase restaurants (see /niches "Demo Bot" panel) are deliberately excluded
  // from every count here -- they're not real businesses on the platform, same exclusion
  // the Businesses page's own "Demo" badge exists to distinguish, just applied to the
  // aggregate counts instead of a per-row label.
  const real = restaurants.filter((r) => !r.is_demo);
  const active = real.filter((r) => r.status === "active").length;
  const connected = real.filter((r) => r.whatsapp_phone_number_id).length;
  const totalOrders = real.reduce((sum, r) => sum + (r.total_orders || 0), 0);

  const nicheCounts = new Map<string, number>();
  for (const r of real) {
    const key = r.niche_type || "Custom / Legacy";
    nicheCounts.set(key, (nicheCounts.get(key) || 0) + 1);
  }
  const nicheEntries = Array.from(nicheCounts.entries()).sort((a, b) => b[1] - a[1]);

  const tiles = [
    { label: "Total Businesses", value: real.length, icon: "🏢", accent: "bg-blue-50 text-blue-600" },
    { label: "Active Businesses", value: active, icon: "✅", accent: "bg-emerald-50 text-emerald-600" },
    { label: "Connected WhatsApp", value: connected, icon: "🔗", accent: "bg-violet-50 text-violet-600" },
    { label: "Orders/Bookings/Leads (all-time)", value: totalOrders, icon: "🧾", accent: "bg-amber-50 text-amber-600" },
  ];

  return (
    <div className="space-y-4 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold text-slate-800">🌐 Platform Overview</h2>
          <p className="mt-0.5 text-xs text-slate-500">Across every business on KelvionTech, excluding demo restaurants.</p>
        </div>
        <Link href="/restaurants" className="text-xs font-medium text-primary hover:underline">
          View all businesses →
        </Link>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {tiles.map((t) => (
          <Link
            key={t.label}
            href="/restaurants"
            className="rounded-lg border border-slate-100 p-3 transition-colors hover:border-slate-300 hover:bg-slate-50"
          >
            <div className={`mb-1.5 flex h-8 w-8 items-center justify-center rounded-lg text-sm ${t.accent}`}>{t.icon}</div>
            <p className="text-[11px] font-medium uppercase tracking-wide text-slate-400">{t.label}</p>
            <p className="mt-0.5 text-xl font-semibold text-slate-900">{t.value}</p>
          </Link>
        ))}
      </div>

      {nicheEntries.length > 0 && (
        <div>
          <p className="mb-1.5 text-xs font-medium text-slate-500">Niche distribution</p>
          <div className="flex flex-wrap gap-1.5">
            {nicheEntries.map(([niche, count]) => (
              <Link
                key={niche}
                href="/niches"
                className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs text-slate-600 hover:bg-slate-100"
              >
                {niche} <span className="font-semibold text-slate-800">{count}</span>
              </Link>
            ))}
          </div>
        </div>
      )}

      {real.length === 0 && (
        <p className="text-sm text-slate-400">No businesses onboarded yet -- add one from Businesses.</p>
      )}
    </div>
  );
}

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
    <div className="space-y-4">
      <div>
        <h2 className="text-sm font-semibold text-slate-800">📍 This Business, Today</h2>
        <p className="text-xs text-slate-500">Live snapshot of today&apos;s activity — updates automatically as orders come in.</p>
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
  const { user } = useAuth();
  const isSuperAdmin = user?.role === "super_admin";

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Dashboard</h1>
      </div>
      {isSuperAdmin && <PlatformOverview />}
      <RequireRestaurant>{(restaurantId) => <DashboardForRestaurant restaurantId={restaurantId} />}</RequireRestaurant>
    </div>
  );
}
