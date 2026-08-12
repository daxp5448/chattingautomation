"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { ApiError } from "@/lib/api";

export default function LoginPage() {
  const { login } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(email, password);
      router.replace("/dashboard");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Login failed");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-slate-50 via-white to-primary/5 p-4">
      <form onSubmit={handleSubmit} className="w-full max-w-sm space-y-5 rounded-2xl border border-slate-200 bg-white p-8 shadow-lg shadow-slate-200/50">
        <div className="flex flex-col items-center text-center">
          <div className="mb-3 flex h-11 w-11 items-center justify-center rounded-xl bg-primary text-lg font-bold text-white">K</div>
          <h1 className="text-xl font-semibold text-slate-900">KelvionTech Admin</h1>
          <p className="text-sm text-slate-500">Sign in to manage your restaurant</p>
        </div>

        {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

        <div className="space-y-1">
          <label className="text-sm font-medium text-slate-700">Email</label>
          <input
            type="email"
            required
            autoFocus
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
          />
        </div>

        <div className="space-y-1">
          <label className="text-sm font-medium text-slate-700">Password</label>
          <input
            type="password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
          />
        </div>

        <button
          type="submit"
          disabled={submitting}
          className="w-full rounded-lg bg-primary px-3 py-2.5 text-sm font-medium text-white shadow-sm transition-opacity disabled:opacity-60"
        >
          {submitting ? "Signing in..." : "Sign in"}
        </button>
      </form>
    </div>
  );
}
