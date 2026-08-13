"use client";

import { useEffect, useState, type FormEvent } from "react";
import { apiFetch, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { FlowGraphEditor } from "@/components/FlowGraphEditor";
import { TemplateImageUpload } from "@/components/TemplateImageUpload";
import type { ApiEndpoint, DemoBotStatus, FlowStep, NicheCatalogCategory, NicheCatalogItem, NicheTemplateFull, NicheTemplateSummary } from "@/lib/types";

function DemoBotPanel() {
  const [status, setStatus] = useState<DemoBotStatus | null>(null);

  useEffect(() => {
    apiFetch<DemoBotStatus>("/restaurants/demo-bot-status")
      .then(setStatus)
      .catch(() => setStatus(null)); // non-fatal -- this panel is purely informational
  }, []);

  if (!status) return null;

  const missing = status.niches.filter((n) => !n.has_demo_restaurant);

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <h2 className="text-sm font-semibold text-slate-800">Industry Picker</h2>
      <p className="mt-1 text-xs text-slate-500">
        A WhatsApp number prospects can message to try any niche's bot -- either a dedicated Demo Bot business
        (see Businesses), or any real business with Industry Picker Mode turned on from its Manage page.
      </p>
      <p className="mt-3 text-sm">
        Entry point:{" "}
        {status.sentinel_configured ? (
          <span className="font-medium text-emerald-600">Configured</span>
        ) : (
          <span className="font-medium text-amber-600">
            Not configured -- create a business with &quot;Demo Bot business&quot; checked and a real WhatsApp
            number, or turn on Industry Picker Mode for an existing business.
          </span>
        )}
      </p>
      <p className="mt-1 text-sm text-slate-600">
        {status.niches.length - missing.length} / {status.niches.length} niches have a demo business provisioned.
      </p>
      {missing.length > 0 && (
        <p className="mt-1 text-xs text-slate-400">
          Missing: {missing.map((n) => n.name).join(", ")} -- runs automatically on the next deploy
          (python -m app.scripts.seed_demo_restaurants).
        </p>
      )}
    </div>
  );
}

const ACTION_TYPES = ["order", "inquiry", "appointment", "booking"] as const;

function jsonField(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

function isValidCategory(c: unknown): c is NicheCatalogCategory {
  return typeof c === "object" && c !== null && typeof (c as NicheCatalogCategory).name === "string";
}

function isValidItem(i: unknown): i is NicheCatalogItem {
  return typeof i === "object" && i !== null && typeof (i as NicheCatalogItem).name === "string";
}

// Structured browse-and-edit view over default_catalog, so images/names/prices for every
// category and item across all 12 niches can be changed without touching raw JSON. Any
// row that doesn't match the expected shape (pre-existing data, if any) falls back to an
// inline raw-JSON editor for just that one row instead of crashing the whole page --
// default_catalog itself has no other consumer than niche_provisioning.py, which reads
// exactly these fields (name/icon_image/items -> name/description/price/price_type/images).
function CatalogEditor({
  catalog, onChange,
}: {
  catalog: NicheCatalogCategory[];
  onChange: (catalog: NicheCatalogCategory[]) => void;
}) {
  function updateCategory(index: number, patch: Partial<NicheCatalogCategory>) {
    onChange(catalog.map((c, i) => (i === index ? { ...c, ...patch } : c)));
  }
  function replaceCategoryRaw(index: number, value: unknown) {
    onChange(catalog.map((c, i) => (i === index ? (value as NicheCatalogCategory) : c)));
  }
  function removeCategory(index: number) {
    if (!window.confirm("Remove this category and all its items?")) return;
    onChange(catalog.filter((_, i) => i !== index));
  }
  function addCategory() {
    onChange([...catalog, { name: "New Category", icon_image: null, items: [] }]);
  }
  function updateItem(catIndex: number, itemIndex: number, patch: Partial<NicheCatalogItem>) {
    const items = ((catalog[catIndex].items as NicheCatalogItem[]) || []).map((it, i) => (i === itemIndex ? { ...it, ...patch } : it));
    updateCategory(catIndex, { items });
  }
  function replaceItemRaw(catIndex: number, itemIndex: number, value: unknown) {
    const items = ((catalog[catIndex].items as NicheCatalogItem[]) || []).map((it, i) => (i === itemIndex ? (value as NicheCatalogItem) : it));
    updateCategory(catIndex, { items });
  }
  function removeItem(catIndex: number, itemIndex: number) {
    const items = ((catalog[catIndex].items as NicheCatalogItem[]) || []).filter((_, i) => i !== itemIndex);
    updateCategory(catIndex, { items });
  }
  function addItem(catIndex: number) {
    const items = [
      ...((catalog[catIndex].items as NicheCatalogItem[]) || []),
      { name: "New Item", description: "", price: 0, price_type: "fixed", images: [], attributes: {} },
    ];
    updateCategory(catIndex, { items });
  }

  return (
    <div className="space-y-3">
      {catalog.map((category, catIndex) => {
        if (!isValidCategory(category)) {
          return (
            <div key={catIndex} className="rounded-md border border-amber-300 bg-amber-50 p-3">
              <p className="text-xs font-medium text-amber-700">
                This category doesn&apos;t match the expected shape -- edit it as raw JSON below.
              </p>
              <textarea
                rows={4}
                defaultValue={JSON.stringify(category, null, 2)}
                onBlur={(e) => {
                  try {
                    replaceCategoryRaw(catIndex, JSON.parse(e.target.value));
                  } catch {
                    // still invalid -- leave catalog untouched, keep showing this row
                  }
                }}
                className="mt-2 w-full rounded-md border border-amber-300 px-2 py-1 font-mono text-xs"
              />
              <button type="button" onClick={() => removeCategory(catIndex)} className="mt-2 text-xs font-medium text-red-600 hover:text-red-700">
                Remove category
              </button>
            </div>
          );
        }

        const items = (category.items as NicheCatalogItem[]) || [];

        return (
          <div key={catIndex} className="space-y-2 rounded-md border border-slate-200 bg-white p-3">
            <div className="flex items-start justify-between gap-3">
              <div className="flex-1">
                <label className="block text-xs font-medium text-slate-500">Category name</label>
                <input
                  value={category.name}
                  onChange={(e) => updateCategory(catIndex, { name: e.target.value })}
                  className="w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm"
                />
              </div>
              <button type="button" onClick={() => removeCategory(catIndex)} className="mt-5 shrink-0 text-xs font-medium text-red-600 hover:text-red-700">
                Remove category
              </button>
            </div>
            <TemplateImageUpload
              label="Category icon"
              value={category.icon_image || ""}
              onChange={(url) => updateCategory(catIndex, { icon_image: url || null })}
            />

            <div className="space-y-2 rounded-md bg-slate-50 p-2">
              <p className="text-xs font-medium text-slate-500">Items</p>
              {items.map((item, itemIndex) => {
                if (!isValidItem(item)) {
                  return (
                    <div key={itemIndex} className="rounded-md border border-amber-300 bg-amber-50 p-2">
                      <p className="text-[11px] font-medium text-amber-700">
                        This item doesn&apos;t match the expected shape -- edit it as raw JSON below.
                      </p>
                      <textarea
                        rows={3}
                        defaultValue={JSON.stringify(item, null, 2)}
                        onBlur={(e) => {
                          try {
                            replaceItemRaw(catIndex, itemIndex, JSON.parse(e.target.value));
                          } catch {
                            // still invalid -- leave catalog untouched, keep showing this row
                          }
                        }}
                        className="mt-1 w-full rounded-md border border-amber-300 px-2 py-1 font-mono text-xs"
                      />
                      <button type="button" onClick={() => removeItem(catIndex, itemIndex)} className="mt-1 text-xs font-medium text-red-600 hover:text-red-700">
                        Remove
                      </button>
                    </div>
                  );
                }

                return (
                  <div key={itemIndex} className="grid grid-cols-[1fr_auto] gap-2 rounded-md border border-slate-200 bg-white p-2">
                    <div className="grid grid-cols-2 gap-2">
                      <div>
                        <label className="block text-[11px] font-medium text-slate-500">Name</label>
                        <input
                          value={item.name}
                          onChange={(e) => updateItem(catIndex, itemIndex, { name: e.target.value })}
                          className="w-full rounded-md border border-slate-300 px-2 py-1 text-xs"
                        />
                      </div>
                      <div>
                        <label className="block text-[11px] font-medium text-slate-500">Price</label>
                        <input
                          type="number"
                          value={item.price ?? ""}
                          onChange={(e) => updateItem(catIndex, itemIndex, { price: e.target.value === "" ? null : Number(e.target.value) })}
                          className="w-full rounded-md border border-slate-300 px-2 py-1 text-xs"
                        />
                      </div>
                      <div className="col-span-2">
                        <label className="block text-[11px] font-medium text-slate-500">Description</label>
                        <input
                          value={item.description || ""}
                          onChange={(e) => updateItem(catIndex, itemIndex, { description: e.target.value })}
                          className="w-full rounded-md border border-slate-300 px-2 py-1 text-xs"
                        />
                      </div>
                      <div className="col-span-2">
                        <TemplateImageUpload
                          label="Item photo"
                          value={item.images?.[0] || ""}
                          onChange={(url) => updateItem(catIndex, itemIndex, { images: url ? [url] : [] })}
                        />
                      </div>
                    </div>
                    <button type="button" onClick={() => removeItem(catIndex, itemIndex)} className="self-start text-xs font-medium text-red-600 hover:text-red-700">
                      Remove
                    </button>
                  </div>
                );
              })}
              <button type="button" onClick={() => addItem(catIndex)} className="text-xs font-medium text-primary hover:underline">
                + Item
              </button>
            </div>
          </div>
        );
      })}
      <button type="button" onClick={addCategory} className="text-xs font-medium text-primary hover:underline">
        + Category
      </button>
    </div>
  );
}

function TemplateEditor({
  template, apiEndpoints, onSaved,
}: {
  template: NicheTemplateFull;
  apiEndpoints: ApiEndpoint[];
  onSaved: () => void;
}) {
  const [name, setName] = useState(template.name);
  const [actionType, setActionType] = useState(template.action_type);
  const [icon, setIcon] = useState(template.icon || "");
  const [welcomeMessage, setWelcomeMessage] = useState(template.welcome_message);
  const [welcomeBannerImage, setWelcomeBannerImage] = useState(template.welcome_banner_image || "");
  // `catalog` is the single source of truth, edited either via the structured
  // CatalogEditor below or the raw-JSON "Advanced" textarea -- see catalogRawEdit.
  const [catalog, setCatalog] = useState<NicheCatalogCategory[]>(template.default_catalog);
  // null = textarea shows the JSON derived from `catalog`; a string = the user is mid-edit
  // in the raw textarea, which wins until it either parses (updating `catalog` too) or the
  // structured editor changes `catalog` again (which resets this back to null).
  const [catalogRawEdit, setCatalogRawEdit] = useState<string | null>(null);
  const [catalogRawError, setCatalogRawError] = useState<string | null>(null);
  const [terminologyJson, setTerminologyJson] = useState(jsonField(template.terminology));
  const [modulesJson, setModulesJson] = useState(jsonField(template.default_modules));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [flowSaving, setFlowSaving] = useState(false);
  const [flowError, setFlowError] = useState<string | null>(null);

  function setCatalogFromStructured(next: NicheCatalogCategory[]) {
    setCatalog(next);
    // The structured editor is now the latest edit -- drop any stale raw-textarea buffer
    // so it re-derives from `catalog` instead of overwriting this change on next render.
    setCatalogRawEdit(null);
    setCatalogRawError(null);
  }

  async function save() {
    setSaving(true);
    setError(null);
    try {
      let defaultCatalog: NicheCatalogCategory[] = catalog;
      let terminology, defaultModules;
      try {
        if (catalogRawEdit !== null) defaultCatalog = JSON.parse(catalogRawEdit);
        terminology = JSON.parse(terminologyJson);
        defaultModules = JSON.parse(modulesJson);
      } catch {
        setError("One of the JSON fields below isn't valid JSON -- fix the syntax and try again.");
        setSaving(false);
        return;
      }
      await apiFetch(`/niche-templates/${template.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          name, action_type: actionType, icon: icon || null, welcome_message: welcomeMessage,
          welcome_banner_image: welcomeBannerImage || null,
          default_catalog: defaultCatalog, terminology, default_modules: defaultModules,
        }),
      });
      onSaved();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  }

  async function saveFlow(steps: FlowStep[], entryStepId: string, uiLayout: Record<string, { x: number; y: number }>) {
    setFlowSaving(true);
    setFlowError(null);
    try {
      // NicheTemplate has no separate entry_step_id field -- niche_provisioning.py and
      // this router's own _validate_flow_steps both always treat default_flow_steps[0]
      // as the entry step, so the chosen entry step must be moved to index 0.
      const reordered = [
        ...steps.filter((s) => s.step_id === entryStepId),
        ...steps.filter((s) => s.step_id !== entryStepId),
      ];
      await apiFetch(`/niche-templates/${template.id}`, {
        method: "PATCH",
        body: JSON.stringify({ default_flow_steps: reordered, default_ui_layout: uiLayout }),
      });
      onSaved();
    } catch (err) {
      setFlowError(err instanceof ApiError ? err.message : "Failed to save flow");
    } finally {
      setFlowSaving(false);
    }
  }

  return (
    <div className="space-y-4 rounded-lg border border-slate-200 p-4">
      {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-xs font-medium text-slate-500">Code</label>
          <p className="rounded-md bg-slate-50 px-3 py-1.5 text-sm text-slate-500">{template.code}</p>
        </div>
        <div>
          <label className="block text-xs font-medium text-slate-500">Icon (emoji)</label>
          <input value={icon} onChange={(e) => setIcon(e.target.value)} className="w-20 rounded-md border border-slate-300 px-3 py-1.5 text-sm" />
        </div>
        <div>
          <label className="block text-xs font-medium text-slate-500">Name</label>
          <input value={name} onChange={(e) => setName(e.target.value)} className="w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm" />
        </div>
        <div>
          <label className="block text-xs font-medium text-slate-500">Action type</label>
          <select value={actionType} onChange={(e) => setActionType(e.target.value as typeof actionType)} className="w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm">
            {ACTION_TYPES.map((t) => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>
        </div>
        <div className="col-span-2">
          <label className="block text-xs font-medium text-slate-500">Welcome message</label>
          <textarea rows={2} value={welcomeMessage} onChange={(e) => setWelcomeMessage(e.target.value)} className="w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm" />
        </div>
        <div className="col-span-2">
          <TemplateImageUpload label="Welcome banner image" value={welcomeBannerImage} onChange={setWelcomeBannerImage} />
        </div>
      </div>

      <div className="rounded-md border border-slate-100 bg-slate-50 p-3">
        <p className="text-xs font-medium text-slate-600">Default flow</p>
        <p className="mt-1 text-xs text-slate-400">
          What a new business starts with -- drag to arrange, click a step to edit it, drag from a node&apos;s
          handle to connect steps. A business&apos;s own copy is edited from Home Builder / Flow Builder after
          they sign up; this only sets the starting point.
        </p>
        <div className="mt-2">
          <FlowGraphEditor
            steps={template.default_flow_steps}
            entryStepId={template.default_flow_steps[0]?.step_id || "welcome"}
            uiLayout={template.default_ui_layout}
            apiEndpoints={apiEndpoints}
            saving={flowSaving}
            error={flowError}
            onSave={saveFlow}
          />
        </div>
      </div>

      <div className="rounded-md border border-slate-100 bg-slate-50 p-3">
        <p className="text-xs font-medium text-slate-600">Default catalog</p>
        <p className="mt-1 text-xs text-slate-400">
          Every category and item a new business starts with -- edit names, prices, and photos below. Photos
          upload straight to permanent storage; nothing here needs a deploy.
        </p>
        <div className="mt-2">
          <CatalogEditor catalog={catalog} onChange={setCatalogFromStructured} />
        </div>
      </div>

      <details className="rounded-md border border-slate-100 bg-slate-50 p-3">
        <summary className="cursor-pointer text-xs font-medium text-slate-600">
          Advanced: raw JSON (bulk edits, terminology, modules)
        </summary>
        <div className="mt-2 space-y-3">
          <div>
            <label className="block text-xs font-medium text-slate-500">default_catalog</label>
            <textarea
              rows={6}
              value={catalogRawEdit ?? jsonField(catalog)}
              onChange={(e) => {
                setCatalogRawEdit(e.target.value);
                try {
                  setCatalog(JSON.parse(e.target.value));
                  setCatalogRawError(null);
                } catch {
                  setCatalogRawError("Not valid JSON yet -- the structured editor above won't update until this parses.");
                }
              }}
              className="w-full rounded-md border border-slate-300 px-3 py-1.5 font-mono text-xs"
            />
            {catalogRawError && <p className="mt-1 text-xs text-amber-600">{catalogRawError}</p>}
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-500">terminology</label>
            <textarea rows={4} value={terminologyJson} onChange={(e) => setTerminologyJson(e.target.value)} className="w-full rounded-md border border-slate-300 px-3 py-1.5 font-mono text-xs" />
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-500">default_modules</label>
            <textarea rows={3} value={modulesJson} onChange={(e) => setModulesJson(e.target.value)} className="w-full rounded-md border border-slate-300 px-3 py-1.5 font-mono text-xs" />
          </div>
        </div>
      </details>

      <button onClick={save} disabled={saving} className="rounded-md bg-primary px-4 py-1.5 text-sm font-medium text-white disabled:opacity-60">
        {saving ? "Saving..." : "Save niche"}
      </button>
    </div>
  );
}

export default function NichesPage() {
  const { user } = useAuth();
  const [templates, setTemplates] = useState<NicheTemplateSummary[]>([]);
  const [expanded, setExpanded] = useState<Record<string, NicheTemplateFull>>({});
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [apiEndpoints, setApiEndpoints] = useState<ApiEndpoint[]>([]);

  const [newCode, setNewCode] = useState("");
  const [newName, setNewName] = useState("");
  const [newActionType, setNewActionType] = useState<typeof ACTION_TYPES[number]>("order");
  const [creating, setCreating] = useState(false);

  const isSuperAdmin = user?.role === "super_admin";

  async function load() {
    setLoading(true);
    try {
      setTemplates(await apiFetch<NicheTemplateSummary[]>("/niche-templates"));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load niches");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (isSuperAdmin) {
      load();
      apiFetch<ApiEndpoint[]>("/api-endpoints").then(setApiEndpoints).catch(() => setApiEndpoints([]));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isSuperAdmin]);

  async function toggleExpand(id: string) {
    if (expandedId === id) {
      setExpandedId(null);
      return;
    }
    setExpandedId(id);
    if (!expanded[id]) {
      try {
        const full = await apiFetch<NicheTemplateFull>(`/niche-templates/${id}`);
        setExpanded((prev) => ({ ...prev, [id]: full }));
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Failed to load niche detail");
      }
    }
  }

  async function handleCreate(e: FormEvent) {
    e.preventDefault();
    setCreating(true);
    setError(null);
    try {
      await apiFetch("/niche-templates", {
        method: "POST",
        body: JSON.stringify({
          code: newCode, name: newName, action_type: newActionType,
          welcome_message: `Welcome to {{restaurant_name}}!`,
          default_flow_steps: [
            {
              step_id: "welcome", type: "menu_select", prompt: "Welcome to {{restaurant_name}}!",
              buttons_from: "static", static_options: [{ id: "welcome:start", title: "Get Started" }],
              routes: {}, next: null, back_target: null,
            },
          ],
        }),
      });
      setNewCode("");
      setNewName("");
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to create niche");
    } finally {
      setCreating(false);
    }
  }

  async function handleDelete(id: string) {
    if (!window.confirm("Delete this niche? Businesses already using it are unaffected -- it just won't be offered to new businesses anymore.")) return;
    try {
      await apiFetch(`/niche-templates/${id}`, { method: "DELETE" });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to delete niche");
    }
  }

  if (!isSuperAdmin) {
    return <p className="text-sm text-slate-500">Only Super Admins can manage niches.</p>;
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Niches</h1>
        <p className="mt-1 text-sm text-slate-500">
          What a new business starts with when they pick a niche during onboarding -- add a new niche or edit
          an existing one, no deploy needed.
        </p>
      </div>
      {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

      <DemoBotPanel />

      <form onSubmit={handleCreate} className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-end gap-3">
          <div>
            <label className="block text-xs font-medium text-slate-500">Code</label>
            <input required placeholder="e.g. pet_grooming" value={newCode} onChange={(e) => setNewCode(e.target.value)} className="w-48 rounded-md border border-slate-300 px-3 py-1.5 text-sm" />
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-500">Name</label>
            <input required placeholder="e.g. Pet Grooming" value={newName} onChange={(e) => setNewName(e.target.value)} className="w-48 rounded-md border border-slate-300 px-3 py-1.5 text-sm" />
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-500">Action type</label>
            <select value={newActionType} onChange={(e) => setNewActionType(e.target.value as typeof ACTION_TYPES[number])} className="rounded-md border border-slate-300 px-3 py-1.5 text-sm">
              {ACTION_TYPES.map((t) => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
          </div>
          <button type="submit" disabled={creating} className="rounded-md bg-primary px-4 py-1.5 text-sm font-medium text-white disabled:opacity-60">
            {creating ? "Creating..." : "+ New niche"}
          </button>
        </div>
        <p className="mt-2 text-xs text-slate-400">
          Starts with a minimal one-button welcome flow -- expand it below to fill in the real default catalog
          and flow steps.
        </p>
      </form>

      {loading ? (
        <p className="text-sm text-slate-500">Loading...</p>
      ) : (
        <div className="space-y-3">
          {templates.map((t) => (
            <div key={t.id} className="rounded-xl border border-slate-200 bg-white shadow-sm">
              <div className="flex items-center justify-between px-5 py-3">
                <button type="button" onClick={() => toggleExpand(t.id)} className="flex-1 text-left">
                  <span className="mr-2">{t.icon}</span>
                  <span className="font-medium text-slate-800">{t.name}</span>
                  <span className="ml-2 font-mono text-xs text-slate-400">{t.code}</span>
                  <span className="ml-2 rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-500">{t.action_type}</span>
                </button>
                <button onClick={() => handleDelete(t.id)} className="text-xs font-medium text-red-600 hover:text-red-700">
                  Delete
                </button>
              </div>
              {expandedId === t.id && (
                <div className="border-t border-slate-100 p-4">
                  {expanded[t.id] ? (
                    <TemplateEditor
                      template={expanded[t.id]}
                      apiEndpoints={apiEndpoints}
                      onSaved={async () => {
                        const full = await apiFetch<NicheTemplateFull>(`/niche-templates/${t.id}`);
                        setExpanded((prev) => ({ ...prev, [t.id]: full }));
                        await load();
                      }}
                    />
                  ) : (
                    <p className="text-sm text-slate-400">Loading...</p>
                  )}
                </div>
              )}
            </div>
          ))}
          {templates.length === 0 && <p className="text-sm text-slate-400">No niches yet.</p>}
        </div>
      )}
    </div>
  );
}
