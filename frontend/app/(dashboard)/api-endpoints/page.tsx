"use client";

import { useEffect, useState, type FormEvent } from "react";
import { apiFetch, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { ApiEndpoint } from "@/lib/types";

function headersToText(headers: Record<string, string>): string {
  return Object.entries(headers).map(([k, v]) => `${k}: ${v}`).join("\n");
}

function textToHeaders(text: string): Record<string, string> {
  const headers: Record<string, string> = {};
  for (const line of text.split("\n")) {
    const idx = line.indexOf(":");
    if (idx === -1) continue;
    const key = line.slice(0, idx).trim();
    const value = line.slice(idx + 1).trim();
    if (key) headers[key] = value;
  }
  return headers;
}

function EndpointEditor({ endpoint, onSaved, onDeleted }: { endpoint: ApiEndpoint; onSaved: () => void; onDeleted: () => void }) {
  const [name, setName] = useState(endpoint.name);
  const [url, setUrl] = useState(endpoint.url);
  const [method, setMethod] = useState(endpoint.method);
  const [headersText, setHeadersText] = useState(headersToText(endpoint.allowed_headers));
  const [capturableKeys, setCapturableKeys] = useState(endpoint.capturable_context_keys.join(", "));
  const [timeoutSeconds, setTimeoutSeconds] = useState(endpoint.timeout_seconds);
  const [isActive, setIsActive] = useState(endpoint.is_active);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save() {
    setSaving(true);
    setError(null);
    try {
      await apiFetch(`/api-endpoints/${endpoint.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          name, url, method, allowed_headers: textToHeaders(headersText),
          capturable_context_keys: capturableKeys.split(",").map((k) => k.trim()).filter(Boolean),
          timeout_seconds: timeoutSeconds, is_active: isActive,
        }),
      });
      onSaved();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  }

  async function remove() {
    if (!window.confirm(`Delete "${endpoint.name}"? Any flow step still referencing it will fail gracefully at call time (the flow just continues without a response), not crash.`)) return;
    try {
      await apiFetch(`/api-endpoints/${endpoint.id}`, { method: "DELETE" });
      onDeleted();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to delete");
    }
  }

  return (
    <div className="space-y-3 rounded-lg border border-slate-200 p-4">
      {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-xs font-medium text-slate-500">Name</label>
          <input value={name} onChange={(e) => setName(e.target.value)} className="w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm" />
        </div>
        <div>
          <label className="block text-xs font-medium text-slate-500">Method</label>
          <select value={method} onChange={(e) => setMethod(e.target.value)} className="w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm">
            <option value="GET">GET</option>
            <option value="POST">POST</option>
          </select>
        </div>
        <div className="col-span-2">
          <label className="block text-xs font-medium text-slate-500">URL</label>
          <input value={url} onChange={(e) => setUrl(e.target.value)} className="w-full rounded-md border border-slate-300 px-3 py-1.5 font-mono text-xs" />
        </div>
        <div className="col-span-2">
          <label className="block text-xs font-medium text-slate-500">Allowed headers (one per line, "Name: value")</label>
          <textarea rows={3} value={headersText} onChange={(e) => setHeadersText(e.target.value)} className="w-full rounded-md border border-slate-300 px-3 py-1.5 font-mono text-xs" />
        </div>
        <div className="col-span-2">
          <label className="block text-xs font-medium text-slate-500">Capturable context keys (comma-separated)</label>
          <input value={capturableKeys} onChange={(e) => setCapturableKeys(e.target.value)} className="w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm" />
          <p className="mt-1 text-[10px] text-slate-400">
            Only these conversation-context keys are ever sent in the request body -- nothing else, and never
            interpolated into the URL or headers.
          </p>
        </div>
        <div>
          <label className="block text-xs font-medium text-slate-500">Timeout (seconds, max 5)</label>
          <input type="number" min={0.1} max={5} step="0.5" value={timeoutSeconds} onChange={(e) => setTimeoutSeconds(Number(e.target.value))} className="w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm" />
        </div>
        <div className="flex items-end">
          <label className="flex items-center gap-2 text-sm text-slate-600">
            <input type="checkbox" checked={isActive} onChange={(e) => setIsActive(e.target.checked)} />
            Active
          </label>
        </div>
      </div>
      <div className="flex items-center gap-3">
        <button onClick={save} disabled={saving} className="rounded-md bg-primary px-4 py-1.5 text-sm font-medium text-white disabled:opacity-60">
          {saving ? "Saving..." : "Save"}
        </button>
        <button onClick={remove} className="text-xs font-medium text-red-600 hover:text-red-700">Delete</button>
      </div>
    </div>
  );
}

export default function ApiEndpointsPage() {
  const { user } = useAuth();
  const [endpoints, setEndpoints] = useState<ApiEndpoint[]>([]);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [newName, setNewName] = useState("");
  const [newUrl, setNewUrl] = useState("");
  const [creating, setCreating] = useState(false);

  const isSuperAdmin = user?.role === "super_admin";

  async function load() {
    setLoading(true);
    try {
      setEndpoints(await apiFetch<ApiEndpoint[]>("/api-endpoints"));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load API endpoints");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function handleCreate(e: FormEvent) {
    e.preventDefault();
    setCreating(true);
    setError(null);
    try {
      await apiFetch("/api-endpoints", { method: "POST", body: JSON.stringify({ name: newName, url: newUrl, method: "POST" }) });
      setNewName("");
      setNewUrl("");
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to create API endpoint");
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">API Endpoints</h1>
        <p className="mt-1 max-w-2xl text-sm text-slate-500">
          The allowlist a flow&apos;s API-call step can reach -- a flow author picks from this catalog in Flow
          Builder, never types a raw URL. Requests only ever carry the context keys listed below, connect over
          a validated public address, and are capped to a short timeout and response size.
        </p>
      </div>
      {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

      {!isSuperAdmin ? (
        <p className="text-sm text-slate-500">Any signed-in user can view this catalog to pick an endpoint in Flow Builder. Only Super Admins can add, edit, or remove entries.</p>
      ) : (
        <form onSubmit={handleCreate} className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex flex-wrap items-end gap-3">
            <div>
              <label className="block text-xs font-medium text-slate-500">Name</label>
              <input required value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="e.g. Order lookup" className="w-56 rounded-md border border-slate-300 px-3 py-1.5 text-sm" />
            </div>
            <div>
              <label className="block text-xs font-medium text-slate-500">URL</label>
              <input required value={newUrl} onChange={(e) => setNewUrl(e.target.value)} placeholder="https://api.example.com/lookup" className="w-72 rounded-md border border-slate-300 px-3 py-1.5 text-sm" />
            </div>
            <button type="submit" disabled={creating} className="rounded-md bg-primary px-4 py-1.5 text-sm font-medium text-white disabled:opacity-60">
              {creating ? "Adding..." : "+ New endpoint"}
            </button>
          </div>
        </form>
      )}

      {loading ? (
        <p className="text-sm text-slate-500">Loading...</p>
      ) : (
        <div className="space-y-3">
          {endpoints.map((ep) => (
            <div key={ep.id} className="rounded-xl border border-slate-200 bg-white shadow-sm">
              <button
                type="button"
                onClick={() => setExpandedId(expandedId === ep.id ? null : ep.id)}
                className="flex w-full items-center justify-between px-5 py-3 text-left"
              >
                <span>
                  <span className="font-medium text-slate-800">{ep.name}</span>
                  <span className="ml-2 rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-500">{ep.method}</span>
                  {!ep.is_active && <span className="ml-2 rounded-full bg-amber-100 px-2 py-0.5 text-[11px] text-amber-700">inactive</span>}
                  <span className="ml-2 truncate font-mono text-xs text-slate-400">{ep.url}</span>
                </span>
              </button>
              {expandedId === ep.id && isSuperAdmin && (
                <div className="border-t border-slate-100 p-4">
                  <EndpointEditor endpoint={ep} onSaved={load} onDeleted={load} />
                </div>
              )}
            </div>
          ))}
          {endpoints.length === 0 && <p className="text-sm text-slate-400">No API endpoints yet.</p>}
        </div>
      )}
    </div>
  );
}
