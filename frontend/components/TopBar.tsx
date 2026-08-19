"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import { useCurrentRestaurant } from "@/lib/restaurant";
import type { Restaurant } from "@/lib/types";

// Persistent context bar shown above every dashboard page's own content -- previously
// nothing sat here, so a business admin (or a Super Admin bouncing between businesses)
// had no persistent reminder of which business they were currently looking at, only
// whatever a given page's own body happened to mention. Self-contained fetch (not read
// from RestaurantContext) since that context deliberately only keeps enabled_features/
// niche-derived terminology, not the restaurant's own name -- see lib/restaurant.tsx.
export function TopBar() {
  const { restaurantId } = useCurrentRestaurant();
  const [restaurant, setRestaurant] = useState<Restaurant | null>(null);

  useEffect(() => {
    if (!restaurantId) {
      setRestaurant(null);
      return;
    }
    let cancelled = false;
    apiFetch<Restaurant>(`/restaurants/${restaurantId}`)
      .then((r) => {
        if (!cancelled) setRestaurant(r);
      })
      .catch(() => {
        if (!cancelled) setRestaurant(null);
      });
    return () => {
      cancelled = true;
    };
  }, [restaurantId]);

  const today = new Date().toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" });

  return (
    <header className="sticky top-0 z-10 flex h-14 shrink-0 items-center justify-between border-b border-slate-100 bg-white/80 px-8 backdrop-blur">
      <div className="flex min-w-0 items-center gap-2.5">
        {restaurant ? (
          <>
            <span className="truncate text-[13.5px] font-medium text-slate-800">{restaurant.name}</span>
            {restaurant.niche_type && (
              <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-medium capitalize text-slate-500">
                {restaurant.niche_type.replace(/_/g, " ")}
              </span>
            )}
            {!restaurant.uses_generic_engine && (
              <span
                className="rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-medium text-amber-700"
                title="Original restaurant-only engine -- Flow Builder / Bot Preview have nothing to show for this business. Use Bot Builder / Home Builder instead."
              >
                Legacy
              </span>
            )}
            <span
              className={`flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium ${
                restaurant.whatsapp_phone_number_id ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-500"
              }`}
            >
              <span className={`h-1.5 w-1.5 rounded-full ${restaurant.whatsapp_phone_number_id ? "bg-emerald-500" : "bg-slate-400"}`} />
              {restaurant.whatsapp_phone_number_id ? "Connected" : "Not connected"}
            </span>
          </>
        ) : (
          <span className="text-[13.5px] font-medium text-slate-400">Platform overview</span>
        )}
      </div>
      <span className="hidden text-xs text-slate-400 sm:block">{today}</span>
    </header>
  );
}
