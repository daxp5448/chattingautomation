"use client";

import { Suspense, useState, type FormEvent } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { apiFetch, ApiError } from "@/lib/api";
import { IconCheckCircle } from "@/components/icons";

export default function SetupPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-slate-50 via-white to-primary/5">
          <span className="h-5 w-5 animate-spin rounded-full border-2 border-slate-300 border-t-primary" />
        </div>
      }
    >
      <SetupForm />
    </Suspense>
  );
}

function SetupForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const token = searchParams.get("token") ?? "";

  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);

    if (password !== confirm) {
      setError("Passwords don't match.");
      return;
    }
    if (password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }

    setSubmitting(true);
    try {
      await apiFetch("/auth/setup", { method: "POST", body: JSON.stringify({ token, password }) });
      setDone(true);
      setTimeout(() => router.replace("/login"), 2000);
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.status === 400
            ? "This setup link is invalid or has already been used or has expired. Ask whoever created your account for a new one."
            : err.message
          : "Something went wrong. Please try again."
      );
    } finally {
      setSubmitting(false);
    }
  }

  if (!token) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-slate-50 via-white to-primary/5 p-4">
        <div className="w-full max-w-sm rounded-2xl border border-slate-200 bg-white p-8 text-center shadow-lg shadow-slate-200/50">
          <h1 className="text-lg font-semibold text-slate-900">Missing setup link</h1>
          <p className="mt-2 text-sm text-slate-500">
            This page needs the link exactly as it was shared with you — open that link again rather than
            navigating here directly.
          </p>
        </div>
      </div>
    );
  }

  if (done) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-slate-50 via-white to-primary/5 p-4">
        <div className="w-full max-w-sm rounded-2xl border border-slate-200 bg-white p-8 text-center shadow-lg shadow-slate-200/50">
          <h1 className="flex items-center justify-center gap-2 text-lg font-semibold text-slate-900">
            <IconCheckCircle size={18} className="text-emerald-500" /> Password set
          </h1>
          <p className="mt-2 text-sm text-slate-500">Taking you to sign in...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-slate-50 via-white to-primary/5 p-4">
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-sm space-y-5 rounded-2xl border border-slate-200 bg-white p-8 shadow-lg shadow-slate-200/50"
      >
        <div className="flex flex-col items-center text-center">
          <div className="mb-3 flex h-11 w-11 items-center justify-center rounded-xl bg-primary text-lg font-bold text-white">
            K
          </div>
          <h1 className="text-xl font-semibold text-slate-900">Set your password</h1>
          <p className="text-sm text-slate-500">Choose a password for your business's dashboard login.</p>
        </div>

        {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

        <div className="space-y-1">
          <label className="text-sm font-medium text-slate-700">New password</label>
          <input
            type="password"
            required
            autoFocus
            minLength={8}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
          />
          <p className="text-xs text-slate-400">At least 8 characters.</p>
        </div>

        <div className="space-y-1">
          <label className="text-sm font-medium text-slate-700">Confirm password</label>
          <input
            type="password"
            required
            minLength={8}
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
          />
        </div>

        <button
          type="submit"
          disabled={submitting}
          className="w-full rounded-lg bg-primary px-3 py-2.5 text-sm font-medium text-white shadow-sm transition-opacity disabled:opacity-60"
        >
          {submitting ? "Setting password..." : "Set password & continue"}
        </button>
      </form>
    </div>
  );
}
