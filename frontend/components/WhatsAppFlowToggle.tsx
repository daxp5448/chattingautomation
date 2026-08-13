"use client";

import { useEffect, useState } from "react";
import { apiFetch, ApiError } from "@/lib/api";
import type { Restaurant } from "@/lib/types";

// Provisions/tears down the native WhatsApp Flow ordering screen (see the approved
// "WhatsApp Flows for Ordering" plan) -- POST .../whatsapp-flow/enable does real Graph API
// work server-side (register a key, create+upload+publish a Flow), so this can take a few
// seconds and can genuinely fail with Meta's own account-standing errors (e.g. "Blocked by
// Integrity" on an unverified test number) -- surfaced verbatim, not swallowed, since it's
// usually something only the Owner can act on.
export function WhatsAppFlowToggle({ restaurantId }: { restaurantId: string }) {
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    try {
      const restaurant = await apiFetch<Restaurant>(`/restaurants/${restaurantId}`);
      setEnabled(!!restaurant.whatsapp_flow_order_id);
    } catch {
      setEnabled(false); // non-fatal -- this panel just stays in its default "off" state
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [restaurantId]);

  async function toggle() {
    setBusy(true);
    setError(null);
    try {
      await apiFetch(`/restaurants/${restaurantId}/whatsapp-flow/${enabled ? "disable" : "enable"}`, { method: "POST" });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to update WhatsApp Flow ordering");
    } finally {
      setBusy(false);
    }
  }

  if (enabled === null) return null;

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <h2 className="text-sm font-semibold text-slate-800">Native ordering screen (Beta)</h2>
      <p className="mt-1 text-xs text-slate-500">
        Lets a customer complete an order in one native WhatsApp screen (WhatsApp Flows) instead of a chain of
        chat messages -- for order-type businesses only. Requires a fully verified WhatsApp Business Account;
        Meta blocks publishing on unverified/test numbers.
      </p>
      {error && <p className="mt-2 rounded-lg bg-red-50 px-3 py-2 text-xs text-red-700">{error}</p>}
      <button
        onClick={toggle}
        disabled={busy}
        className={`mt-3 rounded-md px-4 py-1.5 text-sm font-medium shadow-sm disabled:opacity-60 ${
          enabled ? "border border-red-300 text-red-700 hover:bg-red-50" : "bg-primary text-white"
        }`}
      >
        {busy ? "Working..." : enabled ? "Disable" : "Enable"}
      </button>
    </div>
  );
}
