"use client";

import { useEffect, useState, type FormEvent } from "react";
import { apiFetch, ApiError } from "@/lib/api";
import { RequireRestaurant } from "@/components/RequireRestaurant";
import type { Branch, DisplayDevice, DisplayDeviceCreateResult } from "@/lib/types";
import { IconMonitor } from "@/components/icons";

// Device *management* (mint/revoke a token for a kitchen/counter screen) -- distinct
// from the operational POS/kitchen screen itself (frontend/app/pos/[restaurantId]),
// which stays a separate token-authenticated route unattended screens open directly.
// Backend (app/api/v1/routers/display_devices.py) has had full create/list/revoke for a
// while with zero Super-Admin-reachable frontend page until now.
function DisplaysForRestaurant({ restaurantId }: { restaurantId: string }) {
  const [devices, setDevices] = useState<DisplayDevice[]>([]);
  const [branches, setBranches] = useState<Branch[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [branchId, setBranchId] = useState("");
  const [creating, setCreating] = useState(false);
  const [revealedToken, setRevealedToken] = useState<DisplayDeviceCreateResult | null>(null);

  async function load() {
    setLoading(true);
    try {
      const [devs, brs] = await Promise.all([
        apiFetch<DisplayDevice[]>(`/restaurants/${restaurantId}/display-devices`),
        apiFetch<Branch[]>(`/restaurants/${restaurantId}/branches`),
      ]);
      setDevices(devs);
      setBranches(brs);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load display devices");
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
      const created = await apiFetch<DisplayDeviceCreateResult>(`/restaurants/${restaurantId}/display-devices`, {
        method: "POST",
        body: JSON.stringify({ name, branch_id: branchId || null }),
      });
      setRevealedToken(created);
      setName("");
      setBranchId("");
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to create display device");
    } finally {
      setCreating(false);
    }
  }

  async function revoke(device: DisplayDevice) {
    if (!window.confirm(`Revoke "${device.name}"? Any screen using this link stops working immediately.`)) return;
    try {
      await apiFetch(`/restaurants/${restaurantId}/display-devices/${device.id}`, { method: "DELETE" });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to revoke display device");
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Displays</h1>
        <p className="text-sm text-slate-500">
          Token-authenticated kitchen/counter screens -- each device gets its own link, no staff login required.
        </p>
      </div>
      {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

      {revealedToken && (
        <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
          <p className="font-medium">
            &quot;{revealedToken.name}&quot; created -- copy this link now, it won&apos;t be shown again:
          </p>
          <code className="mt-1 block break-all rounded bg-white px-2 py-1 text-xs">
            {`/pos/${restaurantId}?token=${revealedToken.token}`}
          </code>
          <button onClick={() => setRevealedToken(null)} className="mt-2 text-xs font-medium text-emerald-700 hover:underline">
            Dismiss
          </button>
        </div>
      )}

      <form onSubmit={handleCreate} className="flex flex-wrap items-end gap-3 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <div>
          <label className="block text-xs font-medium text-slate-500">Device name</label>
          <input required value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Kitchen Screen" className="rounded-md border border-slate-300 px-3 py-1.5 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary" />
        </div>
        <div>
          <label className="block text-xs font-medium text-slate-500">Branch (optional)</label>
          <select value={branchId} onChange={(e) => setBranchId(e.target.value)} className="rounded-md border border-slate-300 px-3 py-1.5 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary">
            <option value="">All branches</option>
            {branches.map((b) => (
              <option key={b.id} value={b.id}>{b.name}</option>
            ))}
          </select>
        </div>
        <button type="submit" disabled={creating} className="rounded-md bg-primary px-4 py-1.5 text-sm font-medium text-white shadow-sm disabled:opacity-60">
          {creating ? "Creating..." : "+ Add display"}
        </button>
      </form>

      {loading ? (
        <div className="flex items-center gap-3 text-sm text-slate-500">
          <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-primary" />
          Loading displays...
        </div>
      ) : (
        <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-3">Name</th>
                <th className="px-4 py-3">Branch</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody>
              {devices.map((d) => (
                <tr key={d.id} className="border-t border-slate-100 hover:bg-slate-50/60">
                  <td className="px-4 py-3 font-medium text-slate-800">
                    <span className="flex items-center gap-1.5">
                      <IconMonitor size={13} className="text-slate-400" /> {d.name}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-slate-500">{branches.find((b) => b.id === d.branch_id)?.name || "All branches"}</td>
                  <td className="px-4 py-3">
                    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${d.revoked_at ? "bg-slate-100 text-slate-600" : "bg-emerald-100 text-emerald-700"}`}>
                      {d.revoked_at ? "Revoked" : "Active"}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right">
                    {!d.revoked_at && (
                      <button onClick={() => revoke(d)} className="rounded-md border border-red-300 px-3 py-1 text-xs font-medium text-red-600 hover:bg-red-50">
                        Revoke
                      </button>
                    )}
                  </td>
                </tr>
              ))}
              {devices.length === 0 && (
                <tr>
                  <td colSpan={4} className="px-4 py-8 text-center text-sm text-slate-400">
                    No display devices yet.
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

export default function DisplaysPage() {
  return <RequireRestaurant>{(restaurantId) => <DisplaysForRestaurant restaurantId={restaurantId} />}</RequireRestaurant>;
}
