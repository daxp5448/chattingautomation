"use client";

import { useState } from "react";
import Cropper, { type Area } from "react-easy-crop";
import { apiFetch, ApiError } from "@/lib/api";
import type { ImageRecord } from "@/lib/types";

interface Props {
  restaurantId: string;
  image: ImageRecord;
  onClose: () => void;
  onCropped: (updated: ImageRecord) => void;
}

// Always crops from the untouched original (image.urls.original) -- never a derivative
// -- matching the backend's own guarantee (POST /images/{id}/crop always regenerates
// every variant from original_key). react-easy-crop's onCropComplete reports
// croppedAreaPixels already in the ORIGINAL image's pixel space, which is exactly the
// {x, y, width, height} shape ImageCropRequest expects -- no scaling math needed here.
export function ImageCropModal({ restaurantId, image, onClose, onCropped }: Props) {
  const [crop, setCrop] = useState({ x: 0, y: 0 });
  const [zoom, setZoom] = useState(1);
  const [croppedAreaPixels, setCroppedAreaPixels] = useState<Area | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSave() {
    if (!croppedAreaPixels) return;
    setSaving(true);
    setError(null);
    try {
      const updated = await apiFetch<ImageRecord>(`/restaurants/${restaurantId}/images/${image.id}/crop`, {
        method: "POST",
        body: JSON.stringify({
          x: Math.round(croppedAreaPixels.x),
          y: Math.round(croppedAreaPixels.y),
          width: Math.round(croppedAreaPixels.width),
          height: Math.round(croppedAreaPixels.height),
        }),
      });
      // Processing may still be running in a real deployment (this modal doesn't poll --
      // the parent ImageUploadWidget's list will show "Processing..." for this image
      // until its own next refresh); in this dev/test environment it's already "ready".
      onCropped(updated);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to save crop");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="w-full max-w-lg rounded-xl bg-white p-4 shadow-xl">
        <h3 className="mb-2 text-sm font-semibold text-slate-800">Crop image</h3>
        {error && <p className="mb-2 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
        <div className="relative h-80 w-full overflow-hidden rounded-lg bg-slate-900">
          <Cropper
            image={image.urls.original}
            crop={crop}
            zoom={zoom}
            aspect={1}
            onCropChange={setCrop}
            onZoomChange={setZoom}
            onCropComplete={(_croppedArea, pixels) => setCroppedAreaPixels(pixels)}
          />
        </div>
        <div className="mt-3 flex items-center gap-2">
          <label className="text-xs text-slate-500">Zoom</label>
          <input
            type="range"
            min={1}
            max={3}
            step={0.1}
            value={zoom}
            onChange={(e) => setZoom(Number(e.target.value))}
            className="flex-1"
          />
        </div>
        <div className="mt-4 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-slate-300 px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={saving || !croppedAreaPixels}
            className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-white disabled:opacity-60"
          >
            {saving ? "Saving..." : "Save crop"}
          </button>
        </div>
      </div>
    </div>
  );
}
