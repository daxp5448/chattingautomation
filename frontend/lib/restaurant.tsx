"use client";

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { apiFetch } from "./api";
import { useAuth } from "./auth";
import type { NicheTemplateSummary } from "./types";

interface RestaurantContextValue {
  restaurantId: string | null;
  setRestaurantId: (id: string) => void;
  // Feature Package entitlements for the current restaurant -- null (both the "not
  // loaded yet" and "unrestricted" states collapse to the same value on purpose: see
  // hasFeature below) until the restaurant fetch completes. Refetch after any action
  // that might change it (e.g. a super admin reassigning a package).
  enabledFeatures: string[] | null;
  refetchRestaurant: () => void;
  // enabled_features === null means unrestricted, mirroring backend
  // app/core/deps.py::require_feature's exact semantics -- always go through this
  // helper rather than reading enabledFeatures directly, so a page can't accidentally
  // hide a control before the restaurant has even loaded.
  hasFeature: (code: string) => boolean;
  // The current restaurant's niche (via Restaurant.niche_type -> matching
  // NicheTemplate), so the sidebar/pages can show niche-appropriate copy ("Services"
  // instead of "Menu") instead of one hardcoded label for every business. Null while
  // loading, for a legacy/custom business with no niche_type, or if the matching
  // template can't be resolved (e.g. deleted after this business copied from it).
  nicheTerminology: Record<string, unknown> | null;
  nicheModules: Record<string, boolean> | null;
  // Drives the Orders/Bookings/Appointments/Leads nav label (see layout.tsx) -- e.g.
  // "booking" for Hotel, "inquiry" for Real Estate/Jewellery, "appointment" for Salon/
  // Gym/Clinic, "order" for Restaurant/Grocery/Electronics/Retail.
  nicheActionType: "order" | "inquiry" | "appointment" | "booking" | null;
}

const RestaurantContext = createContext<RestaurantContextValue | undefined>(undefined);

/**
 * Non-super-admin users are locked to the restaurant on their JWT. A super admin
 * manages many restaurants, so they pick one on the Restaurants page and it's
 * remembered here (localStorage) for the rest of the dashboard.
 */
export function RestaurantProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const [restaurantId, setRestaurantIdState] = useState<string | null>(null);
  const [enabledFeatures, setEnabledFeatures] = useState<string[] | null>(null);
  const [nicheTerminology, setNicheTerminology] = useState<Record<string, unknown> | null>(null);
  const [nicheModules, setNicheModules] = useState<Record<string, boolean> | null>(null);
  const [nicheActionType, setNicheActionType] = useState<RestaurantContextValue["nicheActionType"]>(null);
  const [refetchTick, setRefetchTick] = useState(0);

  useEffect(() => {
    if (user?.role !== "super_admin") {
      setRestaurantIdState(user?.restaurant_id ?? null);
      return;
    }
    setRestaurantIdState(localStorage.getItem("selected_restaurant_id"));
  }, [user]);

  useEffect(() => {
    if (!restaurantId) {
      setEnabledFeatures(null);
      setNicheTerminology(null);
      setNicheModules(null);
      setNicheActionType(null);
      return;
    }
    apiFetch<{ enabled_features: string[] | null; niche_type: string | null }>(`/restaurants/${restaurantId}`)
      .then((r) => {
        setEnabledFeatures(r.enabled_features);
        if (!r.niche_type) {
          setNicheTerminology(null);
          setNicheModules(null);
          setNicheActionType(null);
          return;
        }
        // GET /niche-templates is readable by any authenticated role (only mutations are
        // Super-Admin-gated) -- one list call, matched by code, rather than a dedicated
        // "my niche" endpoint. See NicheTemplateSummary's docstring for why terminology/
        // default_modules ride on the summary already instead of a second round trip.
        apiFetch<NicheTemplateSummary[]>("/niche-templates")
          .then((templates) => {
            const match = templates.find((t) => t.code === r.niche_type);
            setNicheTerminology(match?.terminology ?? null);
            setNicheModules(match?.default_modules ?? null);
            setNicheActionType(match?.action_type ?? null);
          })
          .catch(() => {
            setNicheTerminology(null);
            setNicheModules(null);
            setNicheActionType(null);
          });
      })
      .catch(() => setEnabledFeatures(null)); // non-fatal -- null already means "unrestricted", the safe default
  }, [restaurantId, refetchTick]);

  function setRestaurantId(id: string) {
    localStorage.setItem("selected_restaurant_id", id);
    setRestaurantIdState(id);
  }

  const refetchRestaurant = useCallback(() => setRefetchTick((t) => t + 1), []);

  const hasFeature = useCallback((code: string) => enabledFeatures === null || enabledFeatures.includes(code), [enabledFeatures]);

  return (
    <RestaurantContext.Provider
      value={{ restaurantId, setRestaurantId, enabledFeatures, refetchRestaurant, hasFeature, nicheTerminology, nicheModules, nicheActionType }}
    >
      {children}
    </RestaurantContext.Provider>
  );
}

export function useCurrentRestaurant(): RestaurantContextValue {
  const ctx = useContext(RestaurantContext);
  if (!ctx) throw new Error("useCurrentRestaurant must be used within RestaurantProvider");
  return ctx;
}
