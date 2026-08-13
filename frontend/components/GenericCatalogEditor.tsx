"use client";

import { useEffect, useState, type FormEvent } from "react";
import { apiFetch, ApiError } from "@/lib/api";
import { ImageUploadWidget } from "@/components/ImageUploadWidget";
import { TemplateImageUpload } from "@/components/TemplateImageUpload";
import type { CatalogCategoryRow, CatalogItemRow, ImageRecord } from "@/lib/types";

// The generic-engine counterpart of MenuForRestaurant (legacy Category/Product) in
// page.tsx -- talks to /restaurants/{id}/catalog-categories|catalog-items instead
// (backend/app/api/v1/routers/catalog.py). Item photos go through the real Universal
// Image Processing Pipeline (ImageUploadWidget -- crop/replace/variants), the same
// pipeline generic_flow_engine.py's resolve_item_images already prefers when rendering
// the live bot. Category icons are a plain string field (CatalogCategory.image_url, no
// CatalogItem row to hang a pipeline Image off of), so they use the simpler permanent-URL
// uploader instead -- see catalog.py's upload-image endpoint for why.
export function GenericCatalogEditor({ restaurantId }: { restaurantId: string }) {
  const [categories, setCategories] = useState<CatalogCategoryRow[]>([]);
  const [items, setItems] = useState<CatalogItemRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [categoryName, setCategoryName] = useState("");
  const [creatingCategory, setCreatingCategory] = useState(false);

  const [itemName, setItemName] = useState("");
  const [itemPrice, setItemPrice] = useState("");
  const [itemCategoryId, setItemCategoryId] = useState("");
  const [creatingItem, setCreatingItem] = useState(false);

  const [expandedItemId, setExpandedItemId] = useState<string | null>(null);
  const [itemImages, setItemImages] = useState<Record<string, ImageRecord[]>>({});

  async function load() {
    setLoading(true);
    try {
      const [cats, its] = await Promise.all([
        apiFetch<CatalogCategoryRow[]>(`/restaurants/${restaurantId}/catalog-categories`),
        apiFetch<CatalogItemRow[]>(`/restaurants/${restaurantId}/catalog-items`),
      ]);
      setCategories(cats);
      setItems(its);
      if (cats.length > 0 && !itemCategoryId) setItemCategoryId(cats[0].id);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load catalog");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [restaurantId]);

  async function handleCreateCategory(e: FormEvent) {
    e.preventDefault();
    setCreatingCategory(true);
    setError(null);
    try {
      await apiFetch(`/restaurants/${restaurantId}/catalog-categories`, {
        method: "POST",
        body: JSON.stringify({ name: categoryName, display_order: categories.length }),
      });
      setCategoryName("");
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to create category");
    } finally {
      setCreatingCategory(false);
    }
  }

  async function updateCategory(id: string, patch: Partial<CatalogCategoryRow>) {
    try {
      await apiFetch(`/restaurants/${restaurantId}/catalog-categories/${id}`, { method: "PATCH", body: JSON.stringify(patch) });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to update category");
    }
  }

  async function deleteCategory(category: CatalogCategoryRow) {
    if (!window.confirm(`Delete "${category.name}"? This also removes every item in it that hasn't been ordered yet.`)) return;
    try {
      await apiFetch(`/restaurants/${restaurantId}/catalog-categories/${category.id}`, { method: "DELETE" });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to delete category");
    }
  }

  async function handleCreateItem(e: FormEvent) {
    e.preventDefault();
    setCreatingItem(true);
    setError(null);
    try {
      await apiFetch(`/restaurants/${restaurantId}/catalog-items`, {
        method: "POST",
        body: JSON.stringify({ name: itemName, price: itemPrice ? Number(itemPrice) : null, category_id: itemCategoryId }),
      });
      setItemName("");
      setItemPrice("");
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to create item");
    } finally {
      setCreatingItem(false);
    }
  }

  async function updateItem(id: string, patch: Partial<CatalogItemRow>) {
    try {
      await apiFetch(`/restaurants/${restaurantId}/catalog-items/${id}`, { method: "PATCH", body: JSON.stringify(patch) });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to update item");
    }
  }

  async function deleteItem(item: CatalogItemRow) {
    if (!window.confirm(`Delete "${item.name}"?`)) return;
    try {
      await apiFetch(`/restaurants/${restaurantId}/catalog-items/${item.id}`, { method: "DELETE" });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to delete item");
    }
  }

  async function toggleExpandItem(item: CatalogItemRow) {
    if (expandedItemId === item.id) {
      setExpandedItemId(null);
      return;
    }
    setExpandedItemId(item.id);
    if (!itemImages[item.id]) {
      try {
        const images = await apiFetch<ImageRecord[]>(`/restaurants/${restaurantId}/images?catalog_item_id=${item.id}`);
        setItemImages((prev) => ({ ...prev, [item.id]: images }));
      } catch {
        setItemImages((prev) => ({ ...prev, [item.id]: [] })); // non-fatal -- widget just starts empty
      }
    }
  }

  if (loading) {
    return (
      <div className="flex items-center gap-3 text-sm text-slate-500">
        <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-primary" />
        Loading catalog...
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Menu</h1>
        <p className="text-sm text-slate-500">Categories and items your customers see when they order on WhatsApp -- including photos.</p>
      </div>
      {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

      <section className="space-y-3">
        <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
          <span>📂</span> Categories
        </h2>
        <form onSubmit={handleCreateCategory} className="flex items-end gap-3 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <div>
            <label className="block text-xs font-medium text-slate-500">Name</label>
            <input required value={categoryName} onChange={(e) => setCategoryName(e.target.value)} placeholder="e.g. Gold Jewellery" className="rounded-md border border-slate-300 px-3 py-1.5 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary" />
          </div>
          <button type="submit" disabled={creatingCategory} className="rounded-md bg-primary px-4 py-1.5 text-sm font-medium text-white shadow-sm disabled:opacity-60">
            {creatingCategory ? "Adding..." : "+ Add category"}
          </button>
        </form>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {categories.map((c) => (
            <div key={c.id} className="space-y-2 rounded-xl border border-slate-200 bg-white p-3 shadow-sm">
              <div className="flex items-center justify-between gap-2">
                <input
                  value={c.name}
                  onChange={(e) => setCategories((prev) => prev.map((x) => (x.id === c.id ? { ...x, name: e.target.value } : x)))}
                  onBlur={(e) => updateCategory(c.id, { name: e.target.value })}
                  className="flex-1 rounded-md border border-slate-300 px-2 py-1 text-sm font-medium"
                />
                <button onClick={() => deleteCategory(c)} className="shrink-0 text-xs font-medium text-red-600 hover:underline">
                  Delete
                </button>
              </div>
              <TemplateImageUpload
                label="Category icon"
                value={c.image_url || ""}
                onChange={(url) => updateCategory(c.id, { image_url: url || null })}
                endpoint={`/restaurants/${restaurantId}/catalog-categories/upload-image`}
              />
              <button
                onClick={() => updateCategory(c.id, { visible: !c.visible })}
                className={`rounded-full px-2 py-0.5 text-xs font-medium ${c.visible ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-600"}`}
              >
                {c.visible ? "Visible -- click to hide" : "Hidden -- click to show"}
              </button>
            </div>
          ))}
          {categories.length === 0 && <p className="text-sm text-slate-400">No categories yet.</p>}
        </div>
      </section>

      <section className="space-y-3">
        <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
          <span>🍽️</span> Items
        </h2>
        <form onSubmit={handleCreateItem} className="flex flex-wrap items-end gap-3 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <div>
            <label className="block text-xs font-medium text-slate-500">Name</label>
            <input required value={itemName} onChange={(e) => setItemName(e.target.value)} className="rounded-md border border-slate-300 px-3 py-1.5 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary" />
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-500">Price</label>
            <input type="number" step="0.01" value={itemPrice} onChange={(e) => setItemPrice(e.target.value)} className="w-28 rounded-md border border-slate-300 px-3 py-1.5 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary" />
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-500">Category</label>
            <select value={itemCategoryId} onChange={(e) => setItemCategoryId(e.target.value)} className="rounded-md border border-slate-300 px-3 py-1.5 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary">
              {categories.map((c) => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </select>
          </div>
          <button type="submit" disabled={creatingItem || categories.length === 0} className="rounded-md bg-primary px-4 py-1.5 text-sm font-medium text-white shadow-sm disabled:opacity-60">
            {creatingItem ? "Adding..." : "+ Add item"}
          </button>
        </form>
        {categories.length === 0 && <p className="text-sm text-amber-600">Add a category first before adding items.</p>}

        <div className="space-y-2">
          {items.map((item) => (
            <div key={item.id} className="rounded-xl border border-slate-200 bg-white shadow-sm">
              <div className="flex items-center justify-between gap-3 px-4 py-3">
                <button type="button" onClick={() => toggleExpandItem(item)} className="flex flex-1 items-center gap-3 text-left">
                  {(() => {
                    // Prefer the real pipeline image once loaded (post-expand) -- the
                    // legacy `images` list goes stale the moment a real Image row exists
                    // for this item (see image_presenter.py's compat-shim docstring), so
                    // the legacy field is only a reasonable preview before the item has
                    // ever been expanded in this session.
                    const ready = itemImages[item.id]?.find((img) => img.status === "ready");
                    const thumb = ready ? ready.urls.thumbnail || ready.urls.website : item.images[0];
                    return thumb ? <img src={thumb} alt="" className="h-10 w-10 rounded-md object-cover" /> : null;
                  })()}
                  <div>
                    <span className="font-medium text-slate-800">{item.name}</span>
                    <span className="ml-2 text-xs text-slate-400">{categories.find((c) => c.id === item.category_id)?.name || "-"}</span>
                    <span className="ml-2 text-sm text-slate-600">{item.price ?? "-"}</span>
                  </div>
                </button>
                <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${item.available ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-600"}`}>
                  {item.available ? "Available" : "Unavailable"}
                </span>
                <button onClick={() => toggleExpandItem(item)} className="text-xs font-medium text-slate-500 hover:text-primary">
                  {expandedItemId === item.id ? "Close" : "Edit"}
                </button>
                <button onClick={() => deleteItem(item)} className="text-xs font-medium text-red-600 hover:underline">
                  Delete
                </button>
              </div>
              {expandedItemId === item.id && (
                <div className="space-y-3 border-t border-slate-100 p-4">
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="block text-xs font-medium text-slate-500">Name</label>
                      <input defaultValue={item.name} onBlur={(e) => updateItem(item.id, { name: e.target.value })} className="w-full rounded-md border border-slate-300 px-2 py-1 text-sm" />
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-slate-500">Price</label>
                      <input type="number" step="0.01" defaultValue={item.price ?? ""} onBlur={(e) => updateItem(item.id, { price: e.target.value === "" ? null : Number(e.target.value) })} className="w-full rounded-md border border-slate-300 px-2 py-1 text-sm" />
                    </div>
                    <div className="col-span-2">
                      <label className="block text-xs font-medium text-slate-500">Description</label>
                      <input defaultValue={item.description || ""} onBlur={(e) => updateItem(item.id, { description: e.target.value })} className="w-full rounded-md border border-slate-300 px-2 py-1 text-sm" />
                    </div>
                  </div>
                  <div className="flex gap-2">
                    <button onClick={() => updateItem(item.id, { available: !item.available })} className="rounded-md border border-slate-300 px-3 py-1 text-xs font-medium text-slate-700 hover:bg-slate-50">
                      {item.available ? "Mark unavailable" : "Mark available"}
                    </button>
                    <button onClick={() => updateItem(item.id, { is_featured: !item.is_featured })} className="rounded-md border border-slate-300 px-3 py-1 text-xs font-medium text-slate-700 hover:bg-slate-50">
                      {item.is_featured ? "Unmark special" : "Mark special"}
                    </button>
                  </div>
                  <div>
                    <p className="mb-1 text-xs font-medium text-slate-500">Photos</p>
                    <ImageUploadWidget
                      restaurantId={restaurantId}
                      imageType="product"
                      catalogItemId={item.id}
                      images={itemImages[item.id] || []}
                      onChange={(images) => {
                        setItemImages((prev) => ({ ...prev, [item.id]: images }));
                        load(); // resolve_item_images prefers these over the legacy list -- refresh so the row thumbnail updates too
                      }}
                    />
                  </div>
                </div>
              )}
            </div>
          ))}
          {items.length === 0 && <p className="text-sm text-slate-400">No items yet.</p>}
        </div>
      </section>
    </div>
  );
}
