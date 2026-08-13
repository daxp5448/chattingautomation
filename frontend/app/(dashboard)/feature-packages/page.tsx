"use client";

import { useEffect, useState, type FormEvent } from "react";
import { apiFetch, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { FeaturePackage } from "@/lib/types";

function PackageEditor({
  pkg, registry, onSaved, onDeleted,
}: {
  pkg: FeaturePackage;
  registry: Record<string, string>;
  onSaved: () => void;
  onDeleted: () => void;
}) {
  const [name, setName] = useState(pkg.name);
  const [description, setDescription] = useState(pkg.description || "");
  const [codes, setCodes] = useState<string[]>(pkg.feature_codes);
  const [isDefault, setIsDefault] = useState(pkg.is_default);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function toggleCode(code: string) {
    setCodes((prev) => (prev.includes(code) ? prev.filter((c) => c !== code) : [...prev, code]));
  }

  async function save() {
    setSaving(true);
    setError(null);
    try {
      await apiFetch(`/feature-packages/${pkg.id}`, {
        method: "PATCH",
        body: JSON.stringify({ name, description: description || null, feature_codes: codes, is_default: isDefault }),
      });
      onSaved();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  }

  async function remove() {
    if (!window.confirm(`Delete "${pkg.name}"? Businesses already assigned to it keep their current features unchanged -- this only affects future assignment.`)) return;
    try {
      await apiFetch(`/feature-packages/${pkg.id}`, { method: "DELETE" });
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
        <div className="flex items-end">
          <label className="flex items-center gap-2 text-sm text-slate-600">
            <input type="checkbox" checked={isDefault} onChange={(e) => setIsDefault(e.target.checked)} />
            Default for new businesses
          </label>
        </div>
        <div className="col-span-2">
          <label className="block text-xs font-medium text-slate-500">Description</label>
          <textarea rows={2} value={description} onChange={(e) => setDescription(e.target.value)} className="w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm" />
        </div>
      </div>

      <div>
        <label className="block text-xs font-medium text-slate-500">Included features</label>
        <div className="mt-1 grid grid-cols-2 gap-2">
          {Object.entries(registry).map(([code, label]) => (
            <label key={code} className="flex items-center gap-2 rounded-md border border-slate-100 px-3 py-1.5 text-sm text-slate-700">
              <input type="checkbox" checked={codes.includes(code)} onChange={() => toggleCode(code)} />
              {label}
            </label>
          ))}
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

export default function FeaturePackagesPage() {
  const { user } = useAuth();
  const [packages, setPackages] = useState<FeaturePackage[]>([]);
  const [registry, setRegistry] = useState<Record<string, string>>({});
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [newName, setNewName] = useState("");
  const [creating, setCreating] = useState(false);

  const isSuperAdmin = user?.role === "super_admin";

  async function load() {
    setLoading(true);
    try {
      const [pkgs, reg] = await Promise.all([
        apiFetch<FeaturePackage[]>("/feature-packages"),
        apiFetch<Record<string, string>>("/feature-packages/registry"),
      ]);
      setPackages(pkgs);
      setRegistry(reg);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load feature packages");
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
      await apiFetch("/feature-packages", { method: "POST", body: JSON.stringify({ name: newName, feature_codes: [] }) });
      setNewName("");
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to create feature package");
    } finally {
      setCreating(false);
    }
  }

  if (!isSuperAdmin) {
    return <p className="text-sm text-slate-500">Only Super Admins can manage feature packages.</p>;
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Feature Packages</h1>
        <p className="mt-1 max-w-2xl text-sm text-slate-500">
          Bundle features into a plan and assign it to a business when creating it (or later, from its
          settings). Editing a package here never changes a business already assigned to it -- assignment
          copies the feature list at that moment, not a live reference.
        </p>
      </div>
      {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

      <form onSubmit={handleCreate} className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-end gap-3">
          <div>
            <label className="block text-xs font-medium text-slate-500">Name</label>
            <input required placeholder="e.g. Starter" value={newName} onChange={(e) => setNewName(e.target.value)} className="w-56 rounded-md border border-slate-300 px-3 py-1.5 text-sm" />
          </div>
          <button type="submit" disabled={creating} className="rounded-md bg-primary px-4 py-1.5 text-sm font-medium text-white disabled:opacity-60">
            {creating ? "Creating..." : "+ New package"}
          </button>
        </div>
        <p className="mt-2 text-xs text-slate-400">Starts with no features included -- expand it below to pick which ones.</p>
      </form>

      {loading ? (
        <p className="text-sm text-slate-500">Loading...</p>
      ) : (
        <div className="space-y-3">
          {packages.map((pkg) => (
            <div key={pkg.id} className="rounded-xl border border-slate-200 bg-white shadow-sm">
              <button
                type="button"
                onClick={() => setExpandedId(expandedId === pkg.id ? null : pkg.id)}
                className="flex w-full items-center justify-between px-5 py-3 text-left"
              >
                <span>
                  <span className="font-medium text-slate-800">{pkg.name}</span>
                  {pkg.is_default && <span className="ml-2 rounded-full bg-emerald-100 px-2 py-0.5 text-[11px] text-emerald-700">default</span>}
                  <span className="ml-2 text-xs text-slate-400">{pkg.feature_codes.length} feature(s)</span>
                </span>
              </button>
              {expandedId === pkg.id && (
                <div className="border-t border-slate-100 p-4">
                  <PackageEditor pkg={pkg} registry={registry} onSaved={load} onDeleted={load} />
                </div>
              )}
            </div>
          ))}
          {packages.length === 0 && <p className="text-sm text-slate-400">No feature packages yet.</p>}
        </div>
      )}
    </div>
  );
}
