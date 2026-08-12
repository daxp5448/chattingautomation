// Server-side only (not NEXT_PUBLIC_*) -- the browser never talks to this URL directly.
const BACKEND_INTERNAL_URL = process.env.BACKEND_INTERNAL_URL || "http://localhost:8000";

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Proxies /api/* to the FastAPI backend so the browser only ever talks to this app's
  // own origin. This is what makes the httpOnly auth cookies (see backend
  // app/api/v1/routers/auth.py) work simply and safely: same-origin cookies with
  // SameSite=Lax need no cross-site cookie dance, work over plain http in local dev, and
  // never require a shared JWT secret on the frontend just to see if a cookie is present.
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${BACKEND_INTERNAL_URL}/api/:path*` }];
  },
};

export default nextConfig;
