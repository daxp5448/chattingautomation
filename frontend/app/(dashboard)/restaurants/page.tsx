"use client";

import { useEffect, useState, type FormEvent } from "react";
import { apiFetch, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useCurrentRestaurant } from "@/lib/restaurant";
import type { AuditLogEntry, Branch, DisplayDevice, DisplayDeviceCreateResult, FeaturePackage, NicheTemplateSummary, Restaurant, RestaurantCreateResult } from "@/lib/types";
import { IconKey, IconDownload, IconGlobe, IconAlertTriangle, IconMonitor, IconSettings } from "@/components/icons";
import { TemplateImageUpload } from "@/components/TemplateImageUpload";

// Sentinel value for the Business type <select> -- distinct from "" (the unselectable
// placeholder) so a Super Admin has to deliberately pick THIS to get the legacy engine,
// rather than it being whatever's silently selected if they never touch the dropdown.
// See handleCreate, which converts this back to niche_code: null for the API.
const LEGACY_OPTION = "__legacy__";

const STATUS_STYLES: Record<string, string> = {
  active: "bg-emerald-100 text-emerald-700",
  onboarding: "bg-blue-100 text-blue-700",
  suspended: "bg-amber-100 text-amber-700",
  cancelled: "bg-slate-200 text-slate-600",
  pending_review: "bg-purple-100 text-purple-700",
};

function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_STYLES[status] ?? "bg-slate-100 text-slate-600"}`}>
      {status}
    </span>
  );
}

function slugify(name: string): string {
  return name
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

function NewOwnerCredentials({ result, onDismiss }: { result: RestaurantCreateResult; onDismiss: () => void }) {
  const [copied, setCopied] = useState(false);

  async function copyLink() {
    await navigator.clipboard.writeText(result.setup_url);
    setCopied(true);
  }

  return (
    <div className="rounded-lg border border-amber-300 bg-amber-50 p-4">
      <h3 className="font-medium text-amber-900">"{result.name}" is ready</h3>
      <p className="mt-1 text-sm text-amber-800">
        We've emailed this setup link to <span className="font-mono">{result.owner_email}</span> automatically
        (if email isn't configured yet, send it yourself — it's shown once here and can&apos;t be recovered
        afterward). It lets them choose their own password — no password to hand over or forget to change. It
        expires in 48 hours and can only be used once.
      </p>
      <dl className="mt-3 text-sm">
        <dt className="text-xs font-medium text-amber-700">One-time setup link</dt>
        <dd className="break-all font-mono">{result.setup_url}</dd>
      </dl>
      <div className="mt-3 flex gap-2">
        <button onClick={copyLink} className="rounded-md bg-amber-600 px-3 py-1.5 text-xs font-medium text-white">
          {copied ? "Copied!" : "Copy setup link"}
        </button>
        <button onClick={onDismiss} className="rounded-md border border-amber-400 px-3 py-1.5 text-xs font-medium text-amber-800">
          Done, I&apos;ve sent it
        </button>
      </div>
    </div>
  );
}

function NewDisplayLink({ result, restaurantId, onDismiss }: { result: DisplayDeviceCreateResult; restaurantId: string; onDismiss: () => void }) {
  const [copied, setCopied] = useState(false);
  const url = `${window.location.origin}/pos/${restaurantId}?token=${result.token}`;

  async function copyUrl() {
    await navigator.clipboard.writeText(url);
    setCopied(true);
  }

  return (
    <div className="rounded-lg border border-amber-300 bg-amber-50 p-4">
      <h3 className="font-medium text-amber-900">"{result.name}" display link is ready — save it now</h3>
      <p className="mt-1 text-sm text-amber-800">
        This URL is shown once and can&apos;t be recovered afterward. Open it on the tablet/screen you want live
        orders to show on, or send it to whoever is setting that device up.
      </p>
      <p className="mt-3 break-all rounded-md bg-white px-3 py-2 font-mono text-xs text-slate-700">{url}</p>
      <div className="mt-3 flex gap-2">
        <button onClick={copyUrl} className="rounded-md bg-amber-600 px-3 py-1.5 text-xs font-medium text-white">
          {copied ? "Copied!" : "Copy link"}
        </button>
        <button onClick={onDismiss} className="rounded-md border border-amber-400 px-3 py-1.5 text-xs font-medium text-amber-800">
          Done, I&apos;ve saved this
        </button>
      </div>
    </div>
  );
}

const STATUS_ACTIONS: Record<string, { to: "active" | "suspended" | "cancelled"; label: string; confirm: string; style: string }[]> = {
  active: [
    { to: "suspended", label: "Suspend", confirm: "Suspend this business? Its WhatsApp bot will stop taking orders immediately, but nothing is deleted -- reactivating brings it straight back.", style: "border border-amber-300 text-amber-700 hover:bg-amber-50" },
    { to: "cancelled", label: "Cancel", confirm: "Cancel this business? Its WhatsApp bot will stop taking orders. This is meant for a business that's left the platform -- you can still reactivate it later if they come back.", style: "border border-red-300 text-red-700 hover:bg-red-50" },
  ],
  onboarding: [
    { to: "suspended", label: "Suspend", confirm: "Suspend this business? Its WhatsApp bot will stop taking orders immediately, but nothing is deleted -- reactivating brings it straight back.", style: "border border-amber-300 text-amber-700 hover:bg-amber-50" },
    { to: "cancelled", label: "Cancel", confirm: "Cancel this business? Its WhatsApp bot will stop taking orders. This is meant for a business that's left the platform -- you can still reactivate it later if they come back.", style: "border border-red-300 text-red-700 hover:bg-red-50" },
  ],
  suspended: [
    { to: "active", label: "Reactivate", confirm: "Reactivate this business? Its WhatsApp bot will start taking orders again immediately.", style: "bg-emerald-600 text-white hover:bg-emerald-700" },
    { to: "cancelled", label: "Cancel instead", confirm: "Cancel this business instead of reactivating it? This is meant for a business that's left the platform -- you can still reactivate it later if they come back.", style: "border border-red-300 text-red-700 hover:bg-red-50" },
  ],
  cancelled: [
    { to: "active", label: "Reactivate", confirm: "Reactivate this cancelled business? Its WhatsApp bot will start taking orders again immediately.", style: "bg-emerald-600 text-white hover:bg-emerald-700" },
  ],
  pending_review: [
    { to: "active", label: "Approve", confirm: "Approve this business? Its WhatsApp bot will start taking real orders immediately. Its dashboard is already fully set up.", style: "bg-emerald-600 text-white hover:bg-emerald-700" },
    { to: "cancelled", label: "Reject", confirm: "Reject this signup? Its WhatsApp bot will never go live unless you approve it later. Nothing is deleted.", style: "border border-red-300 text-red-700 hover:bg-red-50" },
  ],
};

function trialLabel(trialEndsAt: string | null): { text: string; className: string } | null {
  if (!trialEndsAt) return null;
  const days = Math.ceil((new Date(trialEndsAt).getTime() - Date.now()) / 86_400_000);
  if (days < 0) return { text: `Trial ended ${Math.abs(days)} day${Math.abs(days) === 1 ? "" : "s"} ago`, className: "text-red-600" };
  if (days === 0) return { text: "Trial ends today", className: "text-red-600" };
  if (days <= 7) return { text: `Trial ends in ${days} day${days === 1 ? "" : "s"}`, className: "text-amber-600" };
  return { text: `Trial ends in ${days} days`, className: "text-slate-500" };
}

function SubscriptionSection({ restaurant, onChanged }: { restaurant: Restaurant; onChanged: () => void }) {
  const [log, setLog] = useState<AuditLogEntry[] | null>(null);
  const [showLog, setShowLog] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [trialDate, setTrialDate] = useState(restaurant.trial_ends_at ? restaurant.trial_ends_at.slice(0, 10) : "");
  const [savingTrial, setSavingTrial] = useState(false);
  const [exporting, setExporting] = useState(false);

  async function loadLog() {
    try {
      setLog(await apiFetch<AuditLogEntry[]>(`/restaurants/${restaurant.id}/audit-log`));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load activity log");
    }
  }

  async function setStatus(to: string, confirmMessage: string) {
    if (!window.confirm(confirmMessage)) return;
    setBusy(true);
    setError(null);
    try {
      await apiFetch(`/restaurants/${restaurant.id}`, { method: "PATCH", body: JSON.stringify({ status: to }) });
      onChanged();
      if (showLog) await loadLog();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to change status");
    } finally {
      setBusy(false);
    }
  }

  async function saveTrial() {
    setSavingTrial(true);
    setError(null);
    try {
      await apiFetch(`/restaurants/${restaurant.id}`, {
        method: "PATCH",
        body: JSON.stringify({ trial_ends_at: trialDate ? new Date(trialDate).toISOString() : null }),
      });
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to save trial date");
    } finally {
      setSavingTrial(false);
    }
  }

  async function exportData() {
    setExporting(true);
    setError(null);
    try {
      const data = await apiFetch<Record<string, unknown>>(`/restaurants/${restaurant.id}/export`);
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${restaurant.slug}-export-${new Date().toISOString().slice(0, 10)}.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to export data");
    } finally {
      setExporting(false);
    }
  }

  const actions = STATUS_ACTIONS[restaurant.status] ?? [];
  const trial = trialLabel(restaurant.trial_ends_at);

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <h3 className="flex items-center gap-2 font-medium text-slate-900"><IconKey size={15} /> Subscription</h3>
      <p className="mt-1 text-sm text-slate-500">
        Controls whether this business's WhatsApp bot is allowed to take orders. Nothing here deletes data --
        reactivating a suspended or cancelled business brings it back exactly as it was.
      </p>

      <div className="mt-3 flex items-center gap-3">
        <span className="text-xs font-medium text-slate-500">Current status</span>
        <StatusBadge status={restaurant.status} />
        {trial && <span className={`text-xs font-medium ${trial.className}`}>{trial.text}</span>}
      </div>

      {error && <p className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

      <div className="mt-3 flex flex-wrap gap-2">
        {actions.map((a) => (
          <button
            key={a.to}
            disabled={busy}
            onClick={() => setStatus(a.to, a.confirm)}
            className={`rounded-md px-3 py-1.5 text-xs font-medium disabled:opacity-60 ${a.style}`}
          >
            {a.label}
          </button>
        ))}
        <button
          disabled={exporting}
          onClick={exportData}
          className="flex items-center gap-1.5 rounded-md border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-60"
        >
          {exporting ? (
            "Exporting..."
          ) : (
            <>
              <IconDownload size={12} /> Export data
            </>
          )}
        </button>
        <button
          onClick={() => {
            setShowLog((v) => !v);
            if (!log) loadLog();
          }}
          className="ml-auto rounded-md border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50"
        >
          {showLog ? "Hide activity" : "View activity log"}
        </button>
      </div>

      <div className="mt-4 flex items-end gap-2 border-t border-slate-100 pt-3">
        <div>
          <label className="block text-xs font-medium text-slate-500">Trial / billing due date (optional)</label>
          <input
            type="date"
            value={trialDate}
            onChange={(e) => setTrialDate(e.target.value)}
            className="rounded-md border border-slate-300 px-3 py-1.5 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
          />
        </div>
        <button
          disabled={savingTrial}
          onClick={saveTrial}
          className="rounded-md border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-60"
        >
          {savingTrial ? "Saving..." : "Save date"}
        </button>
        <p className="pb-2 text-xs text-slate-400">Purely informational -- nothing auto-suspends when this passes.</p>
      </div>

      {showLog && (
        <div className="mt-3 space-y-1.5 border-t border-slate-100 pt-3">
          {log === null && <p className="text-xs text-slate-400">Loading...</p>}
          {log?.length === 0 && <p className="text-xs text-slate-400">No status changes recorded yet.</p>}
          {log?.map((entry) => (
            <p key={entry.id} className="text-xs text-slate-500">
              <span className="font-mono text-slate-400">{new Date(entry.created_at).toLocaleString()}</span>
              {" — "}
              {entry.diff.from && entry.diff.to
                ? `changed status from "${entry.diff.from}" to "${entry.diff.to}"`
                : entry.action}
            </p>
          ))}
        </div>
      )}
    </div>
  );
}

function DemoModeSection({ restaurant, onChanged }: { restaurant: Restaurant; onChanged: () => void }) {
  const [templates, setTemplates] = useState<NicheTemplateSummary[]>([]);
  const [selectedCodes, setSelectedCodes] = useState<string[]>(restaurant.demo_enabled_niche_codes ?? []);
  const [allNiches, setAllNiches] = useState(restaurant.demo_enabled_niche_codes === null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<NicheTemplateSummary[]>("/niche-templates").then(setTemplates).catch(() => setTemplates([]));
  }, []);

  useEffect(() => {
    setSelectedCodes(restaurant.demo_enabled_niche_codes ?? []);
    setAllNiches(restaurant.demo_enabled_niche_codes === null);
  }, [restaurant.id, restaurant.demo_enabled_niche_codes]);

  function toggleCode(code: string) {
    setSelectedCodes((prev) => (prev.includes(code) ? prev.filter((c) => c !== code) : [...prev, code]));
  }

  async function toggleEnabled() {
    const next = !restaurant.demo_mode_enabled;
    if (next && !window.confirm(
      `Turn on Industry Picker Mode for "${restaurant.name}"?\n\nAnyone who messages this business's connected WhatsApp number ` +
      `-- including real customers -- will see the multi-industry picker instead of ${restaurant.name}'s real menu/order ` +
      `flow, until you turn this back off.`
    )) {
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await apiFetch(`/restaurants/${restaurant.id}/demo-mode`, { method: "PATCH", body: JSON.stringify({ enabled: next }) });
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to toggle Industry Picker Mode");
    } finally {
      setSaving(false);
    }
  }

  async function saveNiches() {
    setSaving(true);
    setError(null);
    try {
      await apiFetch(`/restaurants/${restaurant.id}/demo-mode`, {
        method: "PATCH",
        body: JSON.stringify({ enabled: restaurant.demo_mode_enabled, niche_codes: allNiches ? null : selectedCodes }),
      });
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to save niche selection");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className={`rounded-xl border p-5 shadow-sm ${restaurant.demo_mode_enabled ? "border-violet-300 bg-violet-50" : "border-slate-200 bg-white"}`}>
      <div className="flex items-center justify-between">
        <div>
          <h3 className="flex items-center gap-2 font-medium text-slate-900"><IconGlobe size={15} /> Industry Picker Mode</h3>
          <p className="mt-1 text-sm text-slate-500">
            Temporarily repoint this business&apos;s own connected WhatsApp number at the multi-industry picker
            instead of its real order flow -- useful for showing the platform to prospects on a number that&apos;s
            already live. Turning this off restores normal order-taking immediately; no data is moved or deleted
            either way.
          </p>
        </div>
        <button
          onClick={toggleEnabled}
          disabled={saving || !restaurant.whatsapp_phone_number_id}
          title={restaurant.whatsapp_phone_number_id ? undefined : "Connect a WhatsApp number first (see Settings below)"}
          className={`shrink-0 rounded-md px-4 py-1.5 text-sm font-medium disabled:opacity-50 ${
            restaurant.demo_mode_enabled ? "bg-violet-600 text-white hover:bg-violet-700" : "border border-slate-300 text-slate-700 hover:bg-slate-50"
          }`}
        >
          {restaurant.demo_mode_enabled ? "Industry Picker: ON -- turn off" : "Turn on Industry Picker"}
        </button>
      </div>

      {restaurant.demo_mode_enabled && (
        <p className="mt-3 flex items-start gap-1.5 rounded-lg bg-violet-100 px-3 py-2 text-xs font-medium text-violet-800">
          <IconAlertTriangle size={13} className="mt-0.5 shrink-0" />
          Live right now: anyone messaging this number sees the industry picker, not {restaurant.name}&apos;s real menu.
        </p>
      )}
      {!restaurant.whatsapp_phone_number_id && (
        <p className="mt-3 text-xs text-amber-600">No WhatsApp number connected yet -- Industry Picker Mode needs a real number to route messages on.</p>
      )}
      {error && <p className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

      <div className="mt-4 border-t border-slate-200 pt-3">
        <p className="mb-2 text-xs font-medium text-slate-500">Which industries appear in the picker</p>
        <label className="flex items-center gap-1.5 text-sm text-slate-700">
          <input type="checkbox" checked={allNiches} onChange={(e) => setAllNiches(e.target.checked)} className="rounded border-slate-300" />
          Show all industries currently available
        </label>
        {!allNiches && (
          <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 sm:grid-cols-3">
            {templates.map((t) => (
              <label key={t.code} className="flex items-center gap-1.5 text-sm text-slate-700">
                <input type="checkbox" checked={selectedCodes.includes(t.code)} onChange={() => toggleCode(t.code)} className="rounded border-slate-300" />
                {t.icon} {t.name}
              </label>
            ))}
          </div>
        )}
        {!allNiches && selectedCodes.length === 0 && (
          <p className="mt-1 text-xs text-amber-600">No industries selected -- the picker will show "no industries configured" until you pick at least one.</p>
        )}
        <button onClick={saveNiches} disabled={saving} className="mt-3 rounded-md border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-60">
          {saving ? "Saving..." : "Save industry selection"}
        </button>
      </div>
    </div>
  );
}

function PosDisplaysSection({ restaurant }: { restaurant: Restaurant }) {
  const [devices, setDevices] = useState<DisplayDevice[]>([]);
  const [branches, setBranches] = useState<Branch[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [branchId, setBranchId] = useState("");
  const [creating, setCreating] = useState(false);
  const [newDevice, setNewDevice] = useState<DisplayDeviceCreateResult | null>(null);

  async function load() {
    setLoading(true);
    try {
      const [deviceData, branchData] = await Promise.all([
        apiFetch<DisplayDevice[]>(`/restaurants/${restaurant.id}/display-devices`),
        apiFetch<Branch[]>(`/restaurants/${restaurant.id}/branches`),
      ]);
      setDevices(deviceData);
      setBranches(branchData);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load POS displays");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [restaurant.id]);

  async function handleCreate(e: FormEvent) {
    e.preventDefault();
    setCreating(true);
    setError(null);
    try {
      const device = await apiFetch<DisplayDeviceCreateResult>(`/restaurants/${restaurant.id}/display-devices`, {
        method: "POST",
        body: JSON.stringify({ name, branch_id: branchId || null }),
      });
      setName("");
      setBranchId("");
      setNewDevice(device);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to create display link");
    } finally {
      setCreating(false);
    }
  }

  async function revoke(device: DisplayDevice) {
    if (!window.confirm(`Revoke "${device.name}"? Any screen still open with this link will stop updating immediately.`)) {
      return;
    }
    try {
      await apiFetch(`/restaurants/${restaurant.id}/display-devices/${device.id}`, { method: "DELETE" });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to revoke display link");
    }
  }

  return (
    <div className="space-y-4 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <div>
        <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-800"><IconMonitor size={15} /> POS Displays</h2>
        <p className="mt-1 text-xs text-slate-500">
          Generate a read-only link for a counter or kitchen screen -- it shows a live-updating order board without
          needing anyone to log in. Revoke a link instantly if a device is lost or replaced.
        </p>
      </div>

      {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
      {newDevice && <NewDisplayLink result={newDevice} restaurantId={restaurant.id} onDismiss={() => setNewDevice(null)} />}

      <form onSubmit={handleCreate} className="flex flex-wrap items-end gap-3">
        <div>
          <label className="block text-xs font-medium text-slate-500">Display name</label>
          <input
            required
            placeholder="e.g. Counter Screen"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="w-52 rounded-md border border-slate-300 px-3 py-1.5 text-sm"
          />
        </div>
        {branches.length > 0 && (
          <div>
            <label className="block text-xs font-medium text-slate-500">Branch (optional)</label>
            <select value={branchId} onChange={(e) => setBranchId(e.target.value)} className="rounded-md border border-slate-300 px-3 py-1.5 text-sm">
              <option value="">All branches</option>
              {branches.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name}
                </option>
              ))}
            </select>
          </div>
        )}
        <button type="submit" disabled={creating} className="rounded-md bg-primary px-4 py-1.5 text-sm font-medium text-white shadow-sm disabled:opacity-60">
          {creating ? "Creating..." : "+ New Display"}
        </button>
      </form>

      {loading ? (
        <p className="text-sm text-slate-500">Loading...</p>
      ) : (
        <div className="overflow-hidden rounded-lg border border-slate-200">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-2">Name</th>
                <th className="px-4 py-2">Created</th>
                <th className="px-4 py-2">Status</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody>
              {devices.map((d) => (
                <tr key={d.id} className="border-t border-slate-100">
                  <td className="px-4 py-2 font-medium text-slate-800">{d.name}</td>
                  <td className="px-4 py-2 text-slate-500">{new Date(d.created_at).toLocaleDateString()}</td>
                  <td className="px-4 py-2">
                    {d.revoked_at ? (
                      <span className="rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-700">Revoked</span>
                    ) : (
                      <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-700">Active</span>
                    )}
                  </td>
                  <td className="px-4 py-2 text-right">
                    {!d.revoked_at && (
                      <button onClick={() => revoke(d)} className="rounded-md border border-red-300 px-3 py-1 text-xs font-medium text-red-600 hover:bg-red-50">
                        Revoke
                      </button>
                    )}
                  </td>
                </tr>
              ))}
              {devices.length === 0 && (
                <tr>
                  <td colSpan={4} className="px-4 py-6 text-center text-slate-400">
                    No POS displays yet.
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

function SettingsPanel({ restaurant, onSaved }: { restaurant: Restaurant; onSaved: () => void }) {
  const [deliveryCharge, setDeliveryCharge] = useState(String(restaurant.delivery_charge));
  const [paymentMethods, setPaymentMethods] = useState<string[]>(restaurant.payment_methods);
  const [defaultPaymentMethod, setDefaultPaymentMethod] = useState(restaurant.default_payment_method);
  const [razorpayKeyId, setRazorpayKeyId] = useState(restaurant.razorpay_key_id || "");
  const [razorpayKeySecret, setRazorpayKeySecret] = useState("");
  const [razorpayWebhookSecret, setRazorpayWebhookSecret] = useState("");
  const [whatsappPhoneNumberId, setWhatsappPhoneNumberId] = useState(restaurant.whatsapp_phone_number_id || "");
  const [whatsappBusinessAccountId, setWhatsappBusinessAccountId] = useState(restaurant.whatsapp_business_account_id || "");
  const [whatsappCatalogId, setWhatsappCatalogId] = useState(restaurant.whatsapp_catalog_id || "");
  const [quickCustomizeFlowId, setQuickCustomizeFlowId] = useState(restaurant.whatsapp_quick_customize_flow_id || "");
  const [quickCustomizeFlowDraftMode, setQuickCustomizeFlowDraftMode] = useState(restaurant.whatsapp_quick_customize_flow_draft_mode);
  const [whatsappAccessToken, setWhatsappAccessToken] = useState("");
  const [coverImageUrl, setCoverImageUrl] = useState(restaurant.cover_image_url || "");
  const [logoUrl, setLogoUrl] = useState(restaurant.logo_url || "");
  const [pointsPerCurrency, setPointsPerCurrency] = useState(String(restaurant.loyalty_settings.points_per_currency_unit ?? 0));
  const [redemptionValue, setRedemptionValue] = useState(String(restaurant.loyalty_settings.redemption_value_per_point ?? 0));
  const [tone, setTone] = useState(restaurant.conversation_settings?.tone || "");
  const [language, setLanguage] = useState(restaurant.conversation_settings?.language || "auto");
  const [emojiLevel, setEmojiLevel] = useState(restaurant.conversation_settings?.emoji_level || "high");
  const [responseLength, setResponseLength] = useState(restaurant.conversation_settings?.response_length || "normal");
  const [businessPersonality, setBusinessPersonality] = useState(restaurant.conversation_settings?.business_personality || "");
  const [featurePackageId, setFeaturePackageId] = useState(restaurant.feature_package_id || "");
  const [featurePackages, setFeaturePackages] = useState<FeaturePackage[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<FeaturePackage[]>("/feature-packages").then(setFeaturePackages).catch(() => setFeaturePackages([]));
  }, []);

  useEffect(() => {
    setFeaturePackageId(restaurant.feature_package_id || "");
  }, [restaurant.feature_package_id]);

  function toggleMethod(method: string) {
    setPaymentMethods((prev) => (prev.includes(method) ? prev.filter((m) => m !== method) : [...prev, method]));
  }

  async function save() {
    setSaving(true);
    setError(null);
    try {
      const body: Record<string, unknown> = {
        delivery_charge: Number(deliveryCharge) || 0,
        payment_methods: paymentMethods,
        default_payment_method: defaultPaymentMethod,
        whatsapp_phone_number_id: whatsappPhoneNumberId || null,
        whatsapp_business_account_id: whatsappBusinessAccountId || null,
        whatsapp_catalog_id: whatsappCatalogId || null,
        whatsapp_quick_customize_flow_id: quickCustomizeFlowId || null,
        whatsapp_quick_customize_flow_draft_mode: quickCustomizeFlowDraftMode,
        cover_image_url: coverImageUrl || null,
        logo_url: logoUrl || null,
        loyalty_settings: {
          points_per_currency_unit: Number(pointsPerCurrency) || 0,
          redemption_value_per_point: Number(redemptionValue) || 0,
        },
        conversation_settings: {
          tone: tone || undefined,
          language: language,
          emoji_level: emojiLevel,
          response_length: responseLength,
          business_personality: businessPersonality || undefined,
        },
        feature_package_id: featurePackageId || null,
      };
      if (razorpayKeyId) body.razorpay_key_id = razorpayKeyId;
      if (razorpayKeySecret) body.razorpay_key_secret = razorpayKeySecret;
      if (razorpayWebhookSecret) body.razorpay_webhook_secret = razorpayWebhookSecret;
      if (whatsappAccessToken) body.whatsapp_access_token = whatsappAccessToken;

      await apiFetch(`/restaurants/${restaurant.id}`, { method: "PATCH", body: JSON.stringify(body) });
      setRazorpayKeySecret("");
      setRazorpayWebhookSecret("");
      setWhatsappAccessToken("");
      onSaved();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to save settings");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-6">
    <div className="space-y-5 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-800"><IconSettings size={15} /> Settings: {restaurant.name}</h2>
      {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

      <div>
        <label className="block text-xs font-medium text-slate-500">Delivery charge</label>
        <input type="number" step="0.01" value={deliveryCharge} onChange={(e) => setDeliveryCharge(e.target.value)} className="w-32 rounded-md border border-slate-300 px-3 py-1.5 text-sm" />
      </div>

      <div>
        <label className="block text-xs font-medium text-slate-500">Feature package</label>
        <select
          value={featurePackageId}
          onChange={(e) => setFeaturePackageId(e.target.value)}
          className="w-56 rounded-md border border-slate-300 px-3 py-1.5 text-sm"
        >
          <option value="">None (unrestricted)</option>
          {featurePackages.map((p) => (
            <option key={p.id} value={p.id}>{p.name}</option>
          ))}
        </select>
        <p className="mt-1 text-xs text-slate-400">
          Reassigning takes a fresh snapshot of that package&apos;s features -- editing the package itself later
          won&apos;t retroactively change this business. See /feature-packages.
        </p>
      </div>

      <div>
        <p className="mb-1 text-xs font-medium text-slate-500">Branding</p>
        <div className="grid grid-cols-2 gap-3">
          <TemplateImageUpload
            label="Cover image"
            value={coverImageUrl}
            onChange={setCoverImageUrl}
            endpoint={`/restaurants/${restaurant.id}/upload-image`}
          />
          <TemplateImageUpload
            label="Logo"
            value={logoUrl}
            onChange={setLogoUrl}
            endpoint={`/restaurants/${restaurant.id}/upload-image`}
          />
        </div>
        <p className="mt-1 text-xs text-slate-400">
          Upload a file (converted to a permanent public URL automatically), or paste one directly. Meta fetches this
          URL directly, so it must stay publicly reachable — uploaded images already satisfy that. If set, the cover
          image is sent as a photo right before the WhatsApp welcome menu.
        </p>
      </div>

      <div>
        <p className="mb-1 text-xs font-medium text-slate-500">Payment methods</p>
        <div className="flex gap-4 text-sm">
          {["cod", "razorpay"].map((method) => (
            <label key={method} className="flex items-center gap-1">
              <input type="checkbox" checked={paymentMethods.includes(method)} onChange={() => toggleMethod(method)} />
              {method.toUpperCase()}
            </label>
          ))}
        </div>
        <div className="mt-2">
          <label className="block text-xs font-medium text-slate-500">Default method</label>
          <select value={defaultPaymentMethod} onChange={(e) => setDefaultPaymentMethod(e.target.value)} className="rounded-md border border-slate-300 px-3 py-1.5 text-sm">
            <option value="cod">COD</option>
            <option value="razorpay">Razorpay</option>
          </select>
        </div>
      </div>

      <div>
        <p className="mb-1 text-xs font-medium text-slate-500">WhatsApp Cloud API (Meta)</p>
        <div className="grid grid-cols-3 gap-3">
          <div>
            <label className="block text-xs font-medium text-slate-500">Phone Number ID</label>
            <input
              value={whatsappPhoneNumberId}
              onChange={(e) => setWhatsappPhoneNumberId(e.target.value)}
              autoComplete="off"
              data-1p-ignore
              className="w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-500">WhatsApp Business Account ID</label>
            <input
              value={whatsappBusinessAccountId}
              onChange={(e) => setWhatsappBusinessAccountId(e.target.value)}
              autoComplete="off"
              data-1p-ignore
              className="w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-500">Access Token</label>
            <input
              type="password"
              placeholder="unchanged"
              value={whatsappAccessToken}
              onChange={(e) => setWhatsappAccessToken(e.target.value)}
              autoComplete="new-password"
              data-1p-ignore
              className="w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm"
            />
          </div>
        </div>
        <p className="mt-1 text-xs text-slate-400">
          See GOING_LIVE.md at the repo root for how to get these values from Meta and connect a real number.
        </p>
        <div className="mt-3">
          <label className="block text-xs font-medium text-slate-500">Commerce Catalog ID (optional)</label>
          <input
            value={whatsappCatalogId}
            onChange={(e) => setWhatsappCatalogId(e.target.value)}
            placeholder="e.g. 1234567890123456"
            autoComplete="off"
            data-1p-ignore
            className="w-full max-w-sm rounded-md border border-slate-300 px-3 py-1.5 text-sm"
          />
          <p className="mt-1 text-xs text-slate-400">
            From Meta Commerce Manager, once a product catalog is created and connected to this business&apos;s
            WhatsApp Business Account. Only needed for features that send WhatsApp&apos;s native product carousel
            (e.g. the jewellery design carousel) -- leave blank otherwise; those features fall back to a plain
            image-based carousel automatically.
          </p>
        </div>
        <div className="mt-3">
          <label className="block text-xs font-medium text-slate-500">Quick Customize Flow ID (optional)</label>
          <input
            value={quickCustomizeFlowId}
            onChange={(e) => setQuickCustomizeFlowId(e.target.value)}
            placeholder="e.g. 1504663505025579"
            autoComplete="off"
            data-1p-ignore
            className="w-full max-w-sm rounded-md border border-slate-300 px-3 py-1.5 text-sm"
          />
          <label className="mt-2 flex items-center gap-2 text-xs text-slate-600">
            <input type="checkbox" checked={quickCustomizeFlowDraftMode} onChange={(e) => setQuickCustomizeFlowDraftMode(e.target.checked)} />
            Flow is still in Draft status in Meta&apos;s Flow Builder
          </label>
          <p className="mt-1 text-xs text-slate-400">
            The id of a Flow built manually in Meta&apos;s own Flow Builder (single static screen, no endpoint) --
            distinct from the auto-created ordering Flow above. While in Draft status, Meta only delivers it to
            phone numbers registered as test numbers for this WhatsApp app; check the box above until it&apos;s
            published, or real customers won&apos;t receive it.
          </p>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-3">
        <div>
          <label className="block text-xs font-medium text-slate-500">Razorpay Key ID</label>
          <input value={razorpayKeyId} onChange={(e) => setRazorpayKeyId(e.target.value)} autoComplete="off" data-1p-ignore className="w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm" />
        </div>
        <div>
          <label className="block text-xs font-medium text-slate-500">Razorpay Key Secret</label>
          <input type="password" placeholder="unchanged" value={razorpayKeySecret} onChange={(e) => setRazorpayKeySecret(e.target.value)} autoComplete="new-password" data-1p-ignore className="w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm" />
        </div>
        <div>
          <label className="block text-xs font-medium text-slate-500">Razorpay Webhook Secret</label>
          <input type="password" placeholder="unchanged" value={razorpayWebhookSecret} onChange={(e) => setRazorpayWebhookSecret(e.target.value)} autoComplete="new-password" data-1p-ignore className="w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm" />
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-xs font-medium text-slate-500">Loyalty points per currency unit spent</label>
          <input type="number" step="0.01" value={pointsPerCurrency} onChange={(e) => setPointsPerCurrency(e.target.value)} className="w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm" />
        </div>
        <div>
          <label className="block text-xs font-medium text-slate-500">Redemption value per point</label>
          <input type="number" step="0.01" value={redemptionValue} onChange={(e) => setRedemptionValue(e.target.value)} className="w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm" />
        </div>
      </div>

      <div>
        <p className="mb-1 text-xs font-medium text-slate-500">Conversation Style</p>
        <p className="mb-2 text-xs text-slate-400">
          How the WhatsApp bot phrases its replies -- rule-based only (no AI/LLM), read by the flow engine on every
          message. Leave blank to use this niche&apos;s own default.
        </p>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <div>
            <label className="block text-xs font-medium text-slate-500">Tone</label>
            <input
              value={tone}
              onChange={(e) => setTone(e.target.value)}
              placeholder="e.g. friendly_casual"
              className="w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-500">Language</label>
            <select value={language} onChange={(e) => setLanguage(e.target.value)} className="w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm">
              <option value="auto">Auto</option>
              <option value="en">English</option>
              <option value="hinglish">Hinglish</option>
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-500">Emoji level</label>
            <select value={emojiLevel} onChange={(e) => setEmojiLevel(e.target.value)} className="w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm">
              <option value="none">None</option>
              <option value="low">Low</option>
              <option value="high">High (as authored)</option>
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-500">Response length</label>
            <select value={responseLength} onChange={(e) => setResponseLength(e.target.value)} className="w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm">
              <option value="normal">Normal</option>
              <option value="short">Short</option>
            </select>
          </div>
        </div>
        <div className="mt-3">
          <label className="block text-xs font-medium text-slate-500">Business personality (display label)</label>
          <input
            value={businessPersonality}
            onChange={(e) => setBusinessPersonality(e.target.value)}
            placeholder="e.g. premium jeweller"
            className="w-full max-w-xs rounded-md border border-slate-300 px-3 py-1.5 text-sm"
          />
        </div>
      </div>

      <button onClick={save} disabled={saving} className="rounded-md bg-primary px-4 py-1.5 text-sm font-medium text-white disabled:opacity-60">
        {saving ? "Saving..." : "Save settings"}
      </button>
    </div>

    <PosDisplaysSection restaurant={restaurant} />
    </div>
  );
}

export default function RestaurantsPage() {
  const { user } = useAuth();
  const { restaurantId, setRestaurantId } = useCurrentRestaurant();
  const [restaurants, setRestaurants] = useState<Restaurant[]>([]);
  const [statusFilter, setStatusFilter] = useState<"all" | Restaurant["status"]>("all");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [slugEdited, setSlugEdited] = useState(false);
  const [nicheCode, setNicheCode] = useState("");
  const [isDemo, setIsDemo] = useState(false);
  const [featurePackageId, setFeaturePackageId] = useState("");
  const [nicheTemplates, setNicheTemplates] = useState<NicheTemplateSummary[]>([]);
  const [featurePackages, setFeaturePackages] = useState<FeaturePackage[]>([]);
  const [creating, setCreating] = useState(false);
  const [newOwner, setNewOwner] = useState<RestaurantCreateResult | null>(null);

  const isSuperAdmin = user?.role === "super_admin";

  async function load() {
    setLoading(true);
    try {
      if (isSuperAdmin) {
        const data = await apiFetch<Restaurant[]>("/restaurants");
        setRestaurants(data);
      } else if (user?.restaurant_id) {
        const data = await apiFetch<Restaurant>(`/restaurants/${user.restaurant_id}`);
        setRestaurants([data]);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load businesses");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (user) load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user]);

  useEffect(() => {
    if (!isSuperAdmin) return;
    apiFetch<NicheTemplateSummary[]>("/niche-templates")
      .then(setNicheTemplates)
      .catch(() => setNicheTemplates([])); // non-fatal -- the picker just falls back to "Custom / Legacy"
    apiFetch<FeaturePackage[]>("/feature-packages")
      .then((pkgs) => {
        setFeaturePackages(pkgs);
        const defaultPkg = pkgs.find((p) => p.is_default);
        if (defaultPkg) setFeaturePackageId(defaultPkg.id);
      })
      .catch(() => setFeaturePackages([])); // non-fatal -- falls back to no package (unrestricted)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isSuperAdmin]);

  async function handleCreate(e: FormEvent) {
    e.preventDefault();
    setCreating(true);
    setError(null);
    try {
      const restaurant = await apiFetch<RestaurantCreateResult>("/restaurants", {
        method: "POST",
        body: JSON.stringify({
          name, slug, niche_code: nicheCode === LEGACY_OPTION ? null : nicheCode, is_demo: isDemo,
          feature_package_id: featurePackageId || null,
        }),
      });
      setName("");
      setSlug("");
      setSlugEdited(false);
      setNicheCode("");
      setIsDemo(false);
      setNewOwner(restaurant);
      await load();
      setRestaurantId(restaurant.id);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to create business");
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Businesses</h1>
        <p className="mt-1 text-sm text-slate-500">
          {isSuperAdmin ? "Onboard a new business in one step -- its owner login is created automatically." : "Your business"}
        </p>
      </div>
      {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

      {newOwner && <NewOwnerCredentials result={newOwner} onDismiss={() => setNewOwner(null)} />}

      {isSuperAdmin && (
        <form onSubmit={handleCreate} className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex flex-wrap items-end gap-3">
            <div>
              <label className="block text-xs font-medium text-slate-500">Business name</label>
              <input
                required
                autoFocus
                placeholder="e.g. Prince Corner Ahmedabad"
                value={name}
                onChange={(e) => {
                  setName(e.target.value);
                  if (!slugEdited) setSlug(slugify(e.target.value));
                }}
                className="w-64 rounded-md border border-slate-300 px-3 py-1.5 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-slate-500">URL slug</label>
              <input
                required
                value={slug}
                onChange={(e) => {
                  setSlug(e.target.value);
                  setSlugEdited(true);
                }}
                placeholder="auto-filled from name"
                className="w-48 rounded-md border border-slate-300 px-3 py-1.5 text-sm text-slate-500 focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-slate-500">
                Business type <span className="text-red-500">*</span>
              </label>
              <select
                required
                value={nicheCode}
                onChange={(e) => setNicheCode(e.target.value)}
                className="w-56 rounded-md border border-slate-300 px-3 py-1.5 text-sm text-slate-700 focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
              >
                <option value="" disabled>
                  Select a business type…
                </option>
                {nicheTemplates.map((t) => (
                  <option key={t.code} value={t.code}>
                    {t.icon} {t.name}
                  </option>
                ))}
                <option value={LEGACY_OPTION}>⚙️ Custom / Legacy (restaurant menu builder)</option>
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-slate-500">Package</label>
              <select
                value={featurePackageId}
                onChange={(e) => setFeaturePackageId(e.target.value)}
                className="w-48 rounded-md border border-slate-300 px-3 py-1.5 text-sm text-slate-700 focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
              >
                <option value="">None (unrestricted)</option>
                {featurePackages.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}{p.is_default ? " (default)" : ""}
                  </option>
                ))}
              </select>
            </div>
            <label className="flex items-center gap-1.5 pb-1.5 text-xs font-medium text-slate-500" title="Marks this as part of the Demo Bot (see /niches) instead of a real business -- excluded from business lists/counts.">
              <input type="checkbox" checked={isDemo} onChange={(e) => setIsDemo(e.target.checked)} className="rounded border-slate-300" />
              Demo Bot business
            </label>
            <button
              type="submit"
              disabled={creating}
              className="rounded-md bg-primary px-4 py-1.5 text-sm font-medium text-white shadow-sm disabled:opacity-60"
            >
              {creating ? "Creating..." : "+ Create business"}
            </button>
          </div>
          <p className="mt-2 text-xs text-slate-400">
            Just type a name — the owner&apos;s dashboard login is created automatically. Only touch the URL slug if you want something different.
            {" "}Business type is required: pick one of the 12 industries to auto-fill a ready-to-go catalog, terminology, and WhatsApp
            conversation flow for it, or deliberately choose &quot;Custom / Legacy&quot; for the original restaurant-only menu builder —
            there&apos;s no silent default either way.
          </p>
        </form>
      )}

      {isSuperAdmin && restaurants.length > 0 && (
        <div className="mb-3 flex flex-wrap gap-1.5">
          {(
            [
              { key: "all" as const, label: "All" },
              { key: "pending_review" as const, label: "Pending Approval" },
              { key: "active" as const, label: "Active" },
              { key: "suspended" as const, label: "Suspended" },
              { key: "cancelled" as const, label: "Cancelled" },
            ]
          ).map((tab) => {
            const count = tab.key === "all" ? restaurants.length : restaurants.filter((r) => r.status === tab.key).length;
            if (tab.key !== "all" && count === 0) return null;
            return (
              <button
                key={tab.key}
                onClick={() => setStatusFilter(tab.key)}
                className={`rounded-full px-3 py-1 text-xs font-medium transition-colors ${
                  statusFilter === tab.key
                    ? "bg-primary text-white"
                    : "border border-slate-200 text-slate-600 hover:bg-slate-50"
                }`}
              >
                {tab.label} ({count})
              </button>
            );
          })}
        </div>
      )}

      {loading ? (
        <p className="text-sm text-slate-500">Loading...</p>
      ) : (
        <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-3">Name</th>
                <th className="px-4 py-3">Slug</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">WhatsApp</th>
                {isSuperAdmin && <th className="px-4 py-3">Orders</th>}
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody>
              {restaurants.filter((r) => statusFilter === "all" || r.status === statusFilter).map((r) => (
                <tr key={r.id} className="border-t border-slate-100 hover:bg-slate-50/60">
                  <td className="px-4 py-3 font-medium text-slate-800">
                    {r.name}
                    {r.is_demo && (
                      <span className="ml-2 rounded-full bg-violet-100 px-2 py-0.5 text-[11px] font-medium text-violet-700" title="Demo Bot business -- see /niches. Manage it below to view its own orders/live-chat.">
                        Demo
                      </span>
                    )}
                    {!r.uses_generic_engine && (
                      <span
                        className="ml-2 rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-medium text-amber-700"
                        title="Original restaurant-only engine -- no Flow Builder / Bot Preview / niche terminology. Use Bot Builder / Home Builder for this one instead. Easy to confuse with a similarly-named niche business below, so flagged here."
                      >
                        Legacy
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-slate-500">{r.slug}</td>
                  <td className="px-4 py-3">
                    <StatusBadge status={r.status} />
                  </td>
                  <td className="px-4 py-3">
                    {r.whatsapp_phone_number_id ? (
                      <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-700">Connected</span>
                    ) : r.demo_sends_via_restaurant_id ? (
                      <span
                        className="rounded-full bg-violet-100 px-2 py-0.5 text-xs font-medium text-violet-700"
                        title="No WhatsApp number of its own -- sends and receives through the Flagship number's industry picker instead."
                      >
                        Connected (via Flagship)
                      </span>
                    ) : (
                      <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-500">Not configured</span>
                    )}
                  </td>
                  {isSuperAdmin && (
                    <td className="px-4 py-3 text-slate-500">
                      {r.total_orders ? (
                        <>
                          <span className="font-medium text-slate-700">{r.total_orders}</span>
                          {r.last_order_at && (
                            <span className="ml-1 text-xs text-slate-400">
                              (last {new Date(r.last_order_at).toLocaleDateString()})
                            </span>
                          )}
                        </>
                      ) : (
                        <span className="text-xs text-slate-400">No orders yet</span>
                      )}
                    </td>
                  )}
                  <td className="px-4 py-3 text-right">
                    <button
                      onClick={() => setRestaurantId(r.id)}
                      className={`rounded-md px-3 py-1 text-xs font-medium ${
                        restaurantId === r.id ? "bg-primary text-white" : "border border-slate-300 text-slate-700 hover:bg-slate-50"
                      }`}
                    >
                      {restaurantId === r.id ? "Selected" : "Manage"}
                    </button>
                  </td>
                </tr>
              ))}
              {restaurants.filter((r) => statusFilter === "all" || r.status === statusFilter).length === 0 && (
                <tr>
                  <td colSpan={isSuperAdmin ? 6 : 5} className="px-4 py-6 text-center text-slate-400">
                    {restaurants.length === 0 ? "No businesses yet." : "No businesses match this filter."}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {isSuperAdmin && restaurantId && restaurants.find((r) => r.id === restaurantId) && (
        <SubscriptionSection restaurant={restaurants.find((r) => r.id === restaurantId)!} onChanged={load} />
      )}

      {isSuperAdmin && restaurantId && restaurants.find((r) => r.id === restaurantId) && (
        <DemoModeSection restaurant={restaurants.find((r) => r.id === restaurantId)!} onChanged={load} />
      )}

      {restaurantId && restaurants.find((r) => r.id === restaurantId) && (
        <SettingsPanel restaurant={restaurants.find((r) => r.id === restaurantId)!} onSaved={load} />
      )}
    </div>
  );
}
