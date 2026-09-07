"use client";

import { useState } from "react";
import { apiFetch, ApiError } from "@/lib/api";
import { useCurrentRestaurant } from "@/lib/restaurant";
import { IconCheckCircle, IconDollarSign, IconX } from "@/components/icons";

interface Props {
  restaurantId: string;
  onClose: () => void;
}

// DEMO ONLY -- no real payment gateway (Razorpay/Cashfree/Stripe) is called anywhere
// here. See backend/app/api/v1/routers/billing.py's module docstring. POST .../demo-pay
// IS the fake charge: one click, one flag flip server-side, nothing else.
export function DemoPaywallModal({ restaurantId, onClose }: Props) {
  const { refetchRestaurant } = useCurrentRestaurant();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  async function handlePay() {
    setSubmitting(true);
    setError(null);
    try {
      // Purely cosmetic delay so the demo *feels* like a real checkout happened --
      // nothing is actually processing.
      await new Promise((resolve) => setTimeout(resolve, 1200));
      await apiFetch(`/restaurants/${restaurantId}/billing/demo-pay`, { method: "POST" });
      setDone(true);
      refetchRestaurant();
      setTimeout(onClose, 1200);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="relative w-full max-w-sm rounded-xl bg-white p-6 shadow-xl">
        <button
          onClick={onClose}
          className="absolute right-4 top-4 text-slate-400 hover:text-slate-600"
          aria-label="Close"
        >
          <IconX size={16} />
        </button>

        {done ? (
          <div className="flex flex-col items-center gap-2 py-6 text-center">
            <IconCheckCircle size={32} className="text-emerald-500" />
            <h3 className="text-base font-semibold text-slate-900">Payment successful</h3>
            <p className="text-sm text-slate-500">You&apos;re all set — thanks for continuing with us.</p>
          </div>
        ) : (
          <>
            <div className="flex flex-col items-center text-center">
              <div className="mb-3 flex h-11 w-11 items-center justify-center rounded-xl bg-primary/10 text-primary">
                <IconDollarSign size={20} />
              </div>
              <h3 className="text-lg font-semibold text-slate-900">Continue using KelvionTech Business OS</h3>
              <p className="mt-1 text-sm text-slate-500">Your 7-day free trial has ended.</p>
            </div>

            <div className="my-5 rounded-lg border border-slate-200 bg-slate-50 px-4 py-3 text-center">
              <p className="text-2xl font-semibold text-slate-900">
                ₹999<span className="text-sm font-normal text-slate-500"> / month</span>
              </p>
            </div>

            {error && (
              <p className="mb-3 rounded-lg border border-red-100 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>
            )}

            <button
              onClick={handlePay}
              disabled={submitting}
              className="flex w-full items-center justify-center gap-2 rounded-lg bg-primary px-3 py-2.5 text-sm font-medium text-white shadow-soft transition-colors hover:bg-primary-dark disabled:opacity-60"
            >
              {submitting && <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/40 border-t-white" />}
              {submitting ? "Processing…" : "Pay ₹999 & Continue"}
            </button>
            <p className="mt-2 text-center text-xs text-slate-400">Demo mode — no real payment is processed.</p>
          </>
        )}
      </div>
    </div>
  );
}
