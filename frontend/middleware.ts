import { NextRequest, NextResponse } from "next/server";

// Server-side gate for the admin dashboard: without this, an unauthenticated visitor's
// browser still downloads and runs the dashboard's JS before the client-side
// useRequireAuth() redirect fires (see lib/auth.tsx). This runs first, before any of
// that page code executes.
//
// This only checks that a session cookie is *present*, not that its signature/expiry are
// valid -- real authorization still happens on every API call via the backend (which does
// verify the JWT properly, see app/core/deps.py). Doing full signature verification here
// would mean duplicating the JWT secret onto the frontend deployment and keeping the two
// perfectly in sync, which is its own operational footgun for comparatively little extra
// safety: a forged-but-present cookie would still be rejected by every API call the page
// then makes, it would just get a logged-in-looking shell first. Presence-checking is the
// right amount of defense-in-depth for what this layer is actually for.
const PROTECTED_PATHS = [
  "/dashboard",
  "/restaurants",
  "/branches",
  "/menu",
  "/bot-builder",
  "/coupons",
  "/orders",
  "/customers",
  "/live-chat",
];

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const isProtected = PROTECTED_PATHS.some((path) => pathname === path || pathname.startsWith(`${path}/`));
  if (!isProtected) return NextResponse.next();

  const hasSession = request.cookies.has("access_token");
  if (!hasSession) {
    const loginUrl = new URL("/login", request.url);
    loginUrl.searchParams.set("from", pathname);
    return NextResponse.redirect(loginUrl);
  }
  return NextResponse.next();
}

export const config = {
  matcher: [
    "/dashboard/:path*",
    "/restaurants/:path*",
    "/branches/:path*",
    "/menu/:path*",
    "/bot-builder/:path*",
    "/coupons/:path*",
    "/orders/:path*",
    "/customers/:path*",
    "/live-chat/:path*",
  ],
};
