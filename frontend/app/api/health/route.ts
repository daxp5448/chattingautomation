import { NextResponse } from "next/server";

// Plain liveness check for orchestration (Docker HEALTHCHECK, uptime monitoring) --
// deliberately doesn't proxy through to the backend's own /health: this route answers
// "is the Next.js server itself up and serving," a different and more basic question
// than "is the whole stack healthy." A backend outage shouldn't make Docker restart an
// otherwise-fine frontend container.
export async function GET() {
  return NextResponse.json({ status: "ok" });
}
