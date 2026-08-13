"use client";

import { useRef, useState } from "react";
import { apiFetch, ApiError } from "@/lib/api";

// Deliberately separate from ImageUploadWidget.tsx -- that one is built around a real
// restaurant_id + CatalogItem row and 30-day re-fetchable URLs (the Universal Image
// Processing Pipeline). A NicheTemplate has neither; this posts to
// POST /niche-templates/upload-image (see that router for why) and gets back one
// permanent URL string the caller decides where to put -- welcome banner, a category
// image, an item image, whatever field is currently being edited.

interface Props {
  label: string;
  value: string;
  onChange: (url: string) => void;
  // Any endpoint that accepts a multipart "file" field and returns { url }. Defaults to
  // the niche-templates one (this component's original use); catalog category icons
  // point at /restaurants/{id}/catalog-categories/upload-image instead -- same
  // permanent-URL contract, different auth scope (Owner/Manager vs Super Admin).
  endpoint?: string;
}

export function TemplateImageUpload({ label, value, onChange, endpoint = "/niche-templates/upload-image" }: Props) {
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  async function handleFile(file: File) {
    setUploading(true);
    setError(null);
    try {
      const formData = new FormData();
      formData.append("file", file);
      const { url } = await apiFetch<{ url: string }>(endpoint, {
        method: "POST",
        body: formData,
      });
      onChange(url);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to upload image");
    } finally {
      setUploading(false);
    }
  }

  return (
    <div className="space-y-1.5">
      <label className="block text-xs font-medium text-slate-500">{label}</label>
      <div className="flex items-center gap-2">
        <input
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder="https://... (or upload a file)"
          className="flex-1 rounded-md border border-slate-300 px-3 py-1.5 text-xs"
        />
        <button
          type="button"
          onClick={() => fileInput.current?.click()}
          disabled={uploading}
          className="shrink-0 rounded-md border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-60"
        >
          {uploading ? "Uploading..." : "Upload"}
        </button>
        <input
          ref={fileInput}
          type="file"
          accept="image/jpeg,image/png,image/webp"
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) handleFile(file);
            e.target.value = "";
          }}
        />
      </div>
      {error && <p className="text-xs text-red-600">{error}</p>}
      {value && <img src={value} alt="" className="h-20 w-32 rounded-md border border-slate-200 object-cover" />}
    </div>
  );
}
