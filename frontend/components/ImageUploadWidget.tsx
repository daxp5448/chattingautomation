"use client";

import { useRef, useState } from "react";
import { apiFetch, ApiError } from "@/lib/api";
import type { ImageRecord } from "@/lib/types";
import { ImageCropModal } from "@/components/ImageCropModal";

// Polls GET /images/{id} until processing finishes -- in this dev/test environment the
// backend's Celery dispatch is synchronous by the time the upload response returns, but
// in a real deployment (real Celery worker) processing genuinely happens after the
// response, so this polling loop is what makes the widget work correctly in both.
const POLL_INTERVAL_MS = 1200;
const POLL_TIMEOUT_MS = 30_000;

interface Props {
  restaurantId: string;
  imageType: string;
  catalogItemId: string;
  images: ImageRecord[];
  onChange: (images: ImageRecord[]) => void;
}

export function ImageUploadWidget({ restaurantId, imageType, catalogItemId, images, onChange }: Props) {
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [cropTarget, setCropTarget] = useState<ImageRecord | null>(null);
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
      formData.append("catalog_item_id", catalogItemId);
      formData.append("file", file);
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

  function onDrop(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files?.[0];
    if (file) handleUpload(file);
  }

  const current = images.filter((img) => !img.replaced_by_image_id);

  return (
    <div className="space-y-3">
      {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

      <div
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
        onClick={() => fileInput.current?.click()}
        className={`flex cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed px-6 py-8 text-center text-sm transition-colors ${
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

      {current.length > 0 && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          {current.map((img) => (
            <div key={img.id} className="rounded-lg border border-slate-200 p-2">
              {img.status === "ready" && (img.urls.thumbnail || img.urls.website) ? (
                <img
                  src={img.urls.thumbnail || img.urls.website}
                  alt=""
                  className="h-24 w-full rounded-md object-cover"
                />
              ) : (
                <div className="flex h-24 w-full items-center justify-center rounded-md bg-slate-100 text-xs text-slate-400">
                  {img.status === "failed" ? "Failed" : "Processing..."}
                </div>
              )}
              {img.resolution_warning && (
                <p className="mt-1 text-xs text-amber-600">
                  {img.low_quality_reason === "below_target_resolution" ? "Low resolution" : "Small file size"}
                </p>
              )}
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
    </div>
  );
}
