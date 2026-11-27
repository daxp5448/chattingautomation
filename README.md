#  WhatsApp Restaurant Platform

A multi-tenant WhatsApp ordering platform: onboard a restaurant from the admin dashboard,
and its WhatsApp bot works automatically off that restaurant's own configuration — menu,
branches, bot copy, coupons, loyalty, and FAQs. No restaurant-specific values are
hardcoded in the backend.

**Phase 1** (core ordering loop), **Phase 2** (coupons/loyalty, Razorpay, rule-based
AI/NLU + human handover, invoicing, WebSocket live updates), and **Phase 3** (button-only
multi-branch bot entry -- see below) are all built. Still deferred: Stripe/PhonePe/UPI,
PDF/thermal printing beyond the basic invoice, the visual drag-drop flow builder, SMS,
CI/CD, and production hardening (rate limiting, RLS policies, secrets manager).

## Architecture

```
Customer → WhatsApp → Meta Cloud API → Webhook (FastAPI) → Flow Engine → PostgreSQL
                                            ↓                    ↑
                                     Razorpay / Invoice PDF   WebSocket
                                                                 ↑
                                                    Admin Dashboard (Next.js)
```

- **Backend**: FastAPI, SQLAlchemy 2.0 (async), Alembic, repository + service layers,
  JWT auth with role-based access control, Celery/Redis for background WhatsApp delivery.
- **Frontend**: Next.js (App Router) + TypeScript + Tailwind.
- **Multi-tenancy**: shared Postgres database, every tenant-scoped table carries
  `restaurant_id`; inbound WhatsApp webhooks resolve the tenant via the restaurant's stored
  `whatsapp_phone_number_id` (Meta's payload includes this in `metadata.phone_number_id`).
- **No Docker/Postgres in every dev environment**: models use a portable `GUID` column type
  (`backend/app/db/types.py`) — native `UUID` on Postgres in production, `CHAR(32)` on SQLite
  for the test suite — so `pytest` runs without Docker.
- **Timestamps are Python-side defaults**, not `server_default=func.now()` — a server-computed
  `onupdate` value needs a post-UPDATE refresh that isn't awaitable outside the async
  greenlet context and crashes response serialization. Found via a live smoke test, not
  `pytest` (which always substitutes a fake WhatsApp sender) — see `backend/app/db/base.py`.

## Quick start (Docker)

```bash
cp .env.example .env
# generate a Fernet key for FIELD_ENCRYPTION_KEY:
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# paste it into .env, then:
docker compose up --build
```

- Backend: http://localhost:8000 (docs at `/docs`)
- Frontend: http://localhost:3000
- MinIO console: http://localhost:9001 (minioadmin/minioadmin)

`docker compose up` runs `alembic upgrade head` automatically on backend startup. To seed a
demo restaurant + menu + admin logins:

```bash
docker compose exec backend python -m app.seed
```

This creates:
- Super admin: `admin@kelviontech.dev` / `ChangeMe123!`
- Demo restaurant owner: `owner@demo-restaurant.kelviontech.dev` / `ChangeMe123!`

> Email addresses under reserved TLDs (`.example`, `.test`, `.invalid`, `.localhost`,
> `.local`) are rejected by `email-validator` even though they look like valid syntax —
> use a real-looking non-reserved domain (`.dev` etc.) for any seed/test accounts.

## Local development without Docker

Backend:

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate      # Windows
pip install -r requirements.txt
pytest                       # runs against SQLite, no Postgres/MinIO needed
```

`storage_service.upload_bytes` (invoice PDFs) is mocked in tests via `conftest.py` since no
MinIO runs in the test environment — invoice attachment is best-effort in production too: if
the storage backend is unreachable, the order still completes (see `flow_engine._attach_invoice`).

Running the API against real Postgres locally requires `DATABASE_URL` pointing at a running
instance, then `alembic upgrade head` and `uvicorn app.main:app --reload`.

Frontend:

```bash
cd frontend
cp .env.local.example .env.local
npm install
npm run dev
```

## Connecting a real WhatsApp number (Meta Cloud API)

**See [GOING_LIVE.md](GOING_LIVE.md) for the full walkthrough** — what each Meta concept
(App, WABA, Phone Number ID, Access Token, Verify Token) maps to in this codebase, how a
message actually round-trips through the webhook and the flow engine, a step-by-step guide
to connecting Meta's free test number using `ngrok`, and everything needed to go from that
to a real production number (permanent tokens, business verification, the 24-hour customer
service window, deployment, rate limits).

Short version: create a Meta App with the WhatsApp product, then in the dashboard go to
**Restaurants → Settings → WhatsApp Cloud API** and paste in that restaurant's Phone Number
ID / WABA ID / Access Token — these are per-restaurant, each tenant can use a different
number. The webhook URL (`https://<your-domain>/api/v1/webhook`) and verify token
(`WHATSAPP_WEBHOOK_VERIFY_TOKEN`) are app-level, configured once in the Meta App dashboard
for the whole platform — which restaurant a message belongs to is resolved per-message via
`phone_number_id`, not the URL. `WHATSAPP_APP_SECRET` verifies inbound webhook signatures;
until it's set, signature verification is skipped so the flow can be exercised with
simulated payloads first.

## Multi-branch bot entry (button-only, no free-typing required)

A customer never has to type anything to navigate the bot — every step is Meta interactive
buttons/lists, matching the reference UX (send "hi" -> tap an option -> keep tapping through
checkout). This is fully generic: the same code drives a single-location restaurant and an
11-branch chain purely off how many branches exist in that restaurant's own data, configured
from the dashboard's **Branches** page — nothing about branch count is hardcoded.

- **1 open branch**: the customer's first "hi" is silently assigned that branch and goes
  straight to the welcome menu — zero extra taps for a single-location restaurant.
- **2+ open branches**: "hi" shows a branch picker *before* the welcome menu, since menu
  availability, "Our Location", and "Contact Restaurant" are all branch-specific. Once
  picked, the branch is remembered for the rest of that chat (including through placing
  another order) until the customer taps **Change Branch**.
- **0 open branches**: the customer gets the `restaurant_closed` message instead.

The default welcome menu ships with five working buttons (`app/services/flow_engine.py::DEFAULT_BUTTONS`),
each backed by real logic, not placeholder text:

| Button | Action key | Behavior |
| --- | --- | --- |
| Order Food | `order_food` | Category -> product -> quantity -> cart -> checkout |
| View Menu | `view_menu` | Same browsing flow as Order Food |
| Today's Special | `today_special` | Lists products marked "featured" in the Menu page |
| Our Location | `our_location` | Sends the selected branch's address (or a WhatsApp native location pin if lat/long are set) |
| Contact Restaurant | `contact_restaurant` | Sends the selected branch's phone, falling back to the restaurant's support number |

An admin can delete/reorder/relabel any of these or add a `change_branch` button (only
useful once a restaurant has more than one branch) from **Bot Builder**, or add a custom
action key that isn't in the built-in list — that one just resolves to whatever `bot_messages`
content is saved under that key, same as Phase 1/2. Onboarding a brand-new restaurant is
still just: create it (or point `.env` at a different `whatsapp_phone_number_id` +
access token), add branches/menu, and the same backend code serves it immediately.

## Bot Builder & AI/NLU

`Bot Builder` in the dashboard edits `bot_messages` (welcome text, order confirmations, etc.
— `{{variable}}` tokens are substituted at send time), `bot_buttons` (the welcome menu's
options), and **FAQ entries** (keyword-triggered answers). Until a restaurant configures
these, generic fallback copy is used (`app/services/flow_engine.py::DEFAULT_MESSAGES`) so a
freshly onboarded restaurant's bot works immediately, fully overridable from the dashboard.

Free-text messages outside an expected input step (e.g. "what's your delivery time?") are
answered by **rule-based matching only** — fuzzy matching (`rapidfuzz`) against menu item
tags/prices, then FAQ keywords (`app/services/nlu_service.py`) — deliberately **no LLM API**,
since per-message cost multiplies across every restaurant on the platform. A greeting like
"hi"/"menu" always shows the welcome menu rather than being routed through NLU. Anything
that doesn't match hands the conversation to a human: the customer gets a "connecting you"
message, the conversation appears on the **Live Chat** dashboard page with full transcript
(every inbound/outbound message is now logged — Phase 1 only tracked current state), and
staff can reply or resolve it back to the bot.

## Payment gateways

Cash on Delivery and Razorpay are both wired up, behind a `PaymentGateway` interface
(`app/services/payment/base.py`). COD is stateless and registered once via
`register_gateway`; Razorpay needs per-restaurant API credentials, so `RazorpayGateway` is
instantiated directly with a `Restaurant` rather than looked up through the global registry.
Real Razorpay credentials aren't required to exercise the flow: `RazorpayGateway.create_payment`
returns a gracefully-empty result when unconfigured, and the flow engine falls back to a
COD-style confirmation rather than failing the order. Add Stripe/PhonePe/UPI by implementing
the `PaymentGateway` interface — order creation and the WhatsApp flow don't change.

Razorpay payment confirmation arrives via `POST /api/v1/payments/razorpay/webhook`, verified
with an HMAC signature against the restaurant's `razorpay_webhook_secret`.

## Coupons & loyalty

Coupons (flat/percentage, min order, usage limits, first-order-only, auto-apply) and a
loyalty points ledger are both admin-configurable per restaurant
(`app/services/coupon_service.py`, `app/services/loyalty_service.py`). During WhatsApp
checkout, after "Checkout" the customer is asked for a coupon code, `REDEEM <points>`, or
`SKIP` (which still auto-applies the best eligible `auto_apply` coupon). Points are awarded
when an order's status transitions to `completed` (not on creation, so cancelled orders
don't earn points) — see the status-update endpoint in `app/api/v1/routers/orders.py`.

## Invoicing

A GST-style PDF invoice (`app/services/invoice_service.py`, via `reportlab` + a `qrcode`)
is generated and uploaded to S3/MinIO (`app/services/storage_service.py`) right after order
confirmation. `boto3` is synchronous, so the upload runs via `asyncio.to_thread` to avoid
blocking the event loop for every other in-flight request during the S3 call. If storage
isn't reachable, invoice attachment is skipped (logged as a warning) and the order still
completes — see `flow_engine._attach_invoice`.

## Live updates

The Orders board and Dashboard use a WebSocket (`WS /api/v1/ws/restaurants/{id}/orders`,
JWT passed as a query param since browsers can't set headers on the WS handshake) instead of
Phase 1's polling, broadcast from order creation/status changes, payment success, and
handover events. The `ConnectionManager` (`app/core/ws_manager.py`) is in-memory and
single-process — a multi-process deployment would need Redis pub/sub to fan events across
workers, not implemented yet.

## Repository layout

See the plan this was built from for the full rationale; in short:

```
backend/app/
  api/v1/routers/   FastAPI routers (one per resource + webhook + ws + payments)
  core/             settings, JWT/security, request-scoped dependencies, ws_manager
  db/               async engine/session, portable GUID type
  models/           SQLAlchemy ORM models
  schemas/          Pydantic request/response models
  repositories/      tenant-scoped CRUD per aggregate
  services/          flow_engine, whatsapp_client, order_service, template_engine,
                      coupon_service, loyalty_service, nlu_service, invoice_service,
                      storage_service, payment/ (cod, razorpay, base)
  tasks/             Celery app + background WhatsApp delivery
  tests/             pytest suite
frontend/app/        Next.js App Router pages (dashboard, restaurants, branches, menu,
                      bot-builder, coupons, orders, customers, live-chat)
```

## Verification tooling

`backend/scripts/smoke_test.py` drives a **real running `uvicorn` process** (not the pytest
ASGI test client) through the full HTTP surface: auth, restaurant/branch/menu CRUD, the
WhatsApp webhook signature verification, a complete order with a coupon applied, Razorpay's
graceful no-credentials fallback, loyalty points on completion, FAQ matching, human handover
+ staff reply + resolve, and dashboard stats. This caught two real bugs `pytest` never would
have (see the Architecture section above) — `pytest` always substitutes a fake WhatsApp
sender, so it never exercised the real send path or a real post-UPDATE serialization. Run it
against a fresh SQLite DB with `alembic upgrade head` applied, then:

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8001 &
python scripts/smoke_test.py
```

## Deferred to later phases

Stripe/PhonePe/UPI gateways, thermal printer (ESC/POS) support, the visual drag-drop flow
builder, SMS (Twilio), CI/CD, and production hardening (rate limiting, Postgres RLS
policies, a real secrets manager, Redis pub/sub fan-out for multi-process WebSockets).
