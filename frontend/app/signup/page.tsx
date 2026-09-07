"use client";

import { useEffect, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { apiFetch, ApiError } from "@/lib/api";
import { LogoFull, LogoMark } from "@/components/Logo";
import {
  IconArrowRight,
  IconBarChart,
  IconCheckCircle,
  IconEye,
  IconLock,
  IconMail,
  IconShieldCheck,
  IconStore,
  IconZap,
} from "@/components/icons";

const FEATURES = [
  { icon: IconShieldCheck, title: "Secure", body: "Enterprise-grade data protection" },
  { icon: IconZap, title: "Smart", body: "Automate, manage and grow faster" },
  { icon: IconBarChart, title: "Scalable", body: "Built for businesses of every size" },
];

interface Niche {
  code: string;
  name: string;
  icon: string | null;
}

function BrandPanel() {
  return (
    <div className="relative hidden w-[44%] flex-col justify-between overflow-hidden bg-secondary px-12 py-12 lg:flex">
      <div
        className="pointer-events-none absolute inset-0 opacity-70"
        style={{
          background:
            "radial-gradient(60% 50% at 15% 15%, rgba(13,148,136,0.35), transparent), radial-gradient(50% 45% at 85% 85%, rgba(94,234,212,0.18), transparent)",
        }}
      />
      <div className="relative flex flex-1 flex-col items-center justify-center text-center">
        <LogoFull width={300} className="mx-auto" />
        <p className="mt-10 max-w-sm text-[19px] font-medium leading-snug text-white">
          Your business on <span className="text-teal-300">WhatsApp</span>.
          <br />
          Live in <span className="text-teal-300">minutes</span>.
        </p>
        <p className="mt-4 max-w-sm text-[15px] leading-relaxed text-slate-300">
          Pick your industry and we'll set up your catalog, chat flow, and ordering bot automatically.
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
  );
}

export default function SignupPage() {
  const { signup, verifyOtp } = useAuth();
  const router = useRouter();

  const [step, setStep] = useState<"details" | "otp">("details");
  const [niches, setNiches] = useState<Niche[]>([]);
  const [nicheCode, setNicheCode] = useState("");

  const [businessName, setBusinessName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [showPassword, setShowPassword] = useState(false);

  const [restaurantId, setRestaurantId] = useState("");
  const [debugCode, setDebugCode] = useState<string | null>(null);
  const [code, setCode] = useState("");

  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    apiFetch<Niche[]>("/signup/niches")
      .then(setNiches)
      .catch(() => setError("Couldn't load the industry list. Please refresh and try again."));
  }, []);

  async function handleDetails(e: FormEvent) {
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
    if (!nicheCode) {
      setError("Pick the industry that best describes your business.");
      return;
    }

    setSubmitting(true);
    try {
      const result = await signup({
        business_name: businessName,
        owner_email: email,
        password,
        niche_code: nicheCode,
      });
      setRestaurantId(result.restaurant_id);
      setDebugCode(result.debug_otp_code);
      setStep("otp");
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.status === 409
            ? "An account with this email already exists. Try signing in instead."
            : err.message
          : "Something went wrong. Please try again."
      );
    } finally {
      setSubmitting(false);
    }
  }

  async function handleOtp(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await verifyOtp(restaurantId, code);
      router.replace("/dashboard");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleResend() {
    setError(null);
    setNotice(null);
    try {
      const result = await apiFetch<{ sent: boolean; debug_otp_code: string | null }>("/signup/resend-otp", {
        method: "POST",
        body: JSON.stringify({ restaurant_id: restaurantId }),
      });
      setDebugCode(result.debug_otp_code);
      setNotice("We've sent a new code to your email.");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't resend the code. Please try again.");
    }
  }

  return (
    <div className="flex min-h-screen bg-white">
      <BrandPanel />

      <div className="flex flex-1 items-center justify-center p-6">
        {step === "details" ? (
          <form onSubmit={handleDetails} className="w-full max-w-md space-y-6">
            <div className="flex flex-col gap-1 lg:hidden">
              <LogoMark size={32} className="mb-2" />
            </div>

            <div>
              <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Create your account</h1>
              <p className="mt-1.5 text-sm text-slate-500">
                Already have one?{" "}
                <a href="/login" className="font-medium text-primary hover:text-primary-dark">
                  Sign in
                </a>
              </p>
            </div>

            {error && (
              <p className="rounded-lg border border-red-100 bg-red-50 px-3.5 py-2.5 text-sm text-red-700">{error}</p>
            )}

            <div className="space-y-4">
              <div className="space-y-1.5">
                <label className="text-sm font-medium text-slate-700">Business name</label>
                <div className="relative">
                  <IconStore size={16} className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400" />
                  <input
                    required
                    autoFocus
                    value={businessName}
                    onChange={(e) => setBusinessName(e.target.value)}
                    placeholder="Bella Napoli Pizzeria"
                    className="w-full rounded-lg border border-slate-200 bg-white py-2.5 pl-10 pr-3.5 text-sm text-slate-900 shadow-soft transition-colors placeholder:text-slate-400 focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
                  />
                </div>
              </div>

              <div className="space-y-1.5">
                <label className="text-sm font-medium text-slate-700">Email address</label>
                <div className="relative">
                  <IconMail size={16} className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400" />
                  <input
                    type="email"
                    required
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="you@business.com"
                    className="w-full rounded-lg border border-slate-200 bg-white py-2.5 pl-10 pr-3.5 text-sm text-slate-900 shadow-soft transition-colors placeholder:text-slate-400 focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <label className="text-sm font-medium text-slate-700">Password</label>
                  <div className="relative">
                    <IconLock size={16} className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400" />
                    <input
                      type={showPassword ? "text" : "password"}
                      required
                      minLength={8}
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
                <div className="space-y-1.5">
                  <label className="text-sm font-medium text-slate-700">Confirm</label>
                  <input
                    type={showPassword ? "text" : "password"}
                    required
                    minLength={8}
                    value={confirm}
                    onChange={(e) => setConfirm(e.target.value)}
                    placeholder="••••••••"
                    className="w-full rounded-lg border border-slate-200 bg-white px-3.5 py-2.5 text-sm text-slate-900 shadow-soft transition-colors placeholder:text-slate-400 focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
                  />
                </div>
              </div>

              <div className="space-y-1.5">
                <label className="text-sm font-medium text-slate-700">What kind of business is it?</label>
                <p className="text-xs text-slate-400">
                  We'll pre-build your catalog and chat flow from this — you can change everything later.
                </p>
                <div className="grid max-h-56 grid-cols-2 gap-2 overflow-y-auto rounded-lg border border-slate-200 p-2 sm:grid-cols-3">
                  {niches.map((n) => (
                    <button
                      key={n.code}
                      type="button"
                      onClick={() => setNicheCode(n.code)}
                      className={`flex flex-col items-center gap-1 rounded-lg border px-2 py-2.5 text-center text-[12px] transition-colors ${
                        nicheCode === n.code
                          ? "border-primary bg-primary/5 font-medium text-primary"
                          : "border-slate-200 text-slate-600 hover:border-slate-300 hover:bg-slate-50"
                      }`}
                    >
                      <span className="text-base leading-none">{n.icon ?? "•"}</span>
                      {n.name}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            <button
              type="submit"
              disabled={submitting}
              className="flex w-full items-center justify-center gap-2 rounded-lg bg-primary px-3 py-2.5 text-sm font-medium text-white shadow-soft transition-colors hover:bg-primary-dark disabled:opacity-60"
            >
              {submitting && <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/40 border-t-white" />}
              {submitting ? "Creating your account…" : "Create account"}
              {!submitting && <IconArrowRight size={16} />}
            </button>
          </form>
        ) : (
          <form onSubmit={handleOtp} className="w-full max-w-sm space-y-6">
            <div>
              <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Check your email</h1>
              <p className="mt-1.5 text-sm text-slate-500">
                We sent a 6-digit code to <span className="font-medium text-slate-700">{email}</span>. It expires in 10
                minutes.
              </p>
            </div>

            {error && (
              <p className="rounded-lg border border-red-100 bg-red-50 px-3.5 py-2.5 text-sm text-red-700">{error}</p>
            )}
            {notice && (
              <p className="rounded-lg border border-emerald-100 bg-emerald-50 px-3.5 py-2.5 text-sm text-emerald-700">
                {notice}
              </p>
            )}
            {debugCode && (
              <p className="rounded-lg border border-amber-200 bg-amber-50 px-3.5 py-2.5 text-sm text-amber-800">
                Dev mode — your code is <span className="font-mono font-semibold">{debugCode}</span> (this is never
                shown in production).
              </p>
            )}

            <div className="space-y-1.5">
              <label className="text-sm font-medium text-slate-700">Verification code</label>
              <input
                required
                autoFocus
                inputMode="numeric"
                pattern="[0-9]{6}"
                maxLength={6}
                value={code}
                onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
                placeholder="123456"
                className="w-full rounded-lg border border-slate-200 bg-white px-3.5 py-2.5 text-center font-mono text-lg tracking-[0.4em] text-slate-900 shadow-soft transition-colors placeholder:tracking-normal placeholder:text-slate-300 focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
              />
            </div>

            <button
              type="submit"
              disabled={submitting || code.length !== 6}
              className="flex w-full items-center justify-center gap-2 rounded-lg bg-primary px-3 py-2.5 text-sm font-medium text-white shadow-soft transition-colors hover:bg-primary-dark disabled:opacity-60"
            >
              {submitting && <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/40 border-t-white" />}
              {submitting ? "Verifying…" : "Verify & continue"}
              {!submitting && <IconCheckCircle size={16} />}
            </button>

            <button
              type="button"
              onClick={handleResend}
              className="w-full text-center text-sm text-slate-500 hover:text-slate-700"
            >
              Didn't get it? Resend code
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
