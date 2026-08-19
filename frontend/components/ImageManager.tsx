"use client";

import { useEffect, useRef, useState } from "react";
import { apiFetch, ApiError } from "@/lib/api";
import type { ImageLibraryEntry, ImageRecord } from "@/lib/types";
import { ImageCropModal } from "@/components/ImageCropModal";
import { IconX } from "@/components/icons";

// Polls GET /images/{id} until processing finishes -- in this dev/test environment the
// backend's Celery dispatch is synchronous by the time the upload response returns, but
// in a real deployment (real Celery worker) processing genuinely happens after the
// response, so this polling loop is what makes the widget work correctly in both.
const POLL_INTERVAL_MS = 1200;
const POLL_TIMEOUT_MS = 30_000;

// One reusable image editor for every owner an Image row can attach to (see
// backend/app/models/image.py's docstring) -- a catalog item, a catalog category, or one
// specific flow step. Every owner shape maps to the same upload/attach/list query
// contract (backend/app/api/v1/routers/images.py), so this component never needs to know
// which owner it's editing beyond building the right form fields/query params.
export type ImageOwner =
  | { catalogItemId: string }
  | { catalogCategoryId: string }
  | { flowDefinitionId: string; stepId: string };

function ownerFormFields(owner: ImageOwner): Record<string, string> {
  if ("catalogItemId" in owner) return { catalog_item_id: owner.catalogItemId };
  if ("catalogCategoryId" in owner) return { catalog_category_id: owner.catalogCategoryId };
  return { flow_definition_id: owner.flowDefinitionId, flow_step_id: owner.stepId };
}

// Query string for GET /restaurants/{id}/images -- exported so callers that fetch an
// owner's current images (to pass into this component's `images` prop) build the same
// owner encoding this component uploads/attaches against, instead of reimplementing it.
export function ownerQueryString(owner: ImageOwner): string {
  const params = new URLSearchParams(ownerFormFields(owner));
  return params.toString();
}

interface Props {
  restaurantId: string;
  imageType: string;
  owner: ImageOwner;
  images: ImageRecord[];
  onChange: (images: ImageRecord[]) => void;
}

export function ImageManager({ restaurantId, imageType, owner, images, onChange }: Props) {
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [cropTarget, setCropTarget] = useState<ImageRecord | null>(null);
  const [libraryOpen, setLibraryOpen] = useState(false);
  const [dragImageId, setDragImageId] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  async function pollUntilReady(imageId: string): Promise<ImageRecord> {
    const deadline = Date.now() + POLL_TIMEOUT_MS;
    for (;;) {
      const current = await apiFetch<ImageRecord>(`/restaurants/${restaurantId}/images/${imageId}`);
      if (current.status !== "processing" || Date.now() > deadline) return current;
      await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
    }
  }

  async function handleUpload(file: File) {
    setUploading(true);
    setError(null);
    try {
      const formData = new FormData();
      formData.append("image_type", imageType);
      for (const [key, value] of Object.entries(ownerFormFields(owner))) formData.append(key, value);
      formData.append("file", file);
      // Appends after whatever's already shown, rather than every upload defaulting to
      // the same order value and needing a manual reorder just to separate them.
      const existingCount = images.filter((img) => !img.replaced_by_image_id).length;
      formData.append("display_order", String(existingCount));
      const created = await apiFetch<ImageRecord>(`/restaurants/${restaurantId}/images`, {
        method: "POST",
        body: formData,
      });
      const ready = await pollUntilReady(created.id);
      onChange([...images, ready]);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to upload image");
    } finally {
      setUploading(false);
    }
  }

  async function handleAttachFromLibrary(entry: ImageLibraryEntry) {
    setError(null);
    try {
      const existingCount = images.filter((img) => !img.replaced_by_image_id).length;
      const attached = await apiFetch<ImageRecord>(`/restaurants/${restaurantId}/images/${entry.id}/attach`, {
        method: "POST",
        body: JSON.stringify({ ...ownerFormFields(owner), display_order: existingCount }),
      });
      onChange([...images, attached]);
      setLibraryOpen(false);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to attach image");
    }
  }

  async function handleReplace(imageId: string, file: File) {
    setUploading(true);
    setError(null);
    try {
      const formData = new FormData();
      formData.append("file", file);
      const created = await apiFetch<ImageRecord>(`/restaurants/${restaurantId}/images/${imageId}/replace`, {
        method: "POST",
        body: formData,
      });
      const ready = await pollUntilReady(created.id);
      onChange(images.map((img) => (img.id === imageId ? { ...img, replaced_by_image_id: created.id } : img)).concat(ready));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to replace image");
    } finally {
      setUploading(false);
    }
  }

  async function handleDelete(imageId: string) {
    if (!window.confirm("Remove this image?")) return;
    try {
      await apiFetch(`/restaurants/${restaurantId}/images/${imageId}`, { method: "DELETE" });
      onChange(images.filter((img) => img.id !== imageId));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to remove image");
    }
  }

  async function updateMetadata(imageId: string, patch: Partial<Pick<ImageRecord, "caption" | "alt_text" | "display_order" | "is_active">>) {
    try {
      const updated = await apiFetch<ImageRecord>(`/restaurants/${restaurantId}/images/${imageId}`, {
        method: "PATCH",
        body: JSON.stringify(patch),
      });
      onChange(images.map((img) => (img.id === imageId ? updated : img)));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to save image details");
    }
  }

  function moveImage(imageId: string, direction: -1 | 1) {
    const index = current.findIndex((img) => img.id === imageId);
    const targetIndex = index + direction;
    if (index < 0 || targetIndex < 0 || targetIndex >= current.length) return;
    const a = current[index];
    const b = current[targetIndex];
    updateMetadata(a.id, { display_order: b.display_order });
    updateMetadata(b.id, { display_order: a.display_order });
  }

  // Drag-to-reorder: dropping image A onto image B moves A to B's position and shifts
  // everything between them, then persists sequential display_order (0..n-1) for the
  // whole set -- not just a two-item swap, so a drag across several cards in one gesture
  // lands where the user actually dropped it.
  function reorderByDrag(sourceId: string, targetId: string) {
    if (sourceId === targetId) return;
    const ids = current.map((img) => img.id);
    const from = ids.indexOf(sourceId);
    const to = ids.indexOf(targetId);
    if (from < 0 || to < 0) return;
    const reordered = [...ids];
    reordered.splice(from, 1);
    reordered.splice(to, 0, sourceId);
    reordered.forEach((id, order) => {
      const img = current.find((i) => i.id === id);
      if (img && img.display_order !== order) updateMetadata(id, { display_order: order });
    });
  }

  function onDrop(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files?.[0];
    if (file) handleUpload(file);
  }

  const current = images
    .filter((img) => !img.replaced_by_image_id)
    .sort((a, b) => a.display_order - b.display_order || a.created_at.localeCompare(b.created_at));

  return (
    <div className="space-y-3">
      {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

      <div className="flex flex-wrap gap-2">
        <div
          onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
          onDragLeave={() => setDragOver(false)}
          onDrop={onDrop}
          onClick={() => fileInput.current?.click()}
          className={`flex flex-1 cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed px-6 py-8 text-center text-sm transition-colors ${
            dragOver ? "border-primary bg-primary/5" : "border-slate-300 text-slate-500 hover:border-slate-400"
          }`}
        >
          <input
            ref={fileInput}
            type="file"
            accept="image/jpeg,image/png,image/webp"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) handleUpload(file);
              e.target.value = "";
            }}
          />
          {uploading ? "Uploading & processing..." : "Drag an image here, or click to browse"}
        </div>
        <button
          type="button"
          onClick={() => setLibraryOpen(true)}
          className="shrink-0 self-stretch rounded-lg border-2 border-dashed border-slate-300 px-4 py-8 text-sm font-medium text-slate-500 hover:border-slate-400 hover:text-slate-700"
        >
          Choose From Media Library
        </button>
      </div>

      {current.length > 1 && (
        <p className="text-xs text-slate-400">
          {current.length} images -- shown to customers in this order, each with its own caption. Drag to reorder, or use ▲/▼.
        </p>
      )}

      {current.length > 0 && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {current.map((img, index) => (
            <div
              key={img.id}
              draggable
              onDragStart={() => setDragImageId(img.id)}
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => {
                e.preventDefault();
                if (dragImageId) reorderByDrag(dragImageId, img.id);
                setDragImageId(null);
              }}
              className={`cursor-move rounded-lg border p-2 ${img.is_active ? "border-slate-200" : "border-slate-200 bg-slate-50 opacity-60"}`}
            >
              <div className="flex gap-2">
                <div className="flex flex-col items-center justify-center gap-0.5">
                  <button
                    type="button"
                    disabled={index === 0}
                    onClick={() => moveImage(img.id, -1)}
                    className="text-xs text-slate-400 hover:text-slate-700 disabled:opacity-30"
                    title="Move earlier"
                  >
                    ▲
                  </button>
                  <span className="text-[10px] text-slate-400">{index + 1}</span>
                  <button
                    type="button"
                    disabled={index === current.length - 1}
                    onClick={() => moveImage(img.id, 1)}
                    className="text-xs text-slate-400 hover:text-slate-700 disabled:opacity-30"
                    title="Move later"
                  >
                    ▼
                  </button>
                </div>

                {img.status === "ready" && (img.urls.thumbnail || img.urls.website) ? (
                  <img
                    src={img.urls.thumbnail || img.urls.website}
                    alt={img.alt_text || ""}
                    className="h-24 w-24 shrink-0 rounded-md object-cover"
                  />
                ) : (
                  <div className="flex h-24 w-24 shrink-0 items-center justify-center rounded-md bg-slate-100 text-xs text-slate-400">
                    {img.status === "failed" ? "Failed" : "Processing..."}
                  </div>
                )}

                <div className="min-w-0 flex-1 space-y-1">
                  <input
                    defaultValue={img.caption || ""}
                    placeholder="Caption customers see with this photo"
                    onBlur={(e) => {
                      const value = e.target.value.trim();
                      if (value !== (img.caption || "")) updateMetadata(img.id, { caption: value || null });
                    }}
                    className="w-full rounded-md border border-slate-200 px-2 py-1 text-xs"
                  />
                  <label className="flex items-center gap-1 text-[11px] text-slate-500">
                    <input
                      type="checkbox"
                      checked={img.is_active}
                      onChange={(e) => updateMetadata(img.id, { is_active: e.target.checked })}
                    />
                    Visible to customers
                  </label>
                  {img.resolution_warning && (
                    <p className="text-[11px] text-amber-600">
                      {img.low_quality_reason === "below_target_resolution" ? "Low resolution" : "Small file size"}
                    </p>
                  )}
                </div>
              </div>

              <div className="mt-2 flex flex-wrap gap-1">
                <button
                  type="button"
                  onClick={() => setCropTarget(img)}
                  disabled={img.status !== "ready"}
                  className="rounded-md border border-slate-300 px-2 py-1 text-xs text-slate-600 hover:bg-slate-50 disabled:opacity-50"
                >
                  Crop
                </button>
                <label className="cursor-pointer rounded-md border border-slate-300 px-2 py-1 text-xs text-slate-600 hover:bg-slate-50">
                  Replace
                  <input
                    type="file"
                    accept="image/jpeg,image/png,image/webp"
                    className="hidden"
                    onChange={(e) => {
                      const file = e.target.files?.[0];
                      if (file) handleReplace(img.id, file);
                      e.target.value = "";
                    }}
                  />
                </label>
                <button
                  type="button"
                  onClick={() => handleDelete(img.id)}
                  className="rounded-md border border-red-300 px-2 py-1 text-xs text-red-600 hover:bg-red-50"
                >
                  Remove
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {cropTarget && (
        <ImageCropModal
          restaurantId={restaurantId}
          image={cropTarget}
          onClose={() => setCropTarget(null)}
          onCropped={(updated) => {
            onChange(images.map((img) => (img.id === updated.id ? updated : img)));
            setCropTarget(null);
          }}
        />
      )}

      {libraryOpen && (
        <MediaLibraryPicker
          restaurantId={restaurantId}
          onClose={() => setLibraryOpen(false)}
          onPick={handleAttachFromLibrary}
        />
      )}
    </div>
  );
}

function MediaLibraryPicker({
  restaurantId,
  onClose,
  onPick,
}: {
  restaurantId: string;
  onClose: () => void;
  onPick: (entry: ImageLibraryEntry) => void;
}) {
  const [entries, setEntries] = useState<ImageLibraryEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    const query = search ? `?search=${encodeURIComponent(search)}` : "";
    apiFetch<ImageLibraryEntry[]>(`/restaurants/${restaurantId}/images/library${query}`)
      .then((rows) => { if (!cancelled) setEntries(rows.filter((r) => r.status === "ready")); })
      .catch(() => { if (!cancelled) setEntries([]); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [restaurantId, search]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div
        className="max-h-[80vh] w-full max-w-2xl overflow-y-auto rounded-xl bg-white p-4 shadow-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-slate-800">Choose From Media Library</h3>
          <button type="button" onClick={onClose} className="text-slate-400 hover:text-slate-700"><IconX size={15} /></button>
        </div>
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search by item name..."
          className="mb-3 w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm"
        />
        {loading ? (
          <p className="text-sm text-slate-400">Loading...</p>
        ) : entries.length === 0 ? (
          <p className="text-sm text-slate-400">No reusable images found.</p>
        ) : (
          <div className="grid grid-cols-3 gap-2 sm:grid-cols-4">
            {entries.map((entry) => (
              <button
                key={entry.id}
                type="button"
                onClick={() => onPick(entry)}
                className="group relative overflow-hidden rounded-md border border-slate-200 hover:border-primary"
                title={entry.caption || entry.catalog_item?.name || ""}
              >
                <img src={entry.urls.thumbnail || entry.urls.website} alt="" className="h-24 w-full object-cover" />
                <span className="absolute inset-x-0 bottom-0 truncate bg-black/50 px-1 py-0.5 text-[10px] text-white opacity-0 group-hover:opacity-100">
                  {entry.caption || entry.catalog_item?.name || "Use this image"}
                </span>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
