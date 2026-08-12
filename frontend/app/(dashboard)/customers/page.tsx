"use client";

import { useEffect, useState } from "react";
import { apiFetch, ApiError } from "@/lib/api";
import { RequireRestaurant } from "@/components/RequireRestaurant";
import { useAuth } from "@/lib/auth";
import type { Customer } from "@/lib/types";

function CustomersForRestaurant({ restaurantId }: { restaurantId: string }) {
  const { user } = useAuth();
  const canAnonymize = user?.role === "owner" || user?.role === "manager";
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  async function load() {
    setLoading(true);
    try {
      setCustomers(await apiFetch<Customer[]>(`/restaurants/${restaurantId}/customers`));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load customers");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [restaurantId]);

  async function anonymize(customer: Customer) {
    if (
      !window.confirm(
        `Anonymize ${customer.name || customer.phone}? This permanently removes their name, phone, and address from view. Their order history is kept for tax records and cannot be recovered afterward.`
      )
    ) {
      return;
    }
    try {
      await apiFetch(`/customers/${customer.id}/anonymize`, { method: "POST" });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to anonymize customer");
    }
  }

  if (loading) {
    return (
      <div className="flex items-center gap-3 text-sm text-slate-500">
        <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-primary" />
        Loading customers...
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Customers</h1>
        <p className="text-sm text-slate-500">Everyone who has messaged your WhatsApp bot, with their loyalty balance.</p>
      </div>
      {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

      <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-4 py-3">Name</th>
              <th className="px-4 py-3">Phone</th>
              <th className="px-4 py-3">Tags</th>
              <th className="px-4 py-3">Loyalty Points</th>
              <th className="px-4 py-3">Status</th>
              {canAnonymize && <th className="px-4 py-3" />}
            </tr>
          </thead>
          <tbody>
            {customers.map((c) => (
              <tr key={c.id} className="border-t border-slate-100 hover:bg-slate-50/60">
                <td className="px-4 py-3 font-medium text-slate-800">{c.name || "-"}</td>
                <td className="px-4 py-3 text-slate-500">{c.phone}</td>
                <td className="px-4 py-3 text-xs text-slate-500">{c.tags.join(", ") || "-"}</td>
                <td className="px-4 py-3">
                  <span className="rounded-full bg-violet-50 px-2 py-0.5 text-xs font-medium text-violet-600">⭐ {c.loyalty_points}</span>
                </td>
                <td className="px-4 py-3">
                  <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${c.is_blocked ? "bg-red-100 text-red-700" : "bg-emerald-100 text-emerald-700"}`}>
                    {c.is_blocked ? "Blocked" : "Active"}
                  </span>
                </td>
                {canAnonymize && (
                  <td className="px-4 py-3 text-right">
                    <button onClick={() => anonymize(c)} className="rounded-md border border-slate-300 px-3 py-1 text-xs font-medium text-slate-700 hover:bg-slate-50">
                      Anonymize
                    </button>
                  </td>
                )}
              </tr>
            ))}
            {customers.length === 0 && (
              <tr>
                <td colSpan={canAnonymize ? 6 : 5} className="px-4 py-8 text-center text-sm text-slate-400">
                  No customers yet — they&apos;ll appear here after their first WhatsApp message.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function CustomersPage() {
  return <RequireRestaurant>{(restaurantId) => <CustomersForRestaurant restaurantId={restaurantId} />}</RequireRestaurant>;
}
