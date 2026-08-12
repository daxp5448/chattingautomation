"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useRequireAuth } from "@/lib/auth";
import { RestaurantProvider } from "@/lib/restaurant";

const NAV_ITEMS = [
  { href: "/dashboard", label: "Dashboard", icon: "📊" },
  { href: "/restaurants", label: "Restaurants", icon: "🏬" },
  { href: "/niches", label: "Niches", icon: "🧩" },
  { href: "/feature-packages", label: "Feature Packages", icon: "🎁" },
  { href: "/branches", label: "Branches", icon: "📍" },
  { href: "/menu", label: "Menu", icon: "🍽️" },
  { href: "/bot-builder", label: "Bot Builder", icon: "🤖" },
  { href: "/home-builder", label: "Home Builder", icon: "🏠" },
  { href: "/flow-builder", label: "Flow Builder", icon: "🧭" },
  { href: "/api-endpoints", label: "API Endpoints", icon: "🔌" },
  { href: "/whatsapp-templates", label: "WhatsApp Templates", icon: "📨" },
  { href: "/broadcasts", label: "Broadcasts", icon: "📣" },
  { href: "/coupons", label: "Coupons", icon: "🏷️" },
  { href: "/image-library", label: "Image Library", icon: "🖼️" },
  { href: "/orders", label: "Orders", icon: "🧾" },
  { href: "/customers", label: "Customers", icon: "👥" },
  { href: "/live-chat", label: "Live Chat", icon: "💬" },
];

const ROLE_LABELS: Record<string, string> = {
  super_admin: "Super Admin",
  owner: "Owner",
  manager: "Manager",
  cashier: "Cashier",
  kitchen: "Kitchen",
};

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const { user, loading, logout } = useRequireAuth();
  const pathname = usePathname();
  const router = useRouter();

  if (loading || !user) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-50 text-slate-500">
        <span className="h-5 w-5 animate-spin rounded-full border-2 border-slate-300 border-t-primary" />
        <span className="ml-3 text-sm">Loading...</span>
      </div>
    );
  }

  const initial = user.email ? user.email[0].toUpperCase() : "?";

  return (
    <RestaurantProvider>
      <div className="flex min-h-screen bg-slate-50">
        <aside className="flex h-screen w-60 shrink-0 flex-col border-r border-slate-200 bg-white">
          <div className="flex items-center gap-2 border-b border-slate-100 px-5 py-5">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-sm font-bold text-white">K</div>
            <div>
              <p className="text-sm font-semibold leading-tight text-slate-900">KelvionTech</p>
              <p className="text-[11px] text-slate-400">Restaurant Platform</p>
            </div>
          </div>

          <nav className="flex-1 space-y-0.5 overflow-y-auto p-3">
            {NAV_ITEMS.map((item) => {
              const active = pathname === item.href;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                    active ? "bg-primary text-white shadow-sm" : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
                  }`}
                >
                  <span className="text-base leading-none">{item.icon}</span>
                  {item.label}
                </Link>
              );
            })}
          </nav>

          <div className="border-t border-slate-100 p-3">
            <div className="mb-2 flex items-center gap-2 rounded-lg px-2 py-1.5">
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-slate-200 text-xs font-semibold text-slate-600">
                {initial}
              </div>
              <div className="min-w-0">
                <p className="truncate text-xs font-medium text-slate-700">{user.email}</p>
                <p className="text-[11px] text-slate-400">{ROLE_LABELS[user.role] ?? user.role}</p>
              </div>
            </div>
            <button
              onClick={async () => {
                await logout();
                router.replace("/login");
              }}
              className="w-full rounded-lg px-3 py-2 text-left text-sm font-medium text-slate-500 hover:bg-red-50 hover:text-red-600"
            >
              Sign out
            </button>
          </div>
        </aside>
        <main className="flex-1 overflow-y-auto p-8">
          <div className="mx-auto max-w-6xl">{children}</div>
        </main>
      </div>
    </RestaurantProvider>
  );
}
