"use client";

import { useEffect, useState } from "react";
import { apiFetch, ApiError } from "@/lib/api";
import { RequireRestaurant } from "@/components/RequireRestaurant";
import { FlowGraphEditor } from "@/components/FlowGraphEditor";
import type { ApiEndpoint, FlowDefinitionFull, FlowStep, Restaurant } from "@/lib/types";
import { IconCheck } from "@/components/icons";

function FlowBuilderForRestaurant({ restaurantId }: { restaurantId: string }) {
  const [restaurant, setRestaurant] = useState<Restaurant | null>(null);
  const [flow, setFlow] = useState<FlowDefinitionFull | null>(null);
  const [apiEndpoints, setApiEndpoints] = useState<ApiEndpoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [savedTick, setSavedTick] = useState(false);
  // Bumped by the Retry button below to re-run the load effect -- a page that only ever
  // fetches once on mount stays stuck on a stale error forever if that one attempt lands
  // during a transient backend hiccup (a --reload restart window, a brief network blip),
  // with no way to recover short of a full browser refresh.
  const [retryKey, setRetryKey] = useState(0);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      setLoading(true);
      setLoadError(null);
      try {
        // Fetch the restaurant first -- a legacy-engine business has no FlowDefinition
        // at all, and GET /flow's 404 in that case shouldn't be mistaken for "flow not
        // set up yet" on a generic-engine business (see the uses_generic_engine gate
        // below, which needs to know this before deciding whether to fetch /flow).
        const r = await apiFetch<Restaurant>(`/restaurants/${restaurantId}`);
        if (cancelled) return;
        setRestaurant(r);
        if (!r.uses_generic_engine) return;

        const [f, endpoints] = await Promise.all([
          apiFetch<FlowDefinitionFull>(`/restaurants/${restaurantId}/flow`),
          apiFetch<ApiEndpoint[]>("/api-endpoints"),
        ]);
        if (cancelled) return;
        setFlow(f);
        setApiEndpoints(endpoints);
      } catch (err) {
        if (!cancelled) setLoadError(err instanceof ApiError ? err.message : "Failed to load flow");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [restaurantId, retryKey]);

  async function handleSave(steps: FlowStep[], entryStepId: string, uiLayout: Record<string, { x: number; y: number }>) {
    setSaving(true);
    setSaveError(null);
    try {
      const updated = await apiFetch<FlowDefinitionFull>(`/restaurants/${restaurantId}/flow/steps`, {
        method: "PUT",
        body: JSON.stringify({ steps, entry_step_id: entryStepId, ui_layout: uiLayout }),
      });
      setFlow(updated);
      setSavedTick(true);
      setTimeout(() => setSavedTick(false), 2000);
    } catch (err) {
      setSaveError(err instanceof ApiError ? err.message : "Failed to save flow");
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <div className="flex items-center gap-3 text-sm text-slate-500">
        <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-200 border-t-primary" />
        Loading flow…
      </div>
    );
  }
  if (loadError) {
    return (
      <div className="flex flex-wrap items-center gap-3 rounded-lg border border-red-100 bg-red-50 px-3.5 py-2.5 text-sm text-red-700">
        <span>{loadError}</span>
        <button
          onClick={() => setRetryKey((k) => k + 1)}
          className="rounded-md border border-red-200 bg-white px-2.5 py-1 text-xs font-medium text-red-700 transition-colors hover:bg-red-100"
        >
          Retry
        </button>
      </div>
    );
  }
  if (!restaurant) return null;

  if (!restaurant.uses_generic_engine) {
    return (
      <div className="space-y-2 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
        <p>
          Flow Builder is for businesses on the newer multi-niche engine. This business ({restaurant.name}) runs on
          the original restaurant-only flow -- use Bot Builder / Home Builder for it instead.
        </p>
        <p>
          Looking for a niche business instead? Go to{" "}
          <a href="/restaurants" className="font-medium underline">
            Businesses
          </a>{" "}
          and pick one WITHOUT the amber &quot;Legacy&quot; badge (e.g. &quot;Demo — Restaurant&quot;, with a dash --
          not the similarly-named legacy one).
        </p>
      </div>
    );
  }
  if (!flow) return <p className="text-sm text-slate-500">This business has no flow configured yet.</p>;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Flow Builder</h1>
          <p className="mt-1 max-w-2xl text-sm text-slate-500">
            The full conversation graph, beyond Home Builder&apos;s buttons-only view -- add steps, branch on
            conditions, call an approved API, hand off to a human, and connect it all visually.
          </p>
        </div>
        {savedTick && (
          <span className="flex items-center gap-1.5 rounded-full bg-emerald-50 px-3 py-1 text-xs font-semibold text-emerald-700">
            <IconCheck size={12} strokeWidth={2.2} /> Saved
          </span>
        )}
      </div>
      {saveError && <p className="rounded-lg border border-red-100 bg-red-50 px-3.5 py-2.5 text-sm text-red-700">{saveError}</p>}
      <FlowGraphEditor
        steps={flow.steps}
        entryStepId={flow.entry_step_id}
        uiLayout={flow.ui_layout}
        apiEndpoints={apiEndpoints}
        saving={saving}
        error={null}
        onSave={handleSave}
        restaurantId={restaurantId}
        flowDefinitionId={flow.id}
      />
    </div>
  );
}

export default function FlowBuilderPage() {
  return <RequireRestaurant>{(restaurantId) => <FlowBuilderForRestaurant restaurantId={restaurantId} />}</RequireRestaurant>;
}
