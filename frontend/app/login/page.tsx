"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { ApiError } from "@/lib/api";
import { LogoFull, LogoMark } from "@/components/Logo";
import { IconArrowRight, IconBarChart, IconEye, IconLock, IconMail, IconShieldCheck, IconZap } from "@/components/icons";

const FEATURES = [
  { icon: IconShieldCheck, title: "Secure", body: "Enterprise-grade data protection" },
  { icon: IconZap, title: "Smart", body: "Automate, manage and grow faster" },
  { icon: IconBarChart, title: "Scalable", body: "Built for businesses of every size" },
];

// Faint scattered-dot network graphic for the brand panel's bottom-left corner -- a CSS/
// SVG approximation of a "digital globe" motif, not a photographic asset. Pure decoration
// (aria-hidden), so any reasonable approximation is fine -- it never needs to be pixel-
// identical to a specific reference image.
function NetworkGraphic() {
  const dots = [
    [10, 92], [28, 78], [46, 88], [18, 62], [40, 55], [62, 66], [8, 40], [30, 30],
    [55, 40], [75, 50], [15, 15], [42, 10], [65, 22], [85, 32], [95, 55],
  ];
  const lines: [number, number][] = [[0, 1], [1, 2], [1, 3], [3, 4], [4, 5], [4, 7], [6, 7], [7, 8], [8, 9], [9, 14], [7, 10], [10, 11], [11, 12], [12, 13], [13, 14]];
  return (
    <svg
      aria-hidden
      viewBox="0 0 100 100"
      preserveAspectRatio="none"
      className="pointer-events-none absolute inset-x-0 bottom-0 h-[55%] w-full opacity-40"
    >
      {lines.map(([a, b], i) => (
        <line
          key={i}
          x1={dots[a][0]} y1={dots[a][1]} x2={dots[b][0]} y2={dots[b][1]}
          stroke="rgba(94,234,212,0.35)" strokeWidth={0.25}
        />
      ))}
      {dots.map(([x, y], i) => (
        <circle key={i} cx={x} cy={y} r={i % 3 === 0 ? 0.9 : 0.5} fill="rgba(94,234,212,0.6)" />
      ))}
    </svg>
  );
}

export default function LoginPage() {
  const { login } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [rememberMe, setRememberMe] = useState(false);
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
    <div className="flex min-h-screen bg-white">
      {/* Brand panel */}
      <div className="relative hidden w-[44%] flex-col justify-between overflow-hidden bg-secondary px-12 py-12 lg:flex">
        <div
          className="pointer-events-none absolute inset-0 opacity-70"
          style={{
            background:
              "radial-gradient(60% 50% at 15% 15%, rgba(13,148,136,0.35), transparent), radial-gradient(50% 45% at 85% 85%, rgba(94,234,212,0.18), transparent)",
          }}
        />
        <NetworkGraphic />
        <div className="relative flex flex-1 flex-col items-center justify-center text-center">
          <LogoFull width={300} className="mx-auto" />
          <p className="mt-10 max-w-sm text-[19px] font-medium leading-snug text-white">
            One flagship <span className="text-teal-300">WhatsApp</span> number.
            <br />
            Twelve industries. <span className="text-teal-300">Infinite possibilities</span>.
          </p>
          <p className="mt-4 max-w-sm text-[15px] leading-relaxed text-slate-300">
            A single control center for every business you run, streamlined, secure, and built for growth.
          </p>
        </div>
        <div className="relative space-y-6">
          <div className="grid grid-cols-3 gap-3 rounded-2xl border border-white/15 bg-white/[0.08] p-4 shadow-[0_8px_32px_rgba(0,0,0,0.25)] backdrop-blur-md">
            {FEATURES.map(({ icon: Icon, title, body }) => (
              <div key={title} className="space-y-1.5">
                <Icon size={18} className="text-teal-300" />
                <p className="text-[13px] font-semibold text-white">{title}</p>
                <p className="text-[11.5px] leading-snug text-slate-400">{body}</p>
              </div>
            ))}
          </div>
          <p className="text-xs text-slate-500">© {new Date().getFullYear()} KelvionTech. All rights reserved.</p>
        </div>
      </div>

      {/* Form panel */}
      <div className="flex flex-1 items-center justify-center p-6">
        <form onSubmit={handleSubmit} className="w-full max-w-sm space-y-6">
          <div className="flex flex-col gap-1 lg:hidden">
            <LogoMark size={32} className="mb-2" />
          </div>

          <div>
            <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Welcome back</h1>
            <p className="mt-1.5 text-sm text-slate-500">Sign in to manage your WhatsApp Business OS.</p>
          </div>

          {error && (
            <p className="rounded-lg border border-red-100 bg-red-50 px-3.5 py-2.5 text-sm text-red-700">{error}</p>
          )}

          <div className="space-y-4">
            <div className="space-y-1.5">
              <label className="text-sm font-medium text-slate-700">Email address</label>
              <div className="relative">
                <IconMail size={16} className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400" />
                <input
                  type="email"
                  required
                  autoFocus
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="you@business.com"
                  className="w-full rounded-lg border border-slate-200 bg-white py-2.5 pl-10 pr-3.5 text-sm text-slate-900 shadow-soft transition-colors placeholder:text-slate-400 focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
                />
              </div>
            </div>

            <div className="space-y-1.5">
              <label className="text-sm font-medium text-slate-700">Password</label>
              <div className="relative">
                <IconLock size={16} className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400" />
                <input
                  type={showPassword ? "text" : "password"}
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                  className="w-full rounded-lg border border-slate-200 bg-white py-2.5 pl-10 pr-10 text-sm text-slate-900 shadow-soft transition-colors placeholder:text-slate-400 focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((v) => !v)}
                  className="absolute right-3.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
                  aria-label={showPassword ? "Hide password" : "Show password"}
                >
                  <IconEye size={16} />
                </button>
              </div>
            </div>
          </div>

          <div className="flex items-center justify-between text-sm">
            <label className="flex items-center gap-2 text-slate-600">
              <input
                type="checkbox"
                checked={rememberMe}
                onChange={(e) => setRememberMe(e.target.checked)}
                className="h-4 w-4 rounded border-slate-300 text-primary focus:ring-primary"
              />
              Remember me
            </label>
            <a href="#" className="font-medium text-primary hover:text-primary-dark">
              Forgot password?
            </a>
          </div>

          <button
            type="submit"
            disabled={submitting}
            className="flex w-full items-center justify-center gap-2 rounded-lg bg-primary px-3 py-2.5 text-sm font-medium text-white shadow-soft transition-colors hover:bg-primary-dark disabled:opacity-60"
          >
            {submitting && <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/40 border-t-white" />}
            {submitting ? "Signing in…" : "Sign in"}
            {!submitting && <IconArrowRight size={16} />}
          </button>

          <p className="flex items-center justify-center gap-1.5 text-center text-xs text-slate-400">
            <IconShieldCheck size={13} />
            Protected access · KelvionTech Business OS
          </p>
        </form>
      </div>
    </div>
  );
}
