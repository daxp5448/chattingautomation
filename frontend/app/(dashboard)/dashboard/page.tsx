"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import type { ComponentType } from "react";
import { apiFetch, ApiError } from "@/lib/api";
import { RequireRestaurant } from "@/components/RequireRestaurant";
import { useAuth } from "@/lib/auth";
import { useLiveSocket } from "@/lib/useLiveSocket";
import type { DashboardStats, PlatformStats } from "@/lib/types";
import {
  type IconProps,
  IconBuilding,
  IconCheckCircle,
  IconLink,
  IconReceipt,
  IconBed,
  IconCalendar,
  IconMail,
  IconDollarSign,
  IconGlobe,
  IconHourglass,
  IconXCircle,
  IconUsers,
  IconTrendingUp,
  IconPackage,
} from "@/components/icons";

// Platform-wide snapshot -- every number here is a real cross-tenant DB aggregate from
// GET /admin/dashboard/platform-stats (backend/app/api/v1/routers/dashboard.py), not a
// client-side reduce over a paginated restaurant list.
function PlatformOverview() {
  const [stats, setStats] = useState<PlatformStats | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<PlatformStats>("/admin/dashboard/platform-stats")
      .then(setStats)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Failed to load platform overview"));
  }, []);

  if (error) return <p className="rounded-lg border border-red-100 bg-red-50 px-3.5 py-2.5 text-sm text-red-700">{error}</p>;
  if (!stats) {
    return (
      <div className="flex items-center gap-3 rounded-2xl border border-slate-200 bg-white p-6 text-sm text-slate-500 shadow-card">
        <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-200 border-t-primary" />
        Loading platform overview…
      </div>
    );
  }

  const nicheEntries = Object.entries(stats.businesses.by_niche).sort((a, b) => b[1] - a[1]);
  const totalRevenue = stats.orders.revenue + stats.appointments.revenue + stats.bookings.revenue + stats.inquiries.revenue;

  const tiles: { label: string; value: string | number; icon: ComponentType<IconProps>; accent: string }[] = [
    { label: "Total Businesses", value: stats.businesses.total, icon: IconBuilding, accent: "bg-blue-50 text-blue-600" },
    { label: "Active Businesses", value: stats.businesses.active, icon: IconCheckCircle, accent: "bg-emerald-50 text-emerald-600" },
    { label: "Connected WhatsApp", value: stats.businesses.connected_whatsapp, icon: IconLink, accent: "bg-violet-50 text-violet-600" },
    { label: "Orders (all-time)", value: stats.orders.count, icon: IconReceipt, accent: "bg-amber-50 text-amber-600" },
    { label: "Bookings (all-time)", value: stats.bookings.count, icon: IconBed, accent: "bg-sky-50 text-sky-600" },
    { label: "Appointments (all-time)", value: stats.appointments.count, icon: IconCalendar, accent: "bg-pink-50 text-pink-600" },
    { label: "Leads/Enquiries (all-time)", value: stats.inquiries.count, icon: IconMail, accent: "bg-orange-50 text-orange-600" },
    { label: "Revenue (all-time)", value: totalRevenue.toFixed(2), icon: IconDollarSign, accent: "bg-emerald-50 text-emerald-600" },
  ];

  return (
    <div className="space-y-5 rounded-2xl border border-slate-200 bg-white p-6 shadow-card">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="flex items-center gap-2 text-[15px] font-semibold text-slate-900">
            <span className="flex h-6 w-6 items-center justify-center rounded-md bg-primary/10 text-primary-dark">
              <IconGlobe size={14} strokeWidth={1.8} />
            </span>
            Platform Overview
          </h2>
          <p className="mt-1 text-xs text-slate-500">Across every business on KelvionTech, excluding demo/showcase restaurants.</p>
        </div>
        <Link href="/restaurants" className="text-xs font-medium text-primary transition-colors hover:text-primary-dark">
          View all businesses →
        </Link>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {tiles.map((t) => (
          <Link
            key={t.label}
            href="/restaurants"
            className="group rounded-xl border border-slate-100 p-3.5 transition-all hover:-translate-y-0.5 hover:border-slate-200 hover:shadow-soft"
          >
            <div className={`mb-2 flex h-8 w-8 items-center justify-center rounded-lg ${t.accent}`}>
              <t.icon size={16} strokeWidth={1.8} />
            </div>
            <p className="text-[11px] font-medium uppercase tracking-wide text-slate-400">{t.label}</p>
            <p className="mt-0.5 text-xl font-semibold tracking-tight text-slate-900">{t.value}</p>
          </Link>
        ))}
      </div>

      {nicheEntries.length > 0 && (
        <div>
          <p className="mb-2 text-xs font-medium text-slate-500">Businesses by niche</p>
          <div className="flex flex-wrap gap-1.5">
            {nicheEntries.map(([niche, count]) => (
              <Link
                key={niche}
                href="/niches"
                className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs text-slate-600 transition-colors hover:border-primary/30 hover:bg-primary/5 hover:text-primary-dark"
              >
                {niche} <span className="font-semibold text-slate-800">{count}</span>
              </Link>
            ))}
          </div>
        </div>
      )}

      {stats.recent_activity.length > 0 && (
        <div>
          <p className="mb-2 text-xs font-medium text-slate-500">Recent activity (platform-wide)</p>
          <div className="divide-y divide-slate-100 overflow-hidden rounded-xl border border-slate-100">
            {stats.recent_activity.map((entry) => (
              <div key={entry.id} className="flex items-center justify-between gap-3 px-3.5 py-2.5 text-xs transition-colors hover:bg-slate-50/80">
                <div className="min-w-0">
                  <span className="font-medium text-slate-700">{entry.business_name || "-"}</span>
                  <span className="ml-2 text-slate-400">{entry.type}</span>
                  <span className="ml-2 text-slate-400">{entry.customer_name || ""}</span>
                </div>
                <div className="flex shrink-0 items-center gap-2 text-slate-500">
                  <span className="rounded-full bg-slate-100 px-2 py-0.5 font-medium text-slate-600">{entry.status}</span>
                  <span>{new Date(entry.created_at).toLocaleString()}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {stats.businesses.total === 0 && (
        <p className="text-sm text-slate-400">No businesses onboarded yet -- add one from Businesses.</p>
      )}
    </div>
  );
}

const TILES: { key: keyof DashboardStats; label: string; icon: ComponentType<IconProps>; accent: string; format?: (v: number) => string }[] = [
  { key: "total_orders", label: "Today's Orders", icon: IconReceipt, accent: "bg-blue-50 text-blue-600" },
  { key: "revenue", label: "Today's Revenue", icon: IconDollarSign, accent: "bg-emerald-50 text-emerald-600", format: (v) => v.toFixed(2) },
  { key: "pending_orders", label: "Pending Orders", icon: IconHourglass, accent: "bg-amber-50 text-amber-600" },
  { key: "cancelled_orders", label: "Cancelled Orders", icon: IconXCircle, accent: "bg-red-50 text-red-600" },
  { key: "completed_orders", label: "Completed Orders", icon: IconCheckCircle, accent: "bg-emerald-50 text-emerald-600" },
  { key: "total_customers", label: "Total Customers", icon: IconUsers, accent: "bg-violet-50 text-violet-600" },
  { key: "average_order_value", label: "Average Order Value", icon: IconTrendingUp, accent: "bg-blue-50 text-blue-600", format: (v) => v.toFixed(2) },
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

  if (error) return <p className="rounded-lg border border-red-100 bg-red-50 px-3.5 py-2.5 text-sm text-red-700">{error}</p>;
  if (!stats) {
    return (
      <div className="flex items-center gap-3 rounded-2xl border border-slate-200 bg-white p-6 text-sm text-slate-500 shadow-card">
        <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-200 border-t-primary" />
        Loading dashboard…
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <span className="flex h-2 w-2 animate-pulse rounded-full bg-emerald-500" />
        <h2 className="text-[15px] font-semibold text-slate-900">This Business, Today</h2>
        <span className="text-xs text-slate-400">— updates live as orders come in</span>
      </div>
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
        {TILES.map(({ key, label, icon: TileIcon, accent, format }) => {
          const raw = stats[key];
          const value = typeof raw === "number" ? (format ? format(raw) : raw) : raw ?? "-";
          return (
            <div
              key={key}
              className="rounded-2xl border border-slate-200 bg-white p-4 shadow-card transition-all hover:-translate-y-0.5 hover:shadow-panel"
            >
              <div className={`mb-2.5 flex h-9 w-9 items-center justify-center rounded-lg ${accent}`}>
                <TileIcon size={18} strokeWidth={1.7} />
              </div>
              <p className="text-xs font-medium uppercase tracking-wide text-slate-400">{label}</p>
              <p className="mt-1 text-2xl font-semibold tracking-tight text-slate-900">{value}</p>
            </div>
          );
        })}
        <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-card transition-all hover:-translate-y-0.5 hover:shadow-panel">
          <div className="mb-2.5 flex h-9 w-9 items-center justify-center rounded-lg bg-orange-50 text-orange-600">
            <IconPackage size={18} strokeWidth={1.7} />
          </div>
          <p className="text-xs font-medium uppercase tracking-wide text-slate-400">Most Ordered Item</p>
          <p className="mt-1 text-2xl font-semibold tracking-tight text-slate-900">{stats.most_ordered_item || "-"}</p>
        </div>
      </div>
    </div>
  );
}

export default function DashboardPage() {
  const { user } = useAuth();
  const isSuperAdmin = user?.role === "super_admin";

  return (
    <div className="space-y-7">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Dashboard</h1>
        <p className="mt-1 text-sm text-slate-500">
          {isSuperAdmin ? "Your platform, at a glance." : "Here's what's happening with your business."}
        </p>
      </div>
      {isSuperAdmin && <PlatformOverview />}
      <RequireRestaurant>{(restaurantId) => <DashboardForRestaurant restaurantId={restaurantId} />}</RequireRestaurant>
    </div>
  );
}
