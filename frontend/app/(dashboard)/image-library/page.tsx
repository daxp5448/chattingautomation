"use client";

import { useEffect, useState, type FormEvent } from "react";
import { apiFetch, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { ImageTypeProfile, ImageVariantSpec } from "@/lib/types";

const CONTEXTS: ImageVariantSpec["target_context"][] = ["whatsapp", "thumbnail", "banner", "gallery", "website"];

function emptySpec(): ImageVariantSpec {
  return { variant_name: "", target_context: "website", width: 400, height: 400, crop_mode: "cover", format: "webp" };
}

function ProfileEditor({ profile, onSaved }: { profile: ImageTypeProfile; onSaved: () => void }) {
  const [label, setLabel] = useState(profile.label);
  const [maxSize, setMaxSize] = useState(String(profile.max_upload_size_bytes));
  const [specs, setSpecs] = useState<ImageVariantSpec[]>(profile.variant_specs);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function updateSpec(index: number, patch: Partial<ImageVariantSpec>) {
    setSpecs((prev) => prev.map((s, i) => (i === index ? { ...s, ...patch } : s)));
  }

  async function save() {
    setSaving(true);
    setError(null);
    try {
      await apiFetch(`/image-type-profiles/${profile.id}`, {
        method: "PATCH",
        body: JSON.stringify({ label, max_upload_size_bytes: Number(maxSize) || 0, variant_specs: specs }),
      });
      onSaved();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-3 rounded-lg border border-slate-200 p-4">
      {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
      <div className="flex flex-wrap items-end gap-3">
        <div>
          <label className="block text-xs font-medium text-slate-500">Code</label>
          <p className="rounded-md bg-slate-50 px-3 py-1.5 text-sm text-slate-500">{profile.code}</p>
        </div>
        <div>
          <label className="block text-xs font-medium text-slate-500">Label</label>
          <input value={label} onChange={(e) => setLabel(e.target.value)} className="rounded-md border border-slate-300 px-3 py-1.5 text-sm" />
        </div>
        <div>
          <label className="block text-xs font-medium text-slate-500">Max upload size (bytes)</label>
          <input
            type="number"
            value={maxSize}
            onChange={(e) => setMaxSize(e.target.value)}
            className="w-40 rounded-md border border-slate-300 px-3 py-1.5 text-sm"
          />
        </div>
      </div>

      <div>
        <p className="mb-1 text-xs font-medium text-slate-500">Variant sizes</p>
        <div className="space-y-2">
          {specs.map((spec, i) => (
            <div key={i} className="flex flex-wrap items-center gap-2 rounded-md border border-slate-100 bg-slate-50 p-2">
              <input
                value={spec.variant_name}
                onChange={(e) => updateSpec(i, { variant_name: e.target.value })}
                placeholder="name"
                className="w-28 rounded-md border border-slate-300 px-2 py-1 text-xs"
              />
              <select
                value={spec.target_context}
                onChange={(e) => updateSpec(i, { target_context: e.target.value as ImageVariantSpec["target_context"] })}
                className="rounded-md border border-slate-300 px-2 py-1 text-xs"
              >
                {CONTEXTS.map((c) => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </select>
              <input
                type="number"
                value={spec.width}
                onChange={(e) => updateSpec(i, { width: Number(e.target.value) || 0 })}
                className="w-20 rounded-md border border-slate-300 px-2 py-1 text-xs"
              />
              <span className="text-xs text-slate-400">x</span>
              <input
                type="number"
                value={spec.height}
                onChange={(e) => updateSpec(i, { height: Number(e.target.value) || 0 })}
                className="w-20 rounded-md border border-slate-300 px-2 py-1 text-xs"
              />
              <select
                value={spec.crop_mode}
                onChange={(e) => updateSpec(i, { crop_mode: e.target.value as ImageVariantSpec["crop_mode"] })}
                className="rounded-md border border-slate-300 px-2 py-1 text-xs"
              >
                <option value="cover">cover</option>
                <option value="contain">contain</option>
              </select>
              <button
                type="button"
                onClick={() => setSpecs((prev) => prev.filter((_, idx) => idx !== i))}
                className="ml-auto rounded-md border border-red-300 px-2 py-1 text-xs text-red-600 hover:bg-red-50"
              >
                Remove
              </button>
            </div>
          ))}
        </div>
        <button
          type="button"
          onClick={() => setSpecs((prev) => [...prev, emptySpec()])}
          className="mt-2 rounded-md border border-slate-300 px-3 py-1 text-xs text-slate-600 hover:bg-slate-50"
        >
          + Add variant size
        </button>
      </div>

      <button
        onClick={save}
        disabled={saving}
        className="rounded-md bg-primary px-4 py-1.5 text-sm font-medium text-white disabled:opacity-60"
      >
        {saving ? "Saving..." : "Save profile"}
      </button>
    </div>
  );
}

export default function ImageLibraryPage() {
  const { user } = useAuth();
  const [profiles, setProfiles] = useState<ImageTypeProfile[]>([]);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [newCode, setNewCode] = useState("");
  const [newLabel, setNewLabel] = useState("");
  const [creating, setCreating] = useState(false);

  const isSuperAdmin = user?.role === "super_admin";

  async function load() {
    setLoading(true);
    try {
      setProfiles(await apiFetch<ImageTypeProfile[]>("/image-type-profiles"));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load image type profiles");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (isSuperAdmin) load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isSuperAdmin]);

  async function handleCreate(e: FormEvent) {
    e.preventDefault();
    setCreating(true);
    setError(null);
    try {
      await apiFetch("/image-type-profiles", {
        method: "POST",
        body: JSON.stringify({ code: newCode, label: newLabel, variant_specs: [emptySpec()] }),
      });
      setNewCode("");
      setNewLabel("");
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to create image type");
    } finally {
      setCreating(false);
    }
  }

  if (!isSuperAdmin) {
    return <p className="text-sm text-slate-500">Only Super Admins can manage the image library.</p>;
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Image Library</h1>
        <p className="mt-1 text-sm text-slate-500">
          Image types and their generated sizes (WhatsApp/thumbnail/banner/gallery/website) -- add a new
          type or change a size profile here, no deploy needed.
        </p>
      </div>
      {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

      <form onSubmit={handleCreate} className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-end gap-3">
          <div>
            <label className="block text-xs font-medium text-slate-500">Code</label>
            <input
              required
              placeholder="e.g. vehicle_interior"
              value={newCode}
              onChange={(e) => setNewCode(e.target.value)}
              className="w-56 rounded-md border border-slate-300 px-3 py-1.5 text-sm"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-500">Label</label>
            <input
              required
              placeholder="e.g. Vehicle Interior"
              value={newLabel}
              onChange={(e) => setNewLabel(e.target.value)}
              className="w-56 rounded-md border border-slate-300 px-3 py-1.5 text-sm"
            />
          </div>
          <button type="submit" disabled={creating} className="rounded-md bg-primary px-4 py-1.5 text-sm font-medium text-white disabled:opacity-60">
            {creating ? "Creating..." : "+ New image type"}
          </button>
        </div>
      </form>

      {loading ? (
        <p className="text-sm text-slate-500">Loading...</p>
      ) : (
        <div className="space-y-3">
          {profiles.map((profile) => (
            <div key={profile.id} className="rounded-xl border border-slate-200 bg-white shadow-sm">
              <button
                type="button"
                onClick={() => setExpandedId(expandedId === profile.id ? null : profile.id)}
                className="flex w-full items-center justify-between px-5 py-3 text-left"
              >
                <div>
                  <span className="font-medium text-slate-800">{profile.label}</span>
                  <span className="ml-2 font-mono text-xs text-slate-400">{profile.code}</span>
                </div>
                <span className="text-xs text-slate-400">{profile.variant_specs.length} variant(s)</span>
              </button>
              {expandedId === profile.id && (
                <div className="border-t border-slate-100 p-4">
                  <ProfileEditor profile={profile} onSaved={load} />
                </div>
              )}
            </div>
          ))}
          {profiles.length === 0 && <p className="text-sm text-slate-400">No image types yet.</p>}
        </div>
      )}
    </div>
  );
}
