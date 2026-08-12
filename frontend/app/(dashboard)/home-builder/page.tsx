"use client";

import { useEffect, useState, type FormEvent } from "react";
import { apiFetch, ApiError } from "@/lib/api";
import { RequireRestaurant } from "@/components/RequireRestaurant";
import type { BotButton, FlowDefinitionSummary, HomeButton, Restaurant } from "@/lib/types";

// --- Legacy engine: BotButton CRUD (already existed server-side; this page is what
// finally uses its PATCH endpoint + adds reorder/visibility, which bot-builder's own
// button section never did) --------------------------------------------------------

function LegacyHomeBuilder({ restaurantId }: { restaurantId: string }) {
  const [buttons, setButtons] = useState<BotButton[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const [title, setTitle] = useState("");
  const [emoji, setEmoji] = useState("");
  const [action, setAction] = useState("");
  const [creating, setCreating] = useState(false);

  async function load() {
    setLoading(true);
    try {
      setButtons(await apiFetch<BotButton[]>(`/restaurants/${restaurantId}/bot/buttons`));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load buttons");
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
      await apiFetch(`/restaurants/${restaurantId}/bot/buttons`, {
        method: "POST",
        body: JSON.stringify({ title, action, emoji: emoji || null, display_order: buttons.length }),
      });
      setTitle("");
      setEmoji("");
      setAction("");
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to create button");
    } finally {
      setCreating(false);
    }
  }

  async function patchButton(id: string, patch: Partial<BotButton>) {
    setBusyId(id);
    setError(null);
    try {
      await apiFetch(`/restaurants/${restaurantId}/bot/buttons/${id}`, { method: "PATCH", body: JSON.stringify(patch) });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to update button");
    } finally {
      setBusyId(null);
    }
  }

  async function move(index: number, direction: -1 | 1) {
    const target = index + direction;
    if (target < 0 || target >= buttons.length) return;
    const a = buttons[index];
    const b = buttons[target];
    setBusyId(a.id);
    setError(null);
    try {
      await Promise.all([
        apiFetch(`/restaurants/${restaurantId}/bot/buttons/${a.id}`, { method: "PATCH", body: JSON.stringify({ display_order: b.display_order }) }),
        apiFetch(`/restaurants/${restaurantId}/bot/buttons/${b.id}`, { method: "PATCH", body: JSON.stringify({ display_order: a.display_order }) }),
      ]);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to reorder");
    } finally {
      setBusyId(null);
    }
  }

  async function remove(id: string) {
    if (!window.confirm("Remove this button?")) return;
    try {
      await apiFetch(`/restaurants/${restaurantId}/bot/buttons/${id}`, { method: "DELETE" });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to remove button");
    }
  }

  return (
    <div className="space-y-4">
      {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

      <form onSubmit={handleCreate} className="flex flex-wrap items-end gap-3 rounded-lg bg-slate-50 p-3">
        <div>
          <label className="block text-xs font-medium text-slate-500">Emoji</label>
          <input value={emoji} onChange={(e) => setEmoji(e.target.value)} className="w-16 rounded-md border border-slate-300 px-3 py-1.5 text-sm" />
        </div>
        <div>
          <label className="block text-xs font-medium text-slate-500">Title</label>
          <input required value={title} onChange={(e) => setTitle(e.target.value)} className="rounded-md border border-slate-300 px-3 py-1.5 text-sm" />
        </div>
        <div>
          <label className="block text-xs font-medium text-slate-500">Action</label>
          <input required value={action} onChange={(e) => setAction(e.target.value)} placeholder="order_food" className="rounded-md border border-slate-300 px-3 py-1.5 text-sm" />
        </div>
        <button type="submit" disabled={creating} className="rounded-md bg-primary px-4 py-1.5 text-sm font-medium text-white disabled:opacity-60">
          {creating ? "Adding..." : "Add button"}
        </button>
      </form>

      {loading ? (
        <p className="text-sm text-slate-500">Loading...</p>
      ) : (
        <div className="space-y-2">
          {buttons.map((b, i) => (
            <div key={b.id} className="flex flex-wrap items-center gap-3 rounded-lg border border-slate-100 bg-white px-4 py-2">
              <div className="flex flex-col">
                <button disabled={busyId === b.id || i === 0} onClick={() => move(i, -1)} className="text-xs text-slate-400 hover:text-slate-700 disabled:opacity-30">▲</button>
                <button disabled={busyId === b.id || i === buttons.length - 1} onClick={() => move(i, 1)} className="text-xs text-slate-400 hover:text-slate-700 disabled:opacity-30">▼</button>
              </div>
              <input
                value={b.emoji || ""}
                onChange={(e) => patchButton(b.id, { emoji: e.target.value || null })}
                className="w-12 rounded-md border border-slate-200 px-2 py-1 text-sm"
              />
              <input
                value={b.title}
                onChange={(e) => setButtons((prev) => prev.map((x) => (x.id === b.id ? { ...x, title: e.target.value } : x)))}
                onBlur={(e) => patchButton(b.id, { title: e.target.value })}
                className="flex-1 rounded-md border border-slate-200 px-2 py-1 text-sm"
              />
              <span className="text-xs text-slate-400">({b.action})</span>
              <label className="flex items-center gap-1 text-xs text-slate-500">
                <input type="checkbox" checked={b.visible} onChange={(e) => patchButton(b.id, { visible: e.target.checked })} />
                Visible
              </label>
              <button onClick={() => remove(b.id)} className="text-xs font-medium text-red-600 hover:text-red-700">Remove</button>
            </div>
          ))}
          {buttons.length === 0 && (
            <p className="text-sm text-slate-400">No custom buttons yet -- the default menu is shown.</p>
          )}
        </div>
      )}
    </div>
  );
}

// --- Generic engine: FlowDefinition's entry-step buttons ---------------------------

function GenericHomeBuilder({ restaurantId }: { restaurantId: string }) {
  const [buttons, setButtons] = useState<HomeButton[]>([]);
  const [stepOptions, setStepOptions] = useState<{ step_id: string; type: string }[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedTick, setSavedTick] = useState(false);

  async function load() {
    setLoading(true);
    try {
      const [homeButtons, flow] = await Promise.all([
        apiFetch<{ entry_step_id: string; buttons: HomeButton[] }>(`/restaurants/${restaurantId}/flow/home-buttons`),
        apiFetch<FlowDefinitionSummary>(`/restaurants/${restaurantId}/flow`),
      ]);
      setButtons(homeButtons.buttons);
      setStepOptions(flow.steps.map((s) => ({ step_id: s.step_id, type: s.type })));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load home screen buttons");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [restaurantId]);

  function update(index: number, patch: Partial<HomeButton>) {
    setButtons((prev) => prev.map((b, i) => (i === index ? { ...b, ...patch } : b)));
  }

  function move(index: number, direction: -1 | 1) {
    const target = index + direction;
    if (target < 0 || target >= buttons.length) return;
    setButtons((prev) => {
      const next = [...prev];
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
  }

  function remove(index: number) {
    setButtons((prev) => prev.filter((_, i) => i !== index));
  }

  function addButton() {
    const suffix = Math.random().toString(36).slice(2, 7);
    setButtons((prev) => [
      ...prev,
      { id: `welcome:${suffix}`, title: "New Button", icon: null, visible: true, destination_step_id: stepOptions[0]?.step_id || "" },
    ]);
  }

  async function save() {
    setSaving(true);
    setError(null);
    try {
      await apiFetch(`/restaurants/${restaurantId}/flow/home-buttons`, {
        method: "PATCH",
        body: JSON.stringify({ buttons }),
      });
      setSavedTick(true);
      setTimeout(() => setSavedTick(false), 2000);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <p className="text-sm text-slate-500">Loading...</p>;

  return (
    <div className="space-y-4">
      {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

      <div className="space-y-2">
        {buttons.map((b, i) => (
          <div key={i} className="flex flex-wrap items-center gap-3 rounded-lg border border-slate-100 bg-white px-4 py-2">
            <div className="flex flex-col">
              <button disabled={i === 0} onClick={() => move(i, -1)} className="text-xs text-slate-400 hover:text-slate-700 disabled:opacity-30">▲</button>
              <button disabled={i === buttons.length - 1} onClick={() => move(i, 1)} className="text-xs text-slate-400 hover:text-slate-700 disabled:opacity-30">▼</button>
            </div>
            <input value={b.icon || ""} onChange={(e) => update(i, { icon: e.target.value || null })} className="w-12 rounded-md border border-slate-200 px-2 py-1 text-sm" placeholder="icon" />
            <input value={b.title} onChange={(e) => update(i, { title: e.target.value })} maxLength={20} className="flex-1 rounded-md border border-slate-200 px-2 py-1 text-sm" />
            <select value={b.destination_step_id} onChange={(e) => update(i, { destination_step_id: e.target.value })} className="rounded-md border border-slate-200 px-2 py-1 text-xs">
              {stepOptions.map((s) => (
                <option key={s.step_id} value={s.step_id}>{s.step_id}</option>
              ))}
            </select>
            <label className="flex items-center gap-1 text-xs text-slate-500">
              <input type="checkbox" checked={b.visible} onChange={(e) => update(i, { visible: e.target.checked })} />
              Visible
            </label>
            <button onClick={() => remove(i)} className="text-xs font-medium text-red-600 hover:text-red-700">Remove</button>
          </div>
        ))}
        {buttons.length === 0 && <p className="text-sm text-slate-400">No buttons -- add at least one below.</p>}
      </div>

      <div className="flex items-center gap-3">
        <button type="button" onClick={addButton} className="rounded-md border border-slate-300 px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-50">
          + Add button
        </button>
        <button onClick={save} disabled={saving || buttons.length === 0} className="rounded-md bg-primary px-4 py-1.5 text-sm font-medium text-white disabled:opacity-60">
          {saving ? "Saving..." : "Save home screen"}
        </button>
        {savedTick && <span className="text-xs font-medium text-emerald-600">Saved ✓</span>}
        <span className="text-xs text-slate-400">Titles must be 20 characters or fewer (WhatsApp button limit).</span>
      </div>
    </div>
  );
}

function HomeBuilderForRestaurant({ restaurantId }: { restaurantId: string }) {
  const [restaurant, setRestaurant] = useState<Restaurant | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<Restaurant>(`/restaurants/${restaurantId}`)
      .then(setRestaurant)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Failed to load business"));
  }, [restaurantId]);

  if (error) return <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>;
  if (!restaurant) return <p className="text-sm text-slate-500">Loading...</p>;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Home Builder</h1>
        <p className="mt-1 max-w-2xl text-sm text-slate-500">
          What a customer sees right after saying &quot;hi&quot; -- no code, ever. Reorder, rename, hide, or
          repoint any button.
        </p>
      </div>
      {restaurant.uses_generic_engine ? (
        <GenericHomeBuilder restaurantId={restaurantId} />
      ) : (
        <LegacyHomeBuilder restaurantId={restaurantId} />
      )}
    </div>
  );
}

export default function HomeBuilderPage() {
  return <RequireRestaurant>{(restaurantId) => <HomeBuilderForRestaurant restaurantId={restaurantId} />}</RequireRestaurant>;
}
