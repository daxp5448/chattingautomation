"use client";

import type { ComponentType } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useRequireAuth } from "@/lib/auth";
import { RestaurantProvider, useCurrentRestaurant } from "@/lib/restaurant";
import { LogoLockup, LogoMark } from "@/components/Logo";
import { TopBar } from "@/components/TopBar";
import {
  type IconProps,
  IconDashboard,
  IconBuilding,
  IconLayers,
  IconGift,
  IconMapPin,
  IconPackage,
  IconMessageSquare,
  IconBot,
  IconHome,
  IconWorkflow,
  IconEye,
  IconPlug,
  IconSend,
  IconMegaphone,
  IconTag,
  IconHelpCircle,
  IconImage,
  IconFolder,
  IconReceipt,
  IconUsers,
  IconMessageCircle,
  IconMonitor,
  IconShieldSearch,
  IconSettings,
} from "@/components/icons";

type Role = "super_admin" | "owner" | "manager" | "cashier" | "kitchen";

interface NavItem {
  href: string;
  label: string;
  icon: ComponentType<IconProps>;
  // Undefined = every role sees it. Otherwise the item is hidden entirely for any role
  // not listed -- e.g. Businesses/Niches/Feature Packages/API Endpoints/Audit Log are
  // platform-configuration surfaces a business's own staff should never even see in the
  // sidebar, not just be blocked from by a 403 after clicking in.
  roles?: Role[];
  // Matches a Feature Package entitlement code (see backend app/core/deps.py::
  // require_feature) -- hidden when the current business's plan doesn't include it,
  // reusing the same hasFeature() gate every page already checks itself, applied one
  // level up so the sidebar doesn't even offer a route that would 403/show a "not
  // included" notice on click.
  featureCode?: string;
  // Niche-driven label override key (see NicheTemplate.terminology, e.g. catalog_label:
  // "Services" for a salon vs "Menu" for a restaurant) -- falls back to `label` when the
  // current business has no niche/terminology set (legacy/custom businesses).
  terminologyKey?: string;
  // Label per NicheTemplate.action_type (order/inquiry/appointment/booking) -- e.g. the
  // Orders nav item reads as "Bookings" for Hotel, "Leads" for Real Estate/Jewellery,
  // "Appointments" for Salon/Gym/Clinic, "Orders" for Restaurant/Grocery/Electronics/
  // Retail. Falls back to `label` for a legacy/custom business with no niche_type.
  actionTypeLabels?: Record<string, string>;
}

const ORDERS_LABEL_BY_ACTION_TYPE: Record<string, string> = {
  order: "Orders",
  inquiry: "Leads",
  appointment: "Appointments",
  booking: "Bookings",
};

const NAV_ITEMS: NavItem[] = [
  { href: "/dashboard", label: "Dashboard", icon: IconDashboard },
  { href: "/restaurants", label: "Businesses", icon: IconBuilding, roles: ["super_admin"] },
  { href: "/niches", label: "Niches", icon: IconLayers, roles: ["super_admin"] },
  { href: "/feature-packages", label: "Feature Packages", icon: IconGift, roles: ["super_admin"] },
  { href: "/branches", label: "Branches", icon: IconMapPin, roles: ["super_admin", "owner", "manager"] },
  { href: "/menu", label: "Menu", icon: IconPackage, roles: ["super_admin", "owner", "manager"], terminologyKey: "catalog_label" },
  { href: "/messages", label: "Messages", icon: IconMessageSquare, roles: ["super_admin", "owner", "manager"] },
  { href: "/bot-builder", label: "Bot Builder", icon: IconBot, roles: ["super_admin", "owner", "manager"] },
  { href: "/home-builder", label: "Home Builder", icon: IconHome, roles: ["super_admin", "owner", "manager"] },
  { href: "/flow-builder", label: "Flow Builder", icon: IconWorkflow, roles: ["super_admin", "owner", "manager"] },
  { href: "/bot-preview", label: "Bot Preview", icon: IconEye, roles: ["super_admin", "owner", "manager"] },
  { href: "/api-endpoints", label: "API Endpoints", icon: IconPlug, roles: ["super_admin"] },
  { href: "/whatsapp-templates", label: "WhatsApp Templates", icon: IconSend, roles: ["super_admin", "owner", "manager"], featureCode: "whatsapp_template_manager" },
  { href: "/broadcasts", label: "Broadcasts", icon: IconMegaphone, roles: ["super_admin", "owner", "manager"], featureCode: "broadcasts" },
  { href: "/coupons", label: "Coupons", icon: IconTag, roles: ["super_admin", "owner", "manager"], featureCode: "coupons" },
  { href: "/faq", label: "FAQ", icon: IconHelpCircle, roles: ["super_admin", "owner", "manager"], featureCode: "faq_autoresponder" },
  { href: "/image-library", label: "Image Library", icon: IconImage, roles: ["super_admin"] },
  { href: "/media-library", label: "Media Library", icon: IconFolder, roles: ["super_admin", "owner", "manager"] },
  { href: "/orders", label: "Orders", icon: IconReceipt, actionTypeLabels: ORDERS_LABEL_BY_ACTION_TYPE },
  { href: "/customers", label: "Customers", icon: IconUsers, roles: ["super_admin", "owner", "manager", "cashier"] },
  { href: "/live-chat", label: "Live Chat", icon: IconMessageCircle, roles: ["super_admin", "owner", "manager", "cashier"], featureCode: "live_chat_handoff" },
  { href: "/displays", label: "Displays", icon: IconMonitor, roles: ["super_admin", "owner", "manager"] },
  { href: "/audit-log", label: "Audit Log", icon: IconShieldSearch, roles: ["super_admin"] },
  { href: "/niches#flagship-number", label: "Settings", icon: IconSettings, roles: ["super_admin"] },
];

const ROLE_LABELS: Record<string, string> = {
  super_admin: "Super Admin",
  owner: "Owner",
  manager: "Manager",
  cashier: "Cashier",
  kitchen: "Kitchen",
};

// Rendered INSIDE RestaurantProvider (unlike the rest of DashboardLayout) so it can read
// the current business's niche terminology/feature entitlements to drive nav labels and
// visibility -- see NavItem's terminologyKey/featureCode docs above.
function Sidebar({ role, pathname }: { role: Role; pathname: string }) {
  const { hasFeature, nicheTerminology, nicheActionType } = useCurrentRestaurant();

  const visibleItems = NAV_ITEMS.filter((item) => {
    if (item.roles && !item.roles.includes(role)) return false;
    if (item.featureCode && !hasFeature(item.featureCode)) return false;
    return true;
  });

  return (
    <nav className="flex-1 space-y-0.5 overflow-y-auto px-3 py-4">
      {visibleItems.map((item) => {
        const active = pathname === item.href.split("#")[0];
        const label =
          (item.terminologyKey && (nicheTerminology?.[item.terminologyKey] as string | undefined)) ||
          (item.actionTypeLabels && nicheActionType && item.actionTypeLabels[nicheActionType]) ||
          item.label;
        return (
          <Link
            key={item.href}
            href={item.href}
            className={`group relative flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-[13.5px] font-medium transition-colors ${
              active ? "bg-primary/10 text-primary-dark" : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
            }`}
          >
            <span
              className={`absolute inset-y-1.5 left-0 w-[3px] rounded-full bg-primary transition-opacity ${
                active ? "opacity-100" : "opacity-0"
              }`}
            />
            <span
              className={`flex h-6 w-6 items-center justify-center transition-transform ${
                active ? "" : "opacity-70 group-hover:opacity-100"
              }`}
            >
              <item.icon size={17} strokeWidth={1.6} />
            </span>
            <span className="truncate">{label}</span>
          </Link>
        );
      })}
    </nav>
  );
}

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const { user, loading, logout } = useRequireAuth();
  const pathname = usePathname();
  const router = useRouter();

  if (loading || !user) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-3 bg-white text-slate-500">
        <LogoMark size={36} className="opacity-90" />
        <span className="flex items-center gap-2 text-sm">
          <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-slate-200 border-t-primary" />
          Loading…
        </span>
      </div>
    );
  }

  const initial = user.email ? user.email[0].toUpperCase() : "?";

  return (
    <RestaurantProvider>
      <div className="flex h-screen overflow-hidden bg-slate-50/60">
        <aside className="flex h-full w-64 shrink-0 flex-col border-r border-slate-200 bg-white">
          <div className="border-b border-slate-100 px-5 py-5">
            <LogoLockup size={26} />
            <p className="mt-1 pl-[38px] text-[11px] text-slate-400">Business OS</p>
          </div>

          <Sidebar role={user.role as Role} pathname={pathname} />

          <div className="border-t border-slate-100 p-3">
            <div className="mb-1 flex items-center gap-2.5 rounded-lg px-2 py-2">
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary-dark">
                {initial}
              </div>
              <div className="min-w-0">
                <p className="truncate text-[13px] font-medium text-slate-700">{user.email}</p>
                <p className="text-[11px] text-slate-400">{ROLE_LABELS[user.role] ?? user.role}</p>
              </div>
            </div>
            <button
              onClick={async () => {
                await logout();
                router.replace("/login");
              }}
              className="w-full rounded-lg px-2.5 py-2 text-left text-[13px] font-medium text-slate-500 transition-colors hover:bg-red-50 hover:text-red-600"
            >
              Sign out
            </button>
          </div>
        </aside>
        <div className="flex flex-1 flex-col overflow-hidden">
          <TopBar />
          <main className="flex-1 overflow-y-auto p-8">
            <div className="mx-auto max-w-6xl">{children}</div>
          </main>
        </div>
      </div>
    </RestaurantProvider>
  );
}
