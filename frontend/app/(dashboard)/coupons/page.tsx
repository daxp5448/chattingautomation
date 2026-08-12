"use client";

import { useEffect, useState, type FormEvent } from "react";
import { apiFetch, ApiError } from "@/lib/api";
import { RequireRestaurant } from "@/components/RequireRestaurant";
import { useCurrentRestaurant } from "@/lib/restaurant";
import type { Coupon } from "@/lib/types";

function NotIncludedNotice() {
  return (
    <p className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
      Coupons aren&apos;t included in this business&apos;s plan -- contact support to upgrade. Existing coupons
      below are unaffected.
    </p>
  );
}

function CouponsForRestaurant({ restaurantId }: { restaurantId: string }) {
  const { hasFeature } = useCurrentRestaurant();
  const canManage = hasFeature("coupons");
  const [coupons, setCoupons] = useState<Coupon[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const [code, setCode] = useState("");
  const [type, setType] = useState<"flat" | "percentage">("flat");
  const [value, setValue] = useState("");
  const [minOrder, setMinOrder] = useState("0");
  const [firstOrderOnly, setFirstOrderOnly] = useState(false);
  const [autoApply, setAutoApply] = useState(false);
  const [creating, setCreating] = useState(false);

  async function load() {
    setLoading(true);
    try {
      setCoupons(await apiFetch<Coupon[]>(`/restaurants/${restaurantId}/coupons`));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load coupons");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [restaurantId]);

  async function handleCreate(e: FormEvent) {
    e.preventDefault();
    setCreating(true);
    setError(null);
    try {
      await apiFetch(`/restaurants/${restaurantId}/coupons`, {
        method: "POST",
        body: JSON.stringify({
          code,
          type,
          value: Number(value),
          min_order_amount: Number(minOrder) || 0,
          first_order_only: firstOrderOnly,
          auto_apply: autoApply,
        }),
      });
      setCode("");
      setValue("");
      setMinOrder("0");
      setFirstOrderOnly(false);
      setAutoApply(false);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to create coupon");
    } finally {
      setCreating(false);
    }
  }

  async function toggleActive(coupon: Coupon) {
    try {
      await apiFetch(`/restaurants/${restaurantId}/coupons/${coupon.id}`, {
        method: "PATCH",
        body: JSON.stringify({ is_active: !coupon.is_active }),
      });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to update coupon");
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Coupons</h1>
        <p className="text-sm text-slate-500">Customers can enter these at checkout on WhatsApp, or auto-apply ones apply themselves.</p>
      </div>
      {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
      {!canManage && <NotIncludedNotice />}

      {canManage && (
      <form onSubmit={handleCreate} className="flex flex-wrap items-end gap-3 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <div>
          <label className="block text-xs font-medium text-slate-500">Code</label>
          <input required value={code} onChange={(e) => setCode(e.target.value)} placeholder="SAVE20" className="w-32 rounded-md border border-slate-300 px-3 py-1.5 text-sm uppercase focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary" />
        </div>
        <div>
          <label className="block text-xs font-medium text-slate-500">Type</label>
          <select value={type} onChange={(e) => setType(e.target.value as "flat" | "percentage")} className="rounded-md border border-slate-300 px-3 py-1.5 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary">
            <option value="flat">Flat</option>
            <option value="percentage">Percentage</option>
          </select>
        </div>
        <div>
          <label className="block text-xs font-medium text-slate-500">Value</label>
          <input required type="number" step="0.01" value={value} onChange={(e) => setValue(e.target.value)} className="w-24 rounded-md border border-slate-300 px-3 py-1.5 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary" />
        </div>
        <div>
          <label className="block text-xs font-medium text-slate-500">Min order</label>
          <input type="number" step="0.01" value={minOrder} onChange={(e) => setMinOrder(e.target.value)} className="w-24 rounded-md border border-slate-300 px-3 py-1.5 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary" />
        </div>
        <label className="flex items-center gap-1.5 rounded-md bg-slate-50 px-2.5 py-1.5 text-xs text-slate-600">
          <input type="checkbox" checked={firstOrderOnly} onChange={(e) => setFirstOrderOnly(e.target.checked)} />
          First order only
        </label>
        <label className="flex items-center gap-1.5 rounded-md bg-slate-50 px-2.5 py-1.5 text-xs text-slate-600">
          <input type="checkbox" checked={autoApply} onChange={(e) => setAutoApply(e.target.checked)} />
          Auto-apply
        </label>
        <button type="submit" disabled={creating} className="rounded-md bg-primary px-4 py-1.5 text-sm font-medium text-white shadow-sm disabled:opacity-60">
          {creating ? "Creating..." : "+ Create coupon"}
        </button>
      </form>
      )}

      {loading ? (
        <div className="flex items-center gap-3 text-sm text-slate-500">
          <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-primary" />
          Loading coupons...
        </div>
      ) : (
        <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-3">Code</th>
                <th className="px-4 py-3">Type</th>
                <th className="px-4 py-3">Value</th>
                <th className="px-4 py-3">Min Order</th>
                <th className="px-4 py-3">Flags</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody>
              {coupons.map((c) => (
                <tr key={c.id} className="border-t border-slate-100 hover:bg-slate-50/60">
                  <td className="px-4 py-3 font-mono font-medium text-slate-800">🏷️ {c.code}</td>
                  <td className="px-4 py-3 text-slate-500">{c.type}</td>
                  <td className="px-4 py-3 text-slate-700">{c.type === "percentage" ? `${c.value}%` : c.value}</td>
                  <td className="px-4 py-3 text-slate-500">{c.min_order_amount}</td>
                  <td className="px-4 py-3 text-xs">
                    <div className="flex gap-1">
                      {c.first_order_only && <span className="rounded-full bg-blue-50 px-2 py-0.5 text-blue-600">first order</span>}
                      {c.auto_apply && <span className="rounded-full bg-violet-50 px-2 py-0.5 text-violet-600">auto</span>}
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${c.is_active ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-600"}`}>
                      {c.is_active ? "Active" : "Inactive"}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right">
                    <button
                      onClick={() => toggleActive(c)}
                      disabled={!canManage}
                      title={canManage ? undefined : "Coupons aren't included in this business's plan"}
                      className="rounded-md border border-slate-300 px-3 py-1 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {c.is_active ? "Deactivate" : "Activate"}
                    </button>
                  </td>
                </tr>
              ))}
              {coupons.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-4 py-8 text-center text-sm text-slate-400">
                    No coupons yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export default function CouponsPage() {
  return <RequireRestaurant>{(restaurantId) => <CouponsForRestaurant restaurantId={restaurantId} />}</RequireRestaurant>;
}
