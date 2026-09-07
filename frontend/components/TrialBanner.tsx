"use client";

import { useState } from "react";
import { useCurrentRestaurant } from "@/lib/restaurant";
import { DemoPaywallModal } from "@/components/DemoPaywallModal";

// DEMO ONLY -- see backend/app/api/v1/routers/billing.py's module docstring. Soft banner,
// not a hard block: the dashboard stays fully usable either way (see the approved "Demo
// Billing" plan) -- this is purely a visible nudge, not enforcement.
export function TrialBanner() {
  const { restaurantId, billingStatus } = useCurrentRestaurant();
  const [showPaywall, setShowPaywall] = useState(false);

  if (!restaurantId || !billingStatus) return null;
  if (!billingStatus.trial_expired || billingStatus.is_demo_billing_paid) return null;

  return (
    <>
      <div className="flex items-center justify-between gap-3 border-b border-amber-200 bg-amber-50 px-4 py-2 text-sm">
        <p className="text-amber-800">
          <span className="font-medium">Your 7-day free trial has ended.</span> Pay to keep using KelvionTech
          Business OS.
        </p>
        <button
          onClick={() => setShowPaywall(true)}
          className="shrink-0 rounded-md bg-amber-600 px-3 py-1 text-xs font-medium text-white hover:bg-amber-700"
        >
          Pay Now
        </button>
      </div>
      {showPaywall && <DemoPaywallModal restaurantId={restaurantId} onClose={() => setShowPaywall(false)} />}
    </>
  );
}
