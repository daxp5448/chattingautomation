"use client";

import { useEffect, useState } from "react";
import { apiFetch, ApiError } from "@/lib/api";
import { RequireRestaurant } from "@/components/RequireRestaurant";
import { useAuth } from "@/lib/auth";
import type { AuditLogEntry } from "@/lib/types";

// Read-only by design -- the backend never exposes create/update endpoints for audit
// entries (they're written internally via AuditLogRepository.record(), see
// backend/app/api/v1/routers/restaurants.py:359), and this page is Super-Admin-only,
// mirroring the backend's own require_roles(SUPER_ADMIN) on GET /audit-log.
function AuditLogForRestaurant({ restaurantId }: { restaurantId: string }) {
  const [entries, setEntries] = useState<AuditLogEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setEntries(null);
    apiFetch<AuditLogEntry[]>(`/restaurants/${restaurantId}/audit-log`)
      .then(setEntries)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Failed to load audit log"));
  }, [restaurantId]);

  if (error) return <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>;
  if (!entries) {
    return (
      <div className="flex items-center gap-3 text-sm text-slate-500">
        <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-primary" />
        Loading audit log...
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
      <table className="w-full text-sm">
        <thead className="bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
          <tr>
            <th className="px-4 py-3">When</th>
            <th className="px-4 py-3">Action</th>
            <th className="px-4 py-3">Entity</th>
            <th className="px-4 py-3">Actor</th>
            <th className="px-4 py-3">Diff</th>
          </tr>
        </thead>
        <tbody>
          {entries.map((entry) => (
            <tr key={entry.id} className="border-t border-slate-100 align-top hover:bg-slate-50/60">
              <td className="whitespace-nowrap px-4 py-3 text-slate-500">{new Date(entry.created_at).toLocaleString()}</td>
              <td className="px-4 py-3 font-medium text-slate-800">{entry.action}</td>
              <td className="px-4 py-3 text-slate-600">
                {entry.entity}
                {entry.entity_id && <span className="ml-1 font-mono text-xs text-slate-400">{entry.entity_id.slice(0, 8)}</span>}
              </td>
              <td className="px-4 py-3 font-mono text-xs text-slate-400">{entry.actor_id ? entry.actor_id.slice(0, 8) : "system"}</td>
              <td className="max-w-xs px-4 py-3">
                <pre className="max-h-24 overflow-auto whitespace-pre-wrap break-words text-xs text-slate-500">
                  {Object.keys(entry.diff).length > 0 ? JSON.stringify(entry.diff, null, 2) : "-"}
                </pre>
              </td>
            </tr>
          ))}
          {entries.length === 0 && (
            <tr>
              <td colSpan={5} className="px-4 py-8 text-center text-sm text-slate-400">
                No audit log entries yet.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

export default function AuditLogPage() {
  const { user } = useAuth();

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Audit Log</h1>
        <p className="text-sm text-slate-500">Every configuration change made to the selected business, most recent first.</p>
      </div>
      {user?.role !== "super_admin" ? (
        <p className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          Only Super Admins can view the audit log.
        </p>
      ) : (
        <RequireRestaurant>{(restaurantId) => <AuditLogForRestaurant restaurantId={restaurantId} />}</RequireRestaurant>
      )}
    </div>
  );
}
