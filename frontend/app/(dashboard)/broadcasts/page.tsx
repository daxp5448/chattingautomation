"use client";

import { useEffect, useState, type FormEvent } from "react";
import { apiFetch, ApiError } from "@/lib/api";
import { RequireRestaurant } from "@/components/RequireRestaurant";
import { useCurrentRestaurant } from "@/lib/restaurant";
import type { BroadcastCampaign, SegmentPreview, TemplateRecommendations, WhatsAppTemplate } from "@/lib/types";

const STATUS_STYLES: Record<BroadcastCampaign["status"], string> = {
  draft: "bg-slate-100 text-slate-600",
  scheduled: "bg-blue-100 text-blue-700",
  sending: "bg-amber-100 text-amber-700",
  completed: "bg-emerald-100 text-emerald-700",
  failed: "bg-red-100 text-red-700",
  cancelled: "bg-slate-200 text-slate-500",
};

function parseList(raw: string): string[] {
  return raw.split(",").map((s) => s.trim()).filter(Boolean);
}

function CampaignRow({ campaign, restaurantId, onChanged }: { campaign: BroadcastCampaign; restaurantId: string; onChanged: () => void }) {
  const { hasFeature } = useCurrentRestaurant();
  const canManage = hasFeature("broadcasts");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState<number | null>(null);

  async function loadPreview() {
    try {
      const p = await apiFetch<SegmentPreview>(`/restaurants/${restaurantId}/broadcasts/${campaign.id}/segment-preview`);
      setPreview(p.matching_customers);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to preview segment");
    }
  }

  async function start() {
    if (!window.confirm(`Start "${campaign.name}"? This will begin sending real WhatsApp messages.`)) return;
    setBusy(true);
    setError(null);
    try {
      await apiFetch(`/restaurants/${restaurantId}/broadcasts/${campaign.id}/start`, { method: "POST" });
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to start campaign");
    } finally {
      setBusy(false);
    }
  }

  async function cancel() {
    setBusy(true);
    setError(null);
    try {
      await apiFetch(`/restaurants/${restaurantId}/broadcasts/${campaign.id}/cancel`, { method: "POST" });
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to cancel campaign");
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!window.confirm(`Delete draft campaign "${campaign.name}"?`)) return;
    setBusy(true);
    setError(null);
    try {
      await apiFetch(`/restaurants/${restaurantId}/broadcasts/${campaign.id}`, { method: "DELETE" });
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to delete campaign");
      setBusy(false);
    }
  }

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <span className="font-medium text-slate-800">{campaign.name}</span>
            <span className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${STATUS_STYLES[campaign.status]}`}>{campaign.status}</span>
          </div>
          <p className="mt-1 text-xs text-slate-500">
            Segment: {campaign.segment_tags.length ? campaign.segment_tags.join(", ") : "all customers"}
            {campaign.scheduled_at && <> · Scheduled for {new Date(campaign.scheduled_at).toLocaleString()}</>}
          </p>
          {campaign.total_recipients > 0 && (
            <p className="mt-1 text-xs text-slate-600">
              {campaign.sent_count} sent / {campaign.failed_count} failed / {campaign.total_recipients} total
            </p>
          )}
          {campaign.failure_reason && <p className="mt-1 text-xs text-red-600">{campaign.failure_reason}</p>}
          {preview !== null && campaign.status === "draft" && (
            <p className="mt-1 text-xs text-slate-500">Currently matches {preview} customer(s)</p>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          {campaign.status === "draft" && (
            <button onClick={loadPreview} className="rounded-md border border-slate-300 px-3 py-1 text-xs font-medium text-slate-700 hover:bg-slate-50">
              Preview segment
            </button>
          )}
          {campaign.status === "draft" && (
            <button
              onClick={start}
              disabled={busy || !canManage}
              title={canManage ? undefined : "Broadcasts aren't included in this business's plan"}
              className="rounded-md bg-primary px-3 py-1 text-xs font-medium text-white disabled:opacity-60"
            >
              Start
            </button>
          )}
          {(campaign.status === "scheduled" || campaign.status === "sending") && (
            <button onClick={cancel} disabled={busy} className="rounded-md border border-red-200 px-3 py-1 text-xs font-medium text-red-600 hover:bg-red-50">
              Cancel
            </button>
          )}
          {campaign.status === "draft" && (
            <button onClick={remove} disabled={busy} className="rounded-md border border-red-200 px-3 py-1 text-xs font-medium text-red-600 hover:bg-red-50">
              Delete
            </button>
          )}
        </div>
      </div>
      {error && <p className="mt-2 rounded-lg bg-red-50 px-3 py-2 text-xs text-red-700">{error}</p>}
    </div>
  );
}

function BroadcastsForRestaurant({ restaurantId }: { restaurantId: string }) {
  const { hasFeature } = useCurrentRestaurant();
  const canManage = hasFeature("broadcasts");
  const [campaigns, setCampaigns] = useState<BroadcastCampaign[]>([]);
  const [templates, setTemplates] = useState<WhatsAppTemplate[]>([]);
  const [recommendations, setRecommendations] = useState<TemplateRecommendations | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [templateId, setTemplateId] = useState("");
  const [segmentTags, setSegmentTags] = useState("");
  const [variableTemplate, setVariableTemplate] = useState("");
  const [scheduledAt, setScheduledAt] = useState("");
  const [creating, setCreating] = useState(false);

  const approvedTemplates = templates.filter((t) => t.status === "approved");
  // Recommended-for-this-niche ids first (in recommendation order), then everything else
  // approved -- see template_purpose_mapping.py; a template can be recommended for at
  // most one purpose, so no duplicate entries across the two groups.
  const recommendedIds = new Set(Object.values(recommendations || {}).filter((t): t is WhatsAppTemplate => !!t).map((t) => t.id));
  const recommendedTemplates = approvedTemplates.filter((t) => recommendedIds.has(t.id));
  const otherTemplates = approvedTemplates.filter((t) => !recommendedIds.has(t.id));

  async function load() {
    setLoading(true);
    try {
      const [c, t, r] = await Promise.all([
        apiFetch<BroadcastCampaign[]>(`/restaurants/${restaurantId}/broadcasts`),
        apiFetch<WhatsAppTemplate[]>(`/restaurants/${restaurantId}/whatsapp-templates`),
        apiFetch<TemplateRecommendations>(`/restaurants/${restaurantId}/whatsapp-templates/recommendations`),
      ]);
      setCampaigns(c);
      setTemplates(t);
      setRecommendations(r);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load broadcasts");
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
      await apiFetch(`/restaurants/${restaurantId}/broadcasts`, {
        method: "POST",
        body: JSON.stringify({
          name, template_id: templateId, segment_tags: parseList(segmentTags),
          variable_template: parseList(variableTemplate),
          scheduled_at: scheduledAt ? new Date(scheduledAt).toISOString() : null,
        }),
      });
      setName("");
      setTemplateId("");
      setSegmentTags("");
      setVariableTemplate("");
      setScheduledAt("");
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to create campaign");
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Broadcasts</h1>
        <p className="mt-1 max-w-2xl text-sm text-slate-500">
          Send an approved WhatsApp template to a segment of your customers. Only customers who opted in to
          marketing messages are eligible for a Marketing-category template. A daily send cap (set in Business
          settings) protects your WhatsApp number from Meta&apos;s messaging limits.
        </p>
      </div>
      {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
      {!canManage && (
        <p className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          Broadcasts aren&apos;t included in this business&apos;s plan -- contact support to upgrade. Existing
          campaigns below are unaffected.
        </p>
      )}

      {approvedTemplates.length === 0 && !loading && (
        <p className="rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-700">
          No approved WhatsApp templates yet -- create and submit one on the WhatsApp Templates page first.
        </p>
      )}

      {canManage && (
      <form onSubmit={handleCreate} className="space-y-3 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <div className="flex flex-wrap items-end gap-3">
          <div>
            <label className="block text-xs font-medium text-slate-500">Campaign name</label>
            <input required value={name} onChange={(e) => setName(e.target.value)} placeholder="Diwali offer" className="w-56 rounded-md border border-slate-300 px-3 py-1.5 text-sm" />
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-500">Template (approved only)</label>
            <select required value={templateId} onChange={(e) => setTemplateId(e.target.value)} className="w-56 rounded-md border border-slate-300 px-3 py-1.5 text-sm">
              <option value="">Select a template</option>
              {recommendedTemplates.length > 0 && (
                <optgroup label="⭐ Recommended for your business">
                  {recommendedTemplates.map((t) => (
                    <option key={t.id} value={t.id}>{t.name} ({t.category})</option>
                  ))}
                </optgroup>
              )}
              {otherTemplates.length > 0 && (
                <optgroup label={recommendedTemplates.length > 0 ? "Other templates" : "Templates"}>
                  {otherTemplates.map((t) => (
                    <option key={t.id} value={t.id}>{t.name} ({t.category})</option>
                  ))}
                </optgroup>
              )}
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-500">Schedule for (optional)</label>
            <input type="datetime-local" value={scheduledAt} onChange={(e) => setScheduledAt(e.target.value)} className="rounded-md border border-slate-300 px-3 py-1.5 text-sm" />
          </div>
        </div>
        <div>
          <label className="block text-xs font-medium text-slate-500">Segment tags (comma separated, blank = all customers)</label>
          <input value={segmentTags} onChange={(e) => setSegmentTags(e.target.value)} placeholder="vip, regular" className="w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm" />
        </div>
        <div>
          <label className="block text-xs font-medium text-slate-500">
            Variable values (comma separated, in {"{{1}}"} order -- use the literal text <code>{"{{customer_name}}"}</code> to personalize)
          </label>
          <input value={variableTemplate} onChange={(e) => setVariableTemplate(e.target.value)} placeholder="{{customer_name}}, 20% OFF" className="w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm" />
        </div>
        <button type="submit" disabled={creating} className="rounded-md bg-primary px-4 py-1.5 text-sm font-medium text-white shadow-sm disabled:opacity-60">
          {creating ? "Creating..." : "+ Create draft campaign"}
        </button>
      </form>
      )}

      {loading ? (
        <p className="text-sm text-slate-500">Loading...</p>
      ) : (
        <div className="space-y-3">
          {campaigns.map((c) => (
            <CampaignRow key={c.id} campaign={c} restaurantId={restaurantId} onChanged={load} />
          ))}
          {campaigns.length === 0 && <p className="text-sm text-slate-400">No campaigns yet.</p>}
        </div>
      )}
    </div>
  );
}

export default function BroadcastsPage() {
  return <RequireRestaurant>{(restaurantId) => <BroadcastsForRestaurant restaurantId={restaurantId} />}</RequireRestaurant>;
}
