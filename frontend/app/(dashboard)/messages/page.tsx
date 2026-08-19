"use client";

import { useEffect, useMemo, useState } from "react";
import { apiFetch, ApiError } from "@/lib/api";
import { RequireRestaurant } from "@/components/RequireRestaurant";
import type { MessageEntry, Restaurant } from "@/lib/types";
import { IconCheck } from "@/components/icons";

// Friendlier labels for the raw FlowStepType value shown next to each message -- purely
// cosmetic, matches the "Product Catalogue" not "step_type: catalog" spirit the rest of
// the admin panel already follows.
const STEP_TYPE_LABELS: Record<string, string> = {
  message: "Info message",
  menu_select: "Menu / buttons",
  quantity_input: "Quantity prompt",
  free_text_input: "Ask a question",
  confirm_action: "Confirmation step",
  human_handoff: "Talk to a Human",
  send_whatsapp_flow: "WhatsApp Flow",
};

function GenericMessagesEditor({ restaurantId }: { restaurantId: string }) {
  const [entries, setEntries] = useState<MessageEntry[]>([]);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [search, setSearch] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState<string | null>(null);
  const [justSaved, setJustSaved] = useState<string | null>(null);
  const [previewOpenFor, setPreviewOpenFor] = useState<string | null>(null);
  const [previewText, setPreviewText] = useState<string | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);

  async function load() {
    try {
      const list = await apiFetch<MessageEntry[]>(`/restaurants/${restaurantId}/flow/messages`);
      setEntries(list);
      setDrafts(Object.fromEntries(list.map((e) => [e.step_id, e.text])));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load messages");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [restaurantId]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return entries;
    return entries.filter((e) => e.message_key.toLowerCase().includes(q) || e.text.toLowerCase().includes(q) || (drafts[e.step_id] ?? "").toLowerCase().includes(q));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entries, search]);

  function isDirty(entry: MessageEntry): boolean {
    return (drafts[entry.step_id] ?? "") !== entry.text;
  }

  async function saveMessage(stepId: string) {
    setSaving(stepId);
    setError(null);
    try {
      await apiFetch(`/restaurants/${restaurantId}/flow/messages/${encodeURIComponent(stepId)}`, {
        method: "PATCH",
        body: JSON.stringify({ text: drafts[stepId] || "" }),
      });
      await load();
      setJustSaved(stepId);
      setTimeout(() => setJustSaved(null), 2000);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to save message");
    } finally {
      setSaving(null);
    }
  }

  async function restoreDefault(stepId: string) {
    setSaving(stepId);
    setError(null);
    try {
      await apiFetch(`/restaurants/${restaurantId}/flow/messages/${encodeURIComponent(stepId)}/restore-default`, {
        method: "POST",
      });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to restore default");
    } finally {
      setSaving(null);
    }
  }

  async function togglePreview(stepId: string) {
    if (previewOpenFor === stepId) {
      setPreviewOpenFor(null);
      setPreviewText(null);
      return;
    }
    setPreviewOpenFor(stepId);
    setPreviewText(null);
    setPreviewLoading(true);
    try {
      const result = await apiFetch<{ rendered: string }>("/messages/preview", {
        method: "POST",
        body: JSON.stringify({ text: drafts[stepId] || "" }),
      });
      setPreviewText(result.rendered);
    } catch (err) {
      setPreviewText(err instanceof ApiError ? `Preview failed: ${err.message}` : "Preview failed");
    } finally {
      setPreviewLoading(false);
    }
  }

  if (loading) {
    return (
      <div className="flex items-center gap-3 text-sm text-slate-500">
        <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-primary" />
        Loading...
      </div>
    );
  }

  return (
    <div className="space-y-6 pb-16">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Messages</h1>
        <p className="mt-1 max-w-2xl text-sm text-slate-500">
          Every message your WhatsApp bot sends, in one searchable list — no code, no JSON. Edit the text, preview
          exactly what a customer would see (with sample values filled in for {"{{"}variables{"}}"}), and save. A
          message you haven&apos;t touched keeps following your niche&apos;s own default automatically.
        </p>
      </div>

      {error && <p className="rounded-lg border border-red-100 bg-red-50 px-3.5 py-2.5 text-sm text-red-700">{error}</p>}

      <input
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        placeholder="Search by message key or text..."
        className="w-full max-w-md rounded-lg border border-slate-200 bg-white px-3.5 py-2 text-sm shadow-soft focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
      />

      <div className="space-y-4">
        {filtered.map((entry) => (
          <div key={entry.step_id} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-card transition-shadow hover:shadow-panel">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <div>
                <p className="font-mono text-xs text-slate-400">{entry.message_key}</p>
                <p className="text-xs text-slate-500">{STEP_TYPE_LABELS[entry.step_type] ?? entry.step_type}</p>
              </div>
              <span
                className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${
                  entry.is_customized ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-500"
                }`}
              >
                {entry.is_customized ? "Customized" : "Using default"}
              </span>
            </div>

            <textarea
              rows={3}
              value={drafts[entry.step_id] ?? ""}
              onChange={(e) => setDrafts((d) => ({ ...d, [entry.step_id]: e.target.value }))}
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
            />

            <div className="mt-3 flex flex-wrap items-center gap-2.5">
              <button
                onClick={() => saveMessage(entry.step_id)}
                disabled={saving === entry.step_id || !isDirty(entry)}
                className="rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-white shadow-soft transition-colors hover:bg-primary-dark disabled:opacity-40"
              >
                {saving === entry.step_id ? "Saving..." : "Save"}
              </button>
              <button
                onClick={() => togglePreview(entry.step_id)}
                className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-600 transition-colors hover:border-primary/30 hover:text-primary-dark"
              >
                {previewOpenFor === entry.step_id ? "Hide preview" : "Preview"}
              </button>
              {entry.is_customized && (
                <button
                  onClick={() => restoreDefault(entry.step_id)}
                  disabled={saving === entry.step_id}
                  className="rounded-lg border border-amber-200 px-3 py-1.5 text-xs font-medium text-amber-700 transition-colors hover:bg-amber-50 disabled:opacity-40"
                >
                  Restore default
                </button>
              )}
              {justSaved === entry.step_id && (
                <span className="inline-flex items-center gap-1 text-xs font-medium text-emerald-600">
                  <IconCheck size={12} strokeWidth={2.2} /> Saved
                </span>
              )}
            </div>

            {previewOpenFor === entry.step_id && (
              <div className="mt-3 max-w-sm rounded-2xl rounded-tl-none bg-[#dcf8c6] px-3 py-2 text-sm text-slate-800 shadow-soft">
                {previewLoading ? "Rendering preview..." : previewText}
              </div>
            )}
          </div>
        ))}
        {filtered.length === 0 && (
          <p className="rounded-2xl border border-dashed border-slate-300 p-10 text-center text-sm text-slate-400">
            No messages match &quot;{search}&quot;.
          </p>
        )}
      </div>
    </div>
  );
}

function MessagesRouter({ restaurantId }: { restaurantId: string }) {
  // Mirrors menu/page.tsx::MenuRouter's exact switch -- a business's customer-visible
  // copy lives in completely different storage depending on which conversation engine
  // it runs on (see backend/app/services/generic_flow_engine.py's module docstring).
  const [usesGenericEngine, setUsesGenericEngine] = useState<boolean | null>(null);

  useEffect(() => {
    apiFetch<Restaurant>(`/restaurants/${restaurantId}`)
      .then((r) => setUsesGenericEngine(r.uses_generic_engine))
      .catch(() => setUsesGenericEngine(false));
  }, [restaurantId]);

  if (usesGenericEngine === null) {
    return (
      <div className="flex items-center gap-3 text-sm text-slate-500">
        <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-primary" />
        Loading...
      </div>
    );
  }

  if (!usesGenericEngine) {
    return (
      <div className="rounded-xl border border-slate-200 bg-white p-6 text-sm text-slate-600 shadow-sm">
        This business runs on the classic bot builder — head to{" "}
        <a href="/bot-builder" className="font-medium text-primary hover:underline">
          Bot Builder
        </a>{" "}
        to edit its messages instead.
      </div>
    );
  }

  return <GenericMessagesEditor restaurantId={restaurantId} />;
}

export default function MessagesPage() {
  return <RequireRestaurant>{(restaurantId) => <MessagesRouter restaurantId={restaurantId} />}</RequireRestaurant>;
}
