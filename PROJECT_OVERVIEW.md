# Project Overview — KelvionTech WhatsApp Business OS

A plain-language map of this repo: what it is, how the pieces fit together, and what's
still left to do. This is a **synthesis** of the other docs in this repo
(`README.md`, `AGENT_HANDOFF.md`, `GOING_LIVE.md`, `IMPLEMENTATION_STATUS.md`,
`SUPER_ADMIN_FEATURES.md`) plus a fresh look at the actual code — read this first to get
oriented, then go to the specific doc linked in each section for depth.

---

## 1. What this actually is

A **multi-tenant SaaS platform** that lets any small/medium business run its entire
customer-facing ordering/enquiry flow over **WhatsApp**, fully configured from a web
dashboard — no code changes to onboard a new business.

In the code and database every tenant is called a "restaurant" (historical — the project
started as a restaurant-ordering bot), but it now ships **12 pre-built industry templates**:
restaurant, jewellers, salon & spa, gym & fitness, hotel & guesthouse, real estate,
automobile service, clinic & healthcare, education & coaching, electronics & mobile store,
grocery & kirana, and retail & fashion. Each niche gets its own default catalog, bot flow,
and message copy out of the box, editable per business afterward.

**The pitch to a business owner:** connect your WhatsApp number, and customers can message
you, browse your menu/catalog as WhatsApp buttons and lists, place an order, pay (COD or
Razorpay), get order-status updates, redeem coupons/loyalty points — and if the bot doesn't
understand something, a human staff member sees the conversation live in the dashboard and
can take over.

---

## 2. The big picture — how a message actually flows

```
Customer's WhatsApp
      │  "hi"
      ▼
Meta Cloud API ──HMAC-signed POST──▶ FastAPI webhook (backend/app/api/v1/routers/webhook.py)
                                             │
                              looks up restaurant by phone_number_id
                              (every WhatsApp number is tied to exactly one tenant)
                                             │
                                             ▼
                                  Flow Engine reads that restaurant's own
                                  DB rows: catalog, branches, bot messages,
                                  buttons, FAQs, coupons, loyalty rules
                                             │
                              decides the reply, calls Meta's Graph API
                                             │
                                             ▼
                                  Customer's WhatsApp gets a reply
                                  (buttons/lists — never free typing required)

Meanwhile: every inbound/outbound message is logged, broadcast over a
WebSocket to the Admin Dashboard (Next.js) so staff see live orders/chats,
and background jobs (Celery) handle things like invoice generation.
```

The key architectural idea: **one backend, one webhook URL, unlimited tenants.** A new
business is just a new row in the `restaurants` table with its own WhatsApp credentials —
never a new deployment or code branch. Full mechanics (Meta App vs WABA vs Phone Number ID
vs Access Token, and the exact webhook handshake) are in **[GOING_LIVE.md](GOING_LIVE.md)
Part 2** — read that once, it explains concepts everything else depends on.

---

## 3. The two bot engines (important quirk to know about)

There are **two separate flow engines** in this codebase, not one:

| | `flow_engine.py` (legacy) | `generic_flow_engine.py` (current) |
|---|---|---|
| Powers | One specific restaurant only ("Prince Corner") | All 12 niches, every other business |
| Config source | Partly hardcoded to that restaurant's shape | Fully data-driven — reads `FlowDefinition` rows built in the visual Flow Builder |
| Status | Frozen — nothing new is built here, kept only so that one legacy tenant keeps working | Where all current and future feature work lands |

A `Restaurant.uses_generic_engine` flag decides which one a business runs on, and the
frontend branches on it in a couple of spots (`/home-builder`, `/live-chat`). **If you're
reading code to understand "how the bot works," read `generic_flow_engine.py`** — that's
the real, actively developed engine.

---

## 4. Backend tour (`backend/app/`)

FastAPI + async SQLAlchemy 2.0 + Alembic + Celery/Redis, Python 3.12 (not 3.14 — see
gotcha in §7).

```
api/v1/routers/    One FastAPI router per resource — this is the best place to start
                    reading if you want to know "what can the frontend/webhook call?"
                    Notable ones: webhook.py (Meta inbound), ws.py (live dashboard updates),
                    flow_definitions.py (Flow Builder save/load), flow_preview.py (test a
                    bot flow without WhatsApp), payments.py / generic_payments.py,
                    broadcasts.py, feature_packages.py.
core/               Settings (.env parsing), JWT auth, role-based access dependencies,
                    ws_manager.py (in-memory WebSocket connection registry).
db/                 Async engine/session setup, and a portable GUID column type so the
                    same models work on Postgres (prod) and SQLite (tests, no Docker needed).
models/             SQLAlchemy ORM tables — 30+ models. Core ones: Restaurant, Branch,
                    Product/Category (catalog), Order, Customer, Coupon, FlowDefinition,
                    NicheTemplate, BroadcastCampaign, WhatsAppTemplate, FeaturePackage.
schemas/            Pydantic request/response shapes for the API.
repositories/       Tenant-scoped CRUD per model — every query is scoped to a
                    restaurant_id so tenants can never see each other's data.
services/           The actual business logic. This is where most of the interesting code
                    lives:
                      generic_flow_engine.py   the real bot brain (see §3)
                      whatsapp_client.py        talks to Meta's Graph API (send messages)
                      nlu_service.py            rule-based free-text understanding —
                                                 fuzzy match against menu/FAQ, deliberately
                                                 NO LLM calls (cost multiplies per tenant)
                      order_service.py          order lifecycle
                      coupon_service.py / loyalty_service.py
                      invoice_service.py        PDF invoice generation (reportlab + QR)
                      payment/                  PaymentGateway interface — cod.py,
                                                 razorpay.py implemented; Stripe/PhonePe/
                                                 UPI not yet
                      broadcast_service.py      bulk WhatsApp sends to customer segments
                      demo_bot_service.py +
                      demo_restaurant_sync.py   the "industry picker" cross-niche demo (§6)
                      niche_provisioning.py     copies a NicheTemplate into a real new
                                                 tenant's catalog/flow at onboarding
                      meta_media_upload.py      caches Meta-hosted media IDs so images
                                                 don't need re-uploading on every send
tasks/              Celery app + background jobs (e.g. invoice upload doesn't block the
                    request/response cycle).
tests/              85 test files, pytest, runs against SQLite — no Docker required.
niche_seeds/        One Python file per industry (12), each defining that niche's default
                    catalog + flow + copy — this is the actual content behind "12
                    pre-built templates."
```

## 5. Frontend tour (`frontend/app/`)

Next.js App Router + TypeScript + Tailwind. All the real dashboard pages live under the
`(dashboard)` route group (24 sections): `restaurants`, `branches`, `menu`, `orders`,
`customers`, `coupons`, `faq`, `bot-builder`, `flow-builder` (visual drag-and-drop bot
editor), `bot-preview` (test a flow without needing WhatsApp at all), `broadcasts`,
`whatsapp-templates`, `live-chat` (human handover inbox), `media-library` /
`image-library`, `displays` (POS/Kitchen Display devices), `niches` (Super Admin: manage
the 12 templates), `feature-packages`, `api-endpoints`, `audit-log`, `dashboard` (stats
home). Plus `pos/[restaurantId]` (a point-of-sale view) and `login`/`setup`.

## 6. Special features worth understanding

- **Multi-branch bot entry** — a business with 2+ branches gets a branch picker before
  the menu (since hours/menu/location differ by branch); 1 branch skips straight to the
  menu; 0 open branches sends a "closed" message. Fully generic off however many branches
  exist in that tenant's own data. Details: `README.md` "Multi-branch bot entry" section.
- **Demo Bot / Industry Picker** — one special WhatsApp number where anyone can message
  in, get a numbered list of all 12 industries, pick one, and get dropped into a live demo
  of that niche's bot — used for sales demos. Code-complete and tested
  (`demo_bot_service.py`), but per `IMPLEMENTATION_STATUS.md` **not live** because the
  one-time setup step (provisioning a real "sentinel" demo restaurant + running
  `seed_demo_restaurants`) hadn't been done as of that doc's last update — worth
  re-checking current DB state rather than assuming.
- **Bot Preview** — lets you iterate on a business's actual live flow instantly in the
  dashboard, with zero WhatsApp/Meta calls (`POST /restaurants/{id}/flow/preview`,
  `dry_run=True`). The fastest way to test bot changes.
- **Rule-based "AI"** — free text that doesn't match an expected step is handled by fuzzy
  matching + FAQ keywords, not an LLM. This is a deliberate cost decision, not a
  limitation someone forgot to fix — read `README.md`'s "Bot Builder & AI/NLU" section
  before "fixing" it by wiring in a model.
- **Feature Packages** — a proposed (see `SUPER_ADMIN_FEATURES.md` Part A) but partially
  scaffolded (`models/feature_package.py`, `feature_packages.py` router,
  `frontend/.../feature-packages` page exist) system for Super Admin to bundle features
  into pricing tiers per business. Worth checking current build-out state against that
  doc's "Open decisions" before continuing it.

---

## 7. Running it locally

Two documented paths:

1. **Docker** (`README.md` Quick Start) — `docker compose up --build`, seeds via
   `python -m app.seed`. Simplest if you just want it running.
2. **No Docker, SQLite** (`AGENT_HANDOFF.md` §2) — used for fast local iteration; has
   several sharp edges already debugged and written down there:
   - Must use **Python 3.12**, not the system's 3.14 (`rapidfuzz` fails to build on 3.14).
   - `alembic upgrade head` **does not work on SQLite** (Postgres-only enum migrations) —
     use the `Base.metadata.create_all` snippet in that doc instead, and remember
     `app.models` must actually be imported first or zero tables get created silently.
   - Seed with `python -m app.seed` as a **module**, from `backend/`, not `python seed.py`.
   - `email-validator` rejects reserved TLDs (`.example`, `.test`) for seed accounts.

For a real Postgres + real WhatsApp number, see **`GOING_LIVE.md`** end to end — it also
covers going from a free Meta test number to production (permanent tokens, business
verification, deployment, backups, a go-live checklist).

---

## 8. Current state — what's built vs. not

(Cross-check dates: `IMPLEMENTATION_STATUS.md` snapshot was **2026-08-11**; today is
2026-09-03, so treat exact numbers as approximate and re-verify anything decision-critical,
e.g. `pytest -q` for current test count, `git log` for what's shipped since.)

**Solid and done:** core ordering loop, multi-branch bot entry, coupons + loyalty, Razorpay
+ COD payments, WhatsApp Template Manager, Broadcast module, visual Flow Builder, invoicing,
live WebSocket dashboard updates, human handover / Live Chat, audit log, role-based access,
POS/KDS devices, all 12 niche templates seeded.

**Partial / known gaps** (see `SUPER_ADMIN_FEATURES.md` Part B for the full 70+ row
catalog with status tags):
- Inbound "STOP" isn't auto-handled — opt-out compliance is a manual admin action only.
- Loyalty point redemption via chat ("REDEEM 100") only works on the legacy engine, not
  the generic multi-niche one.
- Flow Builder's frontend passed static checks but (as of that doc) hadn't been
  manually clicked through in a browser yet.
- Demo Bot is code-complete but not provisioned live (see §6 above — re-verify).
- Delivery charge is flat-fee only; no distance/zone-based calculation.

**Not started (confirmed roadmap):** AI Knowledge Base (real LLM-backed understanding),
Marketplace, platform-level Billing, White Label, Multi-language. Also deferred:
Stripe/PhonePe/UPI gateways, thermal/ESC-POS printing, SMS, CI/CD, and production
hardening (rate limiting, Postgres RLS, a real secrets manager, Redis pub/sub so
WebSockets work across multiple backend processes instead of just one).

**Also flagged:** `next@14.2.15` has known CVEs per `npm audit` (2 high, 1 critical) — not
yet patched as of `AGENT_HANDOFF.md`.

---

## 9. Suggested reading order for someone new

1. This file, for orientation.
2. `README.md` — architecture, quick start, feature summaries with file references.
3. `GOING_LIVE.md` Part 2 — the Meta/WhatsApp concepts everything else assumes you know.
4. `IMPLEMENTATION_STATUS.md` + `SUPER_ADMIN_FEATURES.md` — what's actually done vs. not,
   re-verify anything you're about to build on top of.
5. `AGENT_HANDOFF.md` — only if you're setting up local dev and hit an environment issue;
   it's a debugging log of gotchas, most of which are Windows/SQLite-specific.
6. Then into code: `backend/app/services/generic_flow_engine.py` is the single most
   important file to actually read the real bot logic.

## 10. Suggested next steps

Pick based on what you're trying to do:

- **Want to see it working end-to-end?** Get a real or test WhatsApp number connected
  (`GOING_LIVE.md` Part 2, ~15 minutes with `ngrok`) and message it.
- **Want to keep building features?** Re-run the status checks in §8 against current code
  (they may have moved since the last snapshot), then continue the confirmed Phase 2/3
  order noted in `IMPLEMENTATION_STATUS.md` — AI Knowledge Base is next in line.
- **Want to fix known gaps first?** The STOP/opt-out compliance gap and the
  next@14.2.15 CVEs are both small, contained, and worth doing before wider production use.
- **Want to productionize?** Work through `GOING_LIVE.md` Part 3's go-live checklist —
  permanent access token, business verification, real deploy target, backups, rate limits.
