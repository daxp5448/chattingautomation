"use client";

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { apiFetch } from "./api";

export type Role = "super_admin" | "owner" | "manager" | "cashier" | "kitchen";

interface Claims {
  id: string;
  role: Role;
  restaurant_id: string | null;
  email: string;
}

export interface SignupPayload {
  business_name: string;
  owner_email: string;
  password: string;
  niche_code: string;
}

export interface SignupResult {
  restaurant_id: string;
  owner_email: string;
  // Only returned outside production, so local/staging signups work without SMTP -- see
  // app/api/v1/routers/signup.py::_debug_otp.
  debug_otp_code: string | null;
}

interface AuthContextValue {
  user: Claims | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  signup: (payload: SignupPayload) => Promise<SignupResult>;
  verifyOtp: (restaurantId: string, code: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<Claims | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // The session lives in an httpOnly cookie the browser sends automatically -- there's
    // nothing to read client-side, so ask the backend who (if anyone) it belongs to.
    apiFetch<Claims>("/auth/me")
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setLoading(false));
  }, []);

  async function login(email: string, password: string) {
    await apiFetch("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) });
    const me = await apiFetch<Claims>("/auth/me");
    setUser(me);
  }

  async function signup(payload: SignupPayload) {
    // No session exists yet -- the account isn't usable until the OTP is verified, so
    // this deliberately doesn't touch `user` state the way login() does.
    return apiFetch<SignupResult>("/signup", { method: "POST", body: JSON.stringify(payload) });
  }

  async function verifyOtp(restaurantId: string, code: string) {
    await apiFetch("/signup/verify-otp", {
      method: "POST",
      body: JSON.stringify({ restaurant_id: restaurantId, code }),
    });
    const me = await apiFetch<Claims>("/auth/me");
    setUser(me);
  }

  async function logout() {
    try {
      await apiFetch("/auth/logout", { method: "POST" });
    } catch {
      // Cookies may already be gone/expired -- clearing local state below still succeeds.
    }
    setUser(null);
  }

  return (
    <AuthContext.Provider value={{ user, loading, login, signup, verifyOtp, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}

export function useRequireAuth(): AuthContextValue {
  const auth = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!auth.loading && !auth.user) {
      router.replace("/login");
    }
  }, [auth.loading, auth.user, router]);

  return auth;
}
