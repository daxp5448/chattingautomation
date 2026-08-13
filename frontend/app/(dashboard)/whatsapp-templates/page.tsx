"use client";

import { useEffect, useState, type FormEvent } from "react";
import { apiFetch, ApiError } from "@/lib/api";
import { RequireRestaurant } from "@/components/RequireRestaurant";
import { WhatsAppFlowToggle } from "@/components/WhatsAppFlowToggle";
import { useCurrentRestaurant } from "@/lib/restaurant";
import type { WhatsAppTemplate } from "@/lib/types";

const STATUS_STYLES: Record<WhatsAppTemplate["status"], string> = {
  draft: "bg-slate-100 text-slate-600",
  pending: "bg-amber-100 text-amber-700",
  approved: "bg-emerald-100 text-emerald-700",
  rejected: "bg-red-100 text-red-700",
  disabled: "bg-slate-200 text-slate-500",
};

function parseExamples(raw: string): string[] {
  return raw.split(",").map((s) => s.trim()).filter(Boolean);
}

function TemplateRow({ template, restaurantId, onChanged }: { template: WhatsAppTemplate; restaurantId: string; onChanged: () => void }) {
  const { hasFeature } = useCurrentRestaurant();
  const canManage = hasFeature("whatsapp_template_manager");
  const editable = template.status === "draft" || template.status === "rejected";
  const [editing, setEditing] = useState(false);
  const [bodyText, setBodyText] = useState(template.body_text);
  const [examples, setExamples] = useState(template.variable_examples.join(", "));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [testing, setTesting] = useState(false);
  const [testPhone, setTestPhone] = useState("");
  const [testValues, setTestValues] = useState(template.variable_examples.join(", "));

  async function save() {
    setSaving(true);
    setError(null);
    try {
      await apiFetch(`/restaurants/${restaurantId}/whatsapp-templates/${template.id}`, {
        method: "PATCH",
        body: JSON.stringify({ body_text: bodyText, variable_examples: parseExamples(examples) }),
      });
      setEditing(false);
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  }

  async function submit() {
    setSaving(true);
    setError(null);
    try {
      await apiFetch(`/restaurants/${restaurantId}/whatsapp-templates/${template.id}/submit`, { method: "POST" });
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to submit for review");
    } finally {
      setSaving(false);
    }
  }

  async function remove() {
    if (!window.confirm(`Delete template "${template.name}"?`)) return;
    setSaving(true);
    setError(null);
    try {
      await apiFetch(`/restaurants/${restaurantId}/whatsapp-templates/${template.id}`, { method: "DELETE" });
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to delete");
      setSaving(false);
    }
  }

  async function sendTest(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await apiFetch(`/restaurants/${restaurantId}/whatsapp-templates/${template.id}/test-send`, {
        method: "POST",
        body: JSON.stringify({ to_phone: testPhone, variable_values: parseExamples(testValues) }),
      });
      setTesting(false);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Test send failed");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <span className="font-mono text-sm font-medium text-slate-800">{template.name}</span>
            <span className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${STATUS_STYLES[template.status]}`}>{template.status}</span>
            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-500">{template.category}</span>
            <span className="text-[11px] text-slate-400">{template.language}</span>
          </div>
          <p className="mt-1 text-sm text-slate-600">{template.body_text}</p>
          {template.rejection_reason && (
            <p className="mt-1 text-xs text-red-600">Rejected: {template.rejection_reason}</p>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          {editable && canManage && (
            <button onClick={() => setEditing((v) => !v)} className="rounded-md border border-slate-300 px-3 py-1 text-xs font-medium text-slate-700 hover:bg-slate-50">
              {editing ? "Cancel" : "Edit"}
            </button>
          )}
          {editable && canManage && (
            <button onClick={submit} disabled={saving} className="rounded-md bg-primary px-3 py-1 text-xs font-medium text-white disabled:opacity-60">
              Submit for review
            </button>
          )}
          {template.status === "approved" && canManage && (
            <button onClick={() => setTesting((v) => !v)} className="rounded-md border border-slate-300 px-3 py-1 text-xs font-medium text-slate-700 hover:bg-slate-50">
              Send test
            </button>
          )}
          <button onClick={remove} disabled={saving} className="rounded-md border border-red-200 px-3 py-1 text-xs font-medium text-red-600 hover:bg-red-50">
            Delete
          </button>
        </div>
      </div>

      {!canManage && (
        <p className="mt-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          The WhatsApp Template Manager isn&apos;t included in this business&apos;s plan -- editing, submitting,
          and test-sending are unavailable. Existing templates are unaffected.
        </p>
      )}

      {error && <p className="mt-2 rounded-lg bg-red-50 px-3 py-2 text-xs text-red-700">{error}</p>}

      {editing && (
        <div className="mt-3 space-y-2 rounded-lg bg-slate-50 p-3">
          <div>
            <label className="block text-xs font-medium text-slate-500">Body (use {"{{1}}"}, {"{{2}}"}, ... for placeholders)</label>
            <textarea rows={2} value={bodyText} onChange={(e) => setBodyText(e.target.value)} className="w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm" />
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-500">Variable examples (comma separated, in {"{{1}}"} order)</label>
            <input value={examples} onChange={(e) => setExamples(e.target.value)} placeholder="Asha, ORD123" className="w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm" />
          </div>
          <button onClick={save} disabled={saving} className="rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-white disabled:opacity-60">
            {saving ? "Saving..." : "Save"}
          </button>
        </div>
      )}

      {testing && (
        <form onSubmit={sendTest} className="mt-3 flex flex-wrap items-end gap-2 rounded-lg bg-slate-50 p-3">
          <div>
            <label className="block text-xs font-medium text-slate-500">Send to phone (with country code)</label>
            <input required value={testPhone} onChange={(e) => setTestPhone(e.target.value)} placeholder="919876543210" className="w-40 rounded-md border border-slate-300 px-3 py-1.5 text-sm" />
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-500">Variable values (comma separated)</label>
            <input value={testValues} onChange={(e) => setTestValues(e.target.value)} className="w-64 rounded-md border border-slate-300 px-3 py-1.5 text-sm" />
          </div>
          <button type="submit" disabled={saving} className="rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-white disabled:opacity-60">
            {saving ? "Sending..." : "Send"}
          </button>
        </form>
      )}
    </div>
  );
}

function WhatsAppTemplatesForRestaurant({ restaurantId }: { restaurantId: string }) {
  const { hasFeature } = useCurrentRestaurant();
  const canManage = hasFeature("whatsapp_template_manager");
  const [templates, setTemplates] = useState<WhatsAppTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [category, setCategory] = useState<WhatsAppTemplate["category"]>("utility");
  const [language, setLanguage] = useState("en_US");
  const [bodyText, setBodyText] = useState("");
  const [examples, setExamples] = useState("");
  const [creating, setCreating] = useState(false);

  async function load() {
    setLoading(true);
    try {
      setTemplates(await apiFetch<WhatsAppTemplate[]>(`/restaurants/${restaurantId}/whatsapp-templates`));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load templates");
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
      await apiFetch(`/restaurants/${restaurantId}/whatsapp-templates`, {
        method: "POST",
        body: JSON.stringify({
          name, category, language, body_text: bodyText, variable_examples: parseExamples(examples),
        }),
      });
      setName("");
      setBodyText("");
      setExamples("");
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to create template");
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">WhatsApp Templates</h1>
        <p className="mt-1 max-w-2xl text-sm text-slate-500">
          Meta requires an approved Message Template to message a customer outside a 24-hour reply window. Create a
          draft, submit it for review, then send a test once it&apos;s approved.
        </p>
      </div>
      {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
      <WhatsAppFlowToggle restaurantId={restaurantId} />
      {!canManage && (
        <p className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          The WhatsApp Template Manager isn&apos;t included in this business&apos;s plan -- contact support to
          upgrade. Existing templates below are unaffected.
        </p>
      )}

      {canManage && (
      <form onSubmit={handleCreate} className="space-y-3 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <div className="flex flex-wrap items-end gap-3">
          <div>
            <label className="block text-xs font-medium text-slate-500">Name (lowercase_with_underscores)</label>
            <input required value={name} onChange={(e) => setName(e.target.value)} placeholder="order_confirmation" className="w-56 rounded-md border border-slate-300 px-3 py-1.5 font-mono text-sm" />
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-500">Category</label>
            <select value={category} onChange={(e) => setCategory(e.target.value as WhatsAppTemplate["category"])} className="rounded-md border border-slate-300 px-3 py-1.5 text-sm">
              <option value="utility">Utility</option>
              <option value="marketing">Marketing</option>
              <option value="authentication">Authentication</option>
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-500">Language</label>
            <input required value={language} onChange={(e) => setLanguage(e.target.value)} placeholder="en_US" className="w-24 rounded-md border border-slate-300 px-3 py-1.5 text-sm" />
          </div>
        </div>
        <div>
          <label className="block text-xs font-medium text-slate-500">Body (use {"{{1}}"}, {"{{2}}"}, ... for placeholders)</label>
          <textarea required rows={2} value={bodyText} onChange={(e) => setBodyText(e.target.value)} placeholder="Hi {{1}}, your order {{2}} is confirmed." className="w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm" />
        </div>
        <div>
          <label className="block text-xs font-medium text-slate-500">Variable examples (comma separated, in {"{{1}}"} order)</label>
          <input value={examples} onChange={(e) => setExamples(e.target.value)} placeholder="Asha, ORD123" className="w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm" />
        </div>
        <button type="submit" disabled={creating} className="rounded-md bg-primary px-4 py-1.5 text-sm font-medium text-white shadow-sm disabled:opacity-60">
          {creating ? "Creating..." : "+ Create draft template"}
        </button>
      </form>
      )}

      {loading ? (
        <p className="text-sm text-slate-500">Loading...</p>
      ) : (
        <div className="space-y-3">
          {templates.map((t) => (
            <TemplateRow key={t.id} template={t} restaurantId={restaurantId} onChanged={load} />
          ))}
          {templates.length === 0 && <p className="text-sm text-slate-400">No templates yet.</p>}
        </div>
      )}
    </div>
  );
}

export default function WhatsAppTemplatesPage() {
  return <RequireRestaurant>{(restaurantId) => <WhatsAppTemplatesForRestaurant restaurantId={restaurantId} />}</RequireRestaurant>;
}
