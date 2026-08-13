"use client";

import { useEffect, useState, type FormEvent } from "react";
import { apiFetch, ApiError } from "@/lib/api";
import { RequireRestaurant } from "@/components/RequireRestaurant";
import { GenericCatalogEditor } from "@/components/GenericCatalogEditor";
import type { Category, Product, Restaurant } from "@/lib/types";

function MenuForRestaurant({ restaurantId }: { restaurantId: string }) {
  const [categories, setCategories] = useState<Category[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const [categoryName, setCategoryName] = useState("");
  const [creatingCategory, setCreatingCategory] = useState(false);

  const [productName, setProductName] = useState("");
  const [productPrice, setProductPrice] = useState("");
  const [productCategoryId, setProductCategoryId] = useState("");
  const [creatingProduct, setCreatingProduct] = useState(false);

  async function load() {
    setLoading(true);
    try {
      const [cats, prods] = await Promise.all([
        apiFetch<Category[]>(`/restaurants/${restaurantId}/categories`),
        apiFetch<Product[]>(`/restaurants/${restaurantId}/products`),
      ]);
      setCategories(cats);
      setProducts(prods);
      if (cats.length > 0 && !productCategoryId) setProductCategoryId(cats[0].id);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load menu");
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
      await apiFetch(`/restaurants/${restaurantId}/categories`, {
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

  async function handleCreateProduct(e: FormEvent) {
    e.preventDefault();
    setCreatingProduct(true);
    setError(null);
    try {
      await apiFetch(`/restaurants/${restaurantId}/products`, {
        method: "POST",
        body: JSON.stringify({ name: productName, price: Number(productPrice), category_id: productCategoryId }),
      });
      setProductName("");
      setProductPrice("");
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to create product");
    } finally {
      setCreatingProduct(false);
    }
  }

  async function toggleCategoryVisible(category: Category) {
    try {
      await apiFetch(`/restaurants/${restaurantId}/categories/${category.id}`, {
        method: "PATCH",
        body: JSON.stringify({ visible: !category.visible }),
      });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to update category");
    }
  }

  async function deleteCategory(category: Category) {
    if (
      !window.confirm(
        `Delete "${category.name}"? This also removes every product in it that hasn't been ordered yet. Products with order history can't be deleted and will block this.`
      )
    ) {
      return;
    }
    try {
      await apiFetch(`/restaurants/${restaurantId}/categories/${category.id}`, { method: "DELETE" });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to delete category");
    }
  }

  async function toggleAvailable(product: Product) {
    try {
      await apiFetch(`/restaurants/${restaurantId}/products/${product.id}`, {
        method: "PATCH",
        body: JSON.stringify({ available: !product.available }),
      });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to update product");
    }
  }

  async function toggleFeatured(product: Product) {
    try {
      await apiFetch(`/restaurants/${restaurantId}/products/${product.id}`, {
        method: "PATCH",
        body: JSON.stringify({ is_featured: !product.is_featured }),
      });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to update product");
    }
  }

  if (loading) {
    return (
      <div className="flex items-center gap-3 text-sm text-slate-500">
        <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-primary" />
        Loading menu...
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Menu</h1>
        <p className="text-sm text-slate-500">Categories and items your customers see when they order on WhatsApp.</p>
      </div>
      {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

      <section className="space-y-3">
        <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
          <span>📂</span> Categories
        </h2>
        <form onSubmit={handleCreateCategory} className="flex items-end gap-3 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <div>
            <label className="block text-xs font-medium text-slate-500">Name</label>
            <input required value={categoryName} onChange={(e) => setCategoryName(e.target.value)} placeholder="e.g. Pizza" className="rounded-md border border-slate-300 px-3 py-1.5 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary" />
          </div>
          <button type="submit" disabled={creatingCategory} className="rounded-md bg-primary px-4 py-1.5 text-sm font-medium text-white shadow-sm disabled:opacity-60">
            {creatingCategory ? "Adding..." : "+ Add category"}
          </button>
        </form>
        <div className="flex flex-wrap gap-2">
          {categories.map((c) => (
            <div key={c.id} className="flex items-center gap-2 rounded-full border border-slate-200 bg-white px-3 py-1 text-sm text-slate-700 shadow-sm">
              <span>{c.name}</span>
              <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${c.visible ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-600"}`}>
                {c.visible ? "Visible" : "Hidden"}
              </span>
              <button onClick={() => toggleCategoryVisible(c)} className="text-xs font-medium text-slate-500 hover:text-primary hover:underline">
                {c.visible ? "Hide" : "Show"}
              </button>
              <button onClick={() => deleteCategory(c)} className="text-xs font-medium text-red-600 hover:underline">
                Delete
              </button>
            </div>
          ))}
          {categories.length === 0 && <p className="text-sm text-slate-400">No categories yet.</p>}
        </div>
      </section>

      <section className="space-y-3">
        <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
          <span>🍽️</span> Products
        </h2>
        <form onSubmit={handleCreateProduct} className="flex flex-wrap items-end gap-3 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <div>
            <label className="block text-xs font-medium text-slate-500">Name</label>
            <input required value={productName} onChange={(e) => setProductName(e.target.value)} className="rounded-md border border-slate-300 px-3 py-1.5 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary" />
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-500">Price</label>
            <input required type="number" step="0.01" value={productPrice} onChange={(e) => setProductPrice(e.target.value)} className="w-28 rounded-md border border-slate-300 px-3 py-1.5 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary" />
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-500">Category</label>
            <select value={productCategoryId} onChange={(e) => setProductCategoryId(e.target.value)} className="rounded-md border border-slate-300 px-3 py-1.5 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary">
              {categories.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </div>
          <button type="submit" disabled={creatingProduct || categories.length === 0} className="rounded-md bg-primary px-4 py-1.5 text-sm font-medium text-white shadow-sm disabled:opacity-60">
            {creatingProduct ? "Adding..." : "+ Add product"}
          </button>
        </form>
        {categories.length === 0 && <p className="text-sm text-amber-600">Add a category first before adding products.</p>}

        <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-3">Name</th>
                <th className="px-4 py-3">Category</th>
                <th className="px-4 py-3">Price</th>
                <th className="px-4 py-3">Available</th>
                <th className="px-4 py-3">Today&apos;s Special</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody>
              {products.map((p) => (
                <tr key={p.id} className="border-t border-slate-100 hover:bg-slate-50/60">
                  <td className="px-4 py-3 font-medium text-slate-800">{p.name}</td>
                  <td className="px-4 py-3 text-slate-500">{categories.find((c) => c.id === p.category_id)?.name || "-"}</td>
                  <td className="px-4 py-3 text-slate-700">{p.price}</td>
                  <td className="px-4 py-3">
                    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${p.available ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-600"}`}>
                      {p.available ? "Available" : "Unavailable"}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${p.is_featured ? "bg-amber-100 text-amber-700" : "bg-slate-100 text-slate-600"}`}>
                      {p.is_featured ? "⭐ Special" : "-"}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right space-x-2 whitespace-nowrap">
                    <button onClick={() => toggleFeatured(p)} className="rounded-md border border-slate-300 px-3 py-1 text-xs font-medium text-slate-700 hover:bg-slate-50">
                      {p.is_featured ? "Unmark special" : "Mark special"}
                    </button>
                    <button onClick={() => toggleAvailable(p)} className="rounded-md border border-slate-300 px-3 py-1 text-xs font-medium text-slate-700 hover:bg-slate-50">
                      {p.available ? "Mark unavailable" : "Mark available"}
                    </button>
                  </td>
                </tr>
              ))}
              {products.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-sm text-slate-400">
                    No products yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function MenuRouter({ restaurantId }: { restaurantId: string }) {
  // niche-provisioned businesses (every one of the 12 niches, including every Demo Bot
  // restaurant) store their catalog in CatalogCategory/CatalogItem, not the legacy
  // Category/Product tables this page's own /categories and /products endpoints read --
  // those return nothing for such a business (confirmed: 0 legacy rows even for a fully
  // provisioned demo restaurant). uses_generic_engine is the same flag the webhook router
  // already uses to pick which conversation engine runs, so it's the correct switch here
  // too.
  const [usesGenericEngine, setUsesGenericEngine] = useState<boolean | null>(null);

  useEffect(() => {
    apiFetch<Restaurant>(`/restaurants/${restaurantId}`)
      .then((r) => setUsesGenericEngine(r.uses_generic_engine))
      .catch(() => setUsesGenericEngine(false)); // safe fallback -- legacy menu builder always works for a Custom/Legacy business
  }, [restaurantId]);

  if (usesGenericEngine === null) {
    return (
      <div className="flex items-center gap-3 text-sm text-slate-500">
        <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-primary" />
        Loading...
      </div>
    );
  }

  return usesGenericEngine ? <GenericCatalogEditor restaurantId={restaurantId} /> : <MenuForRestaurant restaurantId={restaurantId} />;
}

export default function MenuPage() {
  return <RequireRestaurant>{(restaurantId) => <MenuRouter restaurantId={restaurantId} />}</RequireRestaurant>;
}
