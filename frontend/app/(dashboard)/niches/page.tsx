"use client";

import { useEffect, useState, type FormEvent } from "react";
import { apiFetch, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { FlowGraphEditor } from "@/components/FlowGraphEditor";
import { TemplateImageUpload } from "@/components/TemplateImageUpload";
import type { ApiEndpoint, DemoBotStatus, FlowStep, NicheTemplateFull, NicheTemplateSummary } from "@/lib/types";

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
      <h2 className="text-sm font-semibold text-slate-800">Demo Bot</h2>
      <p className="mt-1 text-xs text-slate-500">
        The one WhatsApp number prospects can message to try any niche's bot -- see Bot Builder.
      </p>
      <p className="mt-3 text-sm">
        Demo number:{" "}
        {status.sentinel_configured ? (
          <span className="font-medium text-emerald-600">Configured</span>
        ) : (
          <span className="font-medium text-amber-600">
            Not configured -- create a restaurant with &quot;Demo Bot restaurant&quot; checked and a real WhatsApp number.
          </span>
        )}
      </p>
      <p className="mt-1 text-sm text-slate-600">
        {status.niches.length - missing.length} / {status.niches.length} niches have a demo restaurant provisioned.
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
  const [catalogJson, setCatalogJson] = useState(jsonField(template.default_catalog));
  // Not a real field -- a throwaway "get a URL, paste it into the JSON below" utility for
  // category/item images, since default_catalog isn't a structured per-image form yet.
  const [catalogImageUploadUrl, setCatalogImageUploadUrl] = useState("");
  const [terminologyJson, setTerminologyJson] = useState(jsonField(template.terminology));
  const [modulesJson, setModulesJson] = useState(jsonField(template.default_modules));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [flowSaving, setFlowSaving] = useState(false);
  const [flowError, setFlowError] = useState<string | null>(null);

  async function save() {
    setSaving(true);
    setError(null);
    try {
      let defaultCatalog, terminology, defaultModules;
      try {
        defaultCatalog = JSON.parse(catalogJson);
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

      <details className="rounded-md border border-slate-100 bg-slate-50 p-3">
        <summary className="cursor-pointer text-xs font-medium text-slate-600">
          Advanced: default catalog, terminology, modules (raw JSON)
        </summary>
        <div className="mt-2 space-y-3">
          <div>
            <TemplateImageUpload
              label="Upload a category/item photo -- copy the URL below into default_catalog's icon_image/images fields"
              value={catalogImageUploadUrl}
              onChange={setCatalogImageUploadUrl}
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-500">default_catalog</label>
            <textarea rows={6} value={catalogJson} onChange={(e) => setCatalogJson(e.target.value)} className="w-full rounded-md border border-slate-300 px-3 py-1.5 font-mono text-xs" />
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
