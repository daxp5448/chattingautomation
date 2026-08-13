"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import { apiFetch, ApiError } from "@/lib/api";
import { RequireRestaurant } from "@/components/RequireRestaurant";
import type { ImageLibraryEntry, ImageTypeProfile } from "@/lib/types";

const STATUS_LABEL: Record<ImageLibraryEntry["status"], string> = {
  ready: "Ready",
  processing: "Processing...",
  failed: "Failed",
};

const STATUS_BADGE_CLASS: Record<ImageLibraryEntry["status"], string> = {
  ready: "bg-green-50 text-green-700",
  processing: "bg-amber-50 text-amber-700",
  failed: "bg-red-50 text-red-700",
};

function thumbnailUrl(image: ImageLibraryEntry): string | null {
  // Same preference order ImageUploadWidget.tsx uses for a display thumbnail: the
  // dedicated "thumbnail" variant if this image_type's profile generates one, else the
  // next-smallest "website" variant, else nothing displayable yet.
  return image.urls.thumbnail || image.urls.website || null;
}

function MediaLibraryForRestaurant({ restaurantId }: { restaurantId: string }) {
  const [images, setImages] = useState<ImageLibraryEntry[]>([]);
  const [typeOptions, setTypeOptions] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [imageType, setImageType] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (search) params.set("search", search);
      if (imageType) params.set("image_type", imageType);
      const query = params.toString();
      const results = await apiFetch<ImageLibraryEntry[]>(
        `/restaurants/${restaurantId}/images/library${query ? `?${query}` : ""}`
      );
      setImages(results);
      // Derived fallback for the type filter's options -- see the /image-type-profiles
      // fetch below, which only a Super Admin can call. Only grows the option list (never
      // drops a code the user just filtered by), so the dropdown stays usable even for a
      // plain Owner/Manager account who can't read the profiles registry.
      setTypeOptions((prev) => Array.from(new Set([...prev, ...results.map((img) => img.image_type)])).sort());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load media library");
    } finally {
      setLoading(false);
    }
  }, [restaurantId, search, imageType]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    // Best-effort: GET /image-type-profiles is Super-Admin-only (see
    // image_type_profiles.py), so a plain Owner/Manager gets a 403 here -- harmless, the
    // dropdown just falls back to whatever image_type codes actually show up in this
    // restaurant's own images (populated by `load` above) instead of the full registry.
    apiFetch<ImageTypeProfile[]>("/image-type-profiles")
      .then((profiles) => {
        setTypeOptions((prev) => Array.from(new Set([...prev, ...profiles.map((p) => p.code)])).sort());
      })
      .catch(() => {
        // Not a real error for this page -- see comment above.
      });
  }, []);

  function handleSearchSubmit(e: FormEvent) {
    e.preventDefault();
    setSearch(searchInput.trim());
  }

  async function handleDelete(image: ImageLibraryEntry) {
    if (!window.confirm("Remove this image? This can't be undone from here.")) return;
    try {
      await apiFetch(`/restaurants/${restaurantId}/images/${image.id}`, { method: "DELETE" });
      setImages((prev) => prev.filter((img) => img.id !== image.id));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to remove image");
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Media Library</h1>
        <p className="mt-1 text-sm text-slate-500">
          Every image uploaded across your whole catalog, in one place -- search by the item it's
          attached to, filter by type, and remove ones you no longer need.
        </p>
      </div>

      {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

      <form onSubmit={handleSearchSubmit} className="flex flex-wrap items-end gap-3">
        <div>
          <label className="block text-xs font-medium text-slate-500">Search by item name</label>
          <input
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder="e.g. Margherita Pizza"
            className="w-64 rounded-md border border-slate-300 px-3 py-1.5 text-sm"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-slate-500">Image type</label>
          <select
            value={imageType}
            onChange={(e) => setImageType(e.target.value)}
            className="w-48 rounded-md border border-slate-300 px-3 py-1.5 text-sm"
          >
            <option value="">All types</option>
            {typeOptions.map((code) => (
              <option key={code} value={code}>
                {code}
              </option>
            ))}
          </select>
        </div>
        <button type="submit" className="rounded-md bg-primary px-4 py-1.5 text-sm font-medium text-white">
          Search
        </button>
        {(search || imageType) && (
          <button
            type="button"
            onClick={() => {
              setSearchInput("");
              setSearch("");
              setImageType("");
            }}
            className="rounded-md border border-slate-300 px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-50"
          >
            Clear filters
          </button>
        )}
      </form>

      {loading ? (
        <p className="text-sm text-slate-500">Loading...</p>
      ) : images.length === 0 ? (
        <p className="text-sm text-slate-400">No images found.</p>
      ) : (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5">
          {images.map((image) => {
            const thumb = thumbnailUrl(image);
            return (
              <div key={image.id} className="rounded-xl border border-slate-200 bg-white p-3 shadow-sm">
                {thumb ? (
                  <img src={thumb} alt="" className="h-28 w-full rounded-md object-cover" />
                ) : (
                  <div className="flex h-28 w-full items-center justify-center rounded-md bg-slate-100 text-xs text-slate-400">
                    {image.status === "failed" ? "Failed" : "Processing..."}
                  </div>
                )}

                <div className="mt-2 flex items-center justify-between gap-2">
                  <span className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${STATUS_BADGE_CLASS[image.status]}`}>
                    {STATUS_LABEL[image.status]}
                  </span>
                  <span className="truncate font-mono text-[11px] text-slate-400" title={image.image_type}>
                    {image.image_type}
                  </span>
                </div>

                <p className="mt-1.5 truncate text-xs text-slate-600" title={image.catalog_item?.name}>
                  {image.catalog_item ? (
                    <>
                      Used by: <span className="font-medium text-slate-800">{image.catalog_item.name}</span>
                    </>
                  ) : (
                    <span className="text-slate-400">Not attached to an item</span>
                  )}
                </p>

                {image.resolution_warning && (
                  <p className="mt-1 text-[11px] text-amber-600">
                    {image.low_quality_reason === "below_target_resolution" ? "Low resolution" : "Small file size"}
                  </p>
                )}

                <button
                  type="button"
                  onClick={() => handleDelete(image)}
                  className="mt-2 w-full rounded-md border border-red-300 px-2 py-1 text-xs text-red-600 hover:bg-red-50"
                >
                  Remove
                </button>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default function MediaLibraryPage() {
  return <RequireRestaurant>{(restaurantId) => <MediaLibraryForRestaurant restaurantId={restaurantId} />}</RequireRestaurant>;
}
