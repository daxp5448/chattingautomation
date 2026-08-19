"use client";

import { useEffect, useState, type FormEvent } from "react";
import { apiFetch, ApiError } from "@/lib/api";
import { RequireRestaurant } from "@/components/RequireRestaurant";
import { useCurrentRestaurant } from "@/lib/restaurant";
import type { FaqEntry } from "@/lib/types";

// Same shell/convention as coupons/page.tsx -- backend (app/api/v1/routers/faq.py) has
// had full create/list/patch/delete for a while with zero frontend consumer until now.
function NotIncludedNotice() {
  return (
    <p className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
      The FAQ auto-responder isn&apos;t included in this business&apos;s plan -- contact support to upgrade.
      Existing entries below are unaffected.
    </p>
  );
}

function FaqForRestaurant({ restaurantId }: { restaurantId: string }) {
  const { hasFeature } = useCurrentRestaurant();
  const canManage = hasFeature("faq_autoresponder");
  const [entries, setEntries] = useState<FaqEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [keywords, setKeywords] = useState("");
  const [answer, setAnswer] = useState("");
  const [creating, setCreating] = useState(false);

  async function load() {
    setLoading(true);
    try {
      setEntries(await apiFetch<FaqEntry[]>(`/restaurants/${restaurantId}/faq`));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load FAQ entries");
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
      const trigger_keywords = keywords.split(",").map((k) => k.trim()).filter(Boolean);
      await apiFetch(`/restaurants/${restaurantId}/faq`, {
        method: "POST",
        body: JSON.stringify({ trigger_keywords, answer, display_order: entries.length }),
      });
      setKeywords("");
      setAnswer("");
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to create FAQ entry");
    } finally {
      setCreating(false);
    }
  }

  async function toggleActive(entry: FaqEntry) {
    try {
      await apiFetch(`/restaurants/${restaurantId}/faq/${entry.id}`, {
        method: "PATCH",
        body: JSON.stringify({ is_active: !entry.is_active }),
      });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to update FAQ entry");
    }
  }

  async function updateAnswer(entry: FaqEntry, value: string) {
    if (value === entry.answer) return;
    try {
      await apiFetch(`/restaurants/${restaurantId}/faq/${entry.id}`, {
        method: "PATCH",
        body: JSON.stringify({ answer: value }),
      });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to update FAQ entry");
    }
  }

  async function remove(entry: FaqEntry) {
    if (!window.confirm("Delete this FAQ entry?")) return;
    try {
      await apiFetch(`/restaurants/${restaurantId}/faq/${entry.id}`, { method: "DELETE" });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to delete FAQ entry");
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">FAQ</h1>
        <p className="text-sm text-slate-500">
          When a customer&apos;s message matches these keywords, the bot answers automatically instead of falling
          through to a human handoff.
        </p>
      </div>
      {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
      {!canManage && <NotIncludedNotice />}

      {canManage && (
        <form onSubmit={handleCreate} className="space-y-3 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <div>
            <label className="block text-xs font-medium text-slate-500">Trigger keywords (comma-separated)</label>
            <input
              required
              value={keywords}
              onChange={(e) => setKeywords(e.target.value)}
              placeholder="e.g. delivery time, how long, when will it arrive"
              className="w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-500">Answer</label>
            <textarea
              required
              rows={2}
              value={answer}
              onChange={(e) => setAnswer(e.target.value)}
              className="w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
            />
          </div>
          <button type="submit" disabled={creating} className="rounded-md bg-primary px-4 py-1.5 text-sm font-medium text-white shadow-sm disabled:opacity-60">
            {creating ? "Adding..." : "+ Add FAQ entry"}
          </button>
        </form>
      )}

      {loading ? (
        <div className="flex items-center gap-3 text-sm text-slate-500">
          <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-primary" />
          Loading FAQ entries...
        </div>
      ) : (
        <div className="space-y-2">
          {entries.map((entry) => (
            <div key={entry.id} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                <div className="flex flex-wrap gap-1">
                  {entry.trigger_keywords.map((k) => (
                    <span key={k} className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600">{k}</span>
                  ))}
                </div>
                <div className="flex items-center gap-2">
                  <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${entry.is_active ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-600"}`}>
                    {entry.is_active ? "Active" : "Inactive"}
                  </span>
                  <button
                    onClick={() => toggleActive(entry)}
                    disabled={!canManage}
                    className="rounded-md border border-slate-300 px-2 py-1 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {entry.is_active ? "Deactivate" : "Activate"}
                  </button>
                  <button
                    onClick={() => remove(entry)}
                    disabled={!canManage}
                    className="rounded-md border border-red-300 px-2 py-1 text-xs font-medium text-red-600 hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    Delete
                  </button>
                </div>
              </div>
              <textarea
                defaultValue={entry.answer}
                disabled={!canManage}
                rows={2}
                onBlur={(e) => updateAnswer(entry, e.target.value)}
                className="w-full rounded-md border border-slate-200 px-2 py-1 text-sm disabled:bg-slate-50"
              />
            </div>
          ))}
          {entries.length === 0 && <p className="text-sm text-slate-400">No FAQ entries yet.</p>}
        </div>
      )}
    </div>
  );
}

export default function FaqPage() {
  return <RequireRestaurant>{(restaurantId) => <FaqForRestaurant restaurantId={restaurantId} />}</RequireRestaurant>;
}
