"use client";

import { useEffect, useState, type FormEvent } from "react";
import { apiFetch, ApiError } from "@/lib/api";
import { RequireRestaurant } from "@/components/RequireRestaurant";
import type { Branch } from "@/lib/types";

function BranchesForRestaurant({ restaurantId }: { restaurantId: string }) {
  const [branches, setBranches] = useState<Branch[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const [name, setName] = useState("");
  const [address, setAddress] = useState("");
  const [phone, setPhone] = useState("");
  const [latitude, setLatitude] = useState("");
  const [longitude, setLongitude] = useState("");
  const [creating, setCreating] = useState(false);

  const [editingCoordsId, setEditingCoordsId] = useState<string | null>(null);
  const [editLat, setEditLat] = useState("");
  const [editLng, setEditLng] = useState("");
  const [savingCoords, setSavingCoords] = useState(false);

  async function load() {
    setLoading(true);
    try {
      setBranches(await apiFetch<Branch[]>(`/restaurants/${restaurantId}/branches`));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load branches");
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
      await apiFetch(`/restaurants/${restaurantId}/branches`, {
        method: "POST",
        body: JSON.stringify({
          name,
          address,
          phone,
          latitude: latitude ? Number(latitude) : null,
          longitude: longitude ? Number(longitude) : null,
        }),
      });
      setName("");
      setAddress("");
      setPhone("");
      setLatitude("");
      setLongitude("");
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to create branch");
    } finally {
      setCreating(false);
    }
  }

  async function deleteBranch(branch: Branch) {
    if (
      !window.confirm(
        `Delete "${branch.name}"? Branches with existing orders can't be deleted -- you'll get a clear error instead.`
      )
    ) {
      return;
    }
    try {
      await apiFetch(`/restaurants/${restaurantId}/branches/${branch.id}`, { method: "DELETE" });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to delete branch");
    }
  }

  async function toggleStatus(branch: Branch) {
    const next = branch.status === "open" ? "closed" : "open";
    try {
      await apiFetch(`/restaurants/${restaurantId}/branches/${branch.id}`, {
        method: "PATCH",
        body: JSON.stringify({ status: next }),
      });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to update branch");
    }
  }

  function startEditCoords(branch: Branch) {
    setEditingCoordsId(branch.id);
    setEditLat(branch.latitude != null ? String(branch.latitude) : "");
    setEditLng(branch.longitude != null ? String(branch.longitude) : "");
  }

  async function saveCoords(branchId: string) {
    setSavingCoords(true);
    setError(null);
    try {
      await apiFetch(`/restaurants/${restaurantId}/branches/${branchId}`, {
        method: "PATCH",
        body: JSON.stringify({ latitude: editLat ? Number(editLat) : null, longitude: editLng ? Number(editLng) : null }),
      });
      setEditingCoordsId(null);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to save coordinates");
    } finally {
      setSavingCoords(false);
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Branches</h1>
        <p className="text-sm text-slate-500">
          Every branch you add here shows up automatically in the WhatsApp bot&apos;s branch picker — nothing else to wire up.
        </p>
      </div>
      {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

      <form onSubmit={handleCreate} className="flex flex-wrap items-end gap-3 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <div>
          <label className="block text-xs font-medium text-slate-500">Name</label>
          <input required value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Downtown" className="rounded-md border border-slate-300 px-3 py-1.5 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary" />
        </div>
        <div>
          <label className="block text-xs font-medium text-slate-500">Address</label>
          <input value={address} onChange={(e) => setAddress(e.target.value)} className="w-56 rounded-md border border-slate-300 px-3 py-1.5 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary" />
        </div>
        <div>
          <label className="block text-xs font-medium text-slate-500">Phone</label>
          <input value={phone} onChange={(e) => setPhone(e.target.value)} className="rounded-md border border-slate-300 px-3 py-1.5 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary" />
        </div>
        <div>
          <label className="block text-xs font-medium text-slate-500">Latitude</label>
          <input value={latitude} onChange={(e) => setLatitude(e.target.value)} placeholder="23.0225" className="w-24 rounded-md border border-slate-300 px-3 py-1.5 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary" />
        </div>
        <div>
          <label className="block text-xs font-medium text-slate-500">Longitude</label>
          <input value={longitude} onChange={(e) => setLongitude(e.target.value)} placeholder="72.5714" className="w-24 rounded-md border border-slate-300 px-3 py-1.5 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary" />
        </div>
        <button type="submit" disabled={creating} className="rounded-md bg-primary px-4 py-1.5 text-sm font-medium text-white shadow-sm disabled:opacity-60">
          {creating ? "Adding..." : "+ Add branch"}
        </button>
        <p className="w-full text-xs text-slate-400">
          Latitude/longitude are optional but make &quot;Our Location&quot; send a real tappable map pin on WhatsApp instead of just text.
        </p>
      </form>

      {loading ? (
        <div className="flex items-center gap-3 text-sm text-slate-500">
          <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-primary" />
          Loading branches...
        </div>
      ) : (
        <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-3">Name</th>
                <th className="px-4 py-3">Address</th>
                <th className="px-4 py-3">Phone</th>
                <th className="px-4 py-3">Map location</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody>
              {branches.map((b) => (
                <tr key={b.id} className="border-t border-slate-100 hover:bg-slate-50/60">
                  <td className="px-4 py-3 font-medium text-slate-800">📍 {b.name}</td>
                  <td className="px-4 py-3 text-slate-500">{b.address || "-"}</td>
                  <td className="px-4 py-3 text-slate-500">{b.phone || "-"}</td>
                  <td className="px-4 py-3 text-slate-500">
                    {editingCoordsId === b.id ? (
                      <div className="flex items-center gap-1">
                        <input value={editLat} onChange={(e) => setEditLat(e.target.value)} placeholder="lat" className="w-20 rounded-md border border-slate-300 px-2 py-1 text-xs" />
                        <input value={editLng} onChange={(e) => setEditLng(e.target.value)} placeholder="lng" className="w-20 rounded-md border border-slate-300 px-2 py-1 text-xs" />
                        <button onClick={() => saveCoords(b.id)} disabled={savingCoords} className="rounded-md bg-primary px-2 py-1 text-xs font-medium text-white disabled:opacity-60">
                          Save
                        </button>
                        <button onClick={() => setEditingCoordsId(null)} className="text-xs text-slate-400">
                          Cancel
                        </button>
                      </div>
                    ) : (
                      <button onClick={() => startEditCoords(b)} className="text-xs font-medium text-primary hover:underline">
                        {b.latitude != null && b.longitude != null ? `📌 ${b.latitude.toFixed(4)}, ${b.longitude.toFixed(4)}` : "Set map pin"}
                      </button>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${b.status === "open" ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-600"}`}>
                      {b.status === "open" ? "● Open" : "Closed"}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right">
                    <div className="flex justify-end gap-2">
                      <button onClick={() => toggleStatus(b)} className="rounded-md border border-slate-300 px-3 py-1 text-xs font-medium text-slate-700 hover:bg-slate-50">
                        {b.status === "open" ? "Close" : "Open"}
                      </button>
                      <button onClick={() => deleteBranch(b)} className="rounded-md border border-red-300 px-3 py-1 text-xs font-medium text-red-600 hover:bg-red-50">
                        Delete
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
              {branches.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-sm text-slate-400">
                    No branches yet — add your first one above.
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

export default function BranchesPage() {
  return <RequireRestaurant>{(restaurantId) => <BranchesForRestaurant restaurantId={restaurantId} />}</RequireRestaurant>;
}
