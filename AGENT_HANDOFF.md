# Agent Handoff — KelvionTech WhatsApp Ordering Platform

This document exists so another AI agent (or a human) can pick up this project cold, in this
exact local dev environment, without re-deriving everything a human already spent a session
figuring out. Read this fully before touching the codebase. It supplements — never
overrides — anything already written in `README.md`, `GOING_LIVE.md`, and inline code
comments (this codebase leans heavily on "why" comments at decision points; read those before
assuming something is a bug).

## 1. What this is

A multi-tenant SaaS platform ("KelvionTech Business OS") that lets any business run its entire
customer ordering/enquiry flow over **WhatsApp**, driven entirely from an admin dashboard — no
code changes needed to onboard a new business. One backend serves every tenant; each tenant
("restaurant" in the code/DB, regardless of actual industry) has its own WhatsApp Business
number, catalog, bot messages, and branding.

It ships with **12 pre-built niche templates** (restaurant, jewellers, salon & spa, gym &
fitness, hotel & guesthouse, real estate, automobile service, clinic & healthcare, education &
coaching, electronics & mobile store, grocery & kirana, retail & fashion), each with its own
default catalog, flow steps, and messages, provisioned from `NicheTemplate` rows.

Stack:
- **Backend**: FastAPI (async), SQLAlchemy 2.0 async ORM, Alembic migrations, Celery+Redis for
  background jobs, Postgres in production. Python 3.12 (see gotcha below — do NOT use 3.14).
- **Frontend**: Next.js (App Router) + React + Tailwind, in `frontend/`.
- **Messaging**: Meta WhatsApp Cloud API (Graph API), all outbound/inbound through
  `backend/app/services/whatsapp_client.py` and `backend/app/services/generic_flow_engine.py`.
- **Bot logic**: A generic, data-driven flow engine (`generic_flow_engine.py`) interprets each
  restaurant's `FlowDefinition` (steps/buttons/messages stored in DB, editable from the
  dashboard's Flow Builder) — no niche-specific code paths for the actual conversation logic.

## 2. Local dev environment — exact working setup

This was non-trivial to get running on Windows; follow this exactly rather than re-deriving it.

### Python version — CRITICAL gotcha
The system default was Python **3.14**, which **cannot build `rapidfuzz==3.10.0`** from source
(no prebuilt wheel, and its sdist's `pyproject.toml` fails newer `scikit-build-core`'s stricter
parsing). The working venv uses **Python 3.12** (`py -3.12 -m venv venv`, invoked from
`backend/`). The venv lives at `backend/venv`. Always confirm you're using it — a common
failure mode in this session was a stray terminal losing the `(venv)` prefix and silently
falling back to system Python 3.14, producing `ModuleNotFoundError` for packages that are very
much installed (just not on that interpreter).

```powershell
cd "D:\whatsapp ordering\backend"
py -3.12 -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Frontend deps
```powershell
cd "D:\whatsapp ordering\frontend"
npm install
```
Note: `npm install` currently warns of 3 vulnerabilities (2 high, 1 critical) in `next@14.2.15`
(known CVE) — not fixed yet, flagging for whoever picks this up next.

### `backend/.env` — created this session, does not exist in git
There is no committed `.env`. One was created for local dev with SQLite instead of
Postgres/Redis/MinIO (none of those are running locally). Current contents (secrets already
generated, safe to reuse for continued local dev — **never reuse these in production**):

```
ENVIRONMENT=development
DATABASE_URL=sqlite+aiosqlite:///./dev.db
JWT_SECRET_KEY=sumwDnsl54opdTKoSMgB4kGJJ8SV_5x60I9FaPoKOACc79wQ8LgOemdXPYuHR2z2
ACCESS_TOKEN_EXPIRE_MINUTES=480
REFRESH_TOKEN_EXPIRE_MINUTES=20160
FIELD_ENCRYPTION_KEY=1UEw4PomnvickzwzdWPPQ8xkkJnEpep_lX2TpyQLZDY=
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/1
CELERY_RESULT_BACKEND=redis://localhost:6379/2
STORAGE_BACKEND=local
LOCAL_MEDIA_DIR=media_storage
WHATSAPP_APP_SECRET=
WHATSAPP_WEBHOOK_VERIFY_TOKEN=change-me-verify-token
WHATSAPP_GRAPH_API_VERSION=v20.0
PUBLIC_MEDIA_BASE_URL=https://uncolored-helpful-carload.ngrok-free.dev/api/v1/media
PUBLIC_API_BASE_URL=https://uncolored-helpful-carload.ngrok-free.dev/api/v1
CORS_ORIGINS=["http://localhost:3000"]
FRONTEND_URL=http://localhost:3000
SMTP_HOST=
SENTRY_DSN=
```

`PUBLIC_MEDIA_BASE_URL`/`PUBLIC_API_BASE_URL` point at an **ngrok free tunnel** that changes
every time ngrok restarts — if messaging/images stop working, check first whether the ngrok
URL rotated and update both this file AND the Callback URL in the Meta App dashboard
(WhatsApp → Configuration) to match. `WHATSAPP_APP_SECRET` is empty, so inbound webhook
signature verification is skipped (logged as a loud warning) — fine for dev, must be set
before real production traffic.

### Database — SQLite, NOT via Alembic
`alembic upgrade head` **does not work against SQLite** in this repo — the migration history
contains Postgres-only `ALTER TYPE ... ADD VALUE` statements for enum columns, which SQLite has
no equivalent for. The schema was instead created directly via SQLAlchemy metadata, exactly how
the repo's own test suite (`app/tests/conftest.py`) does it. **Critical detail**: models must
actually be imported for this to work — `app/db/base.py` only defines the declarative `Base`,
it does NOT import model classes, so `Base.metadata` is empty unless something imports
`app.models` first (see `alembic/env.py`'s `from app.models import *` for the canonical
reference). A first attempt at this got skipped silently (zero tables created, no error) by
forgetting that import — resulting in a 0-byte `dev.db` and a very confusing
`no such table: restaurants` error downstream. The working version:

```python
import asyncio
from app.db.base import Base
from app.models import *  # noqa -- REQUIRED, registers every model on Base.metadata
from app.db.session import engine

async def main():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

asyncio.run(main())
```

`backend/dev.db` already exists with this schema applied and demo data seeded (see below) — no
need to redo this unless the DB file is deleted/corrupted or a new migration adds tables that
need picking up (in which case, for local SQLite dev, re-run the snippet above; it's
idempotent, `create_all` skips existing tables).

### Seeding demo data
```powershell
cd "D:\whatsapp ordering\backend"
.\venv\Scripts\Activate.ps1
python -m app.seed
```
Must be run as a **module** (`-m app.seed`), from the `backend/` directory, with the venv
active. Running `python seed.py` directly (even from `backend/app/`) breaks its
`from app.core.config import settings` absolute import — Python needs `backend/` on `sys.path`,
which only `-m` from the right cwd provides.

Seeded accounts: `admin@kelviontech.dev` / `owner@demo-restaurant.kelviontech.dev`, both
`ChangeMe123!`. Note: email-validator rejects reserved TLDs (`.example`, `.test`, etc.) — use
a real-looking non-reserved domain for any new seed/test accounts.

### Running everything
```powershell
# Backend
cd "D:\whatsapp ordering\backend"
.\venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --port 8000

# Frontend
cd "D:\whatsapp ordering\frontend"
npm run dev

# Public tunnel (only needed to receive real WhatsApp webhooks)
ngrok http 8000
```
`/health` on the backend does a real DB round-trip and returns `{"status":"ok"}` when healthy.

## 3. WhatsApp/Meta integration — current state

Real WhatsApp credentials live **per-restaurant in the database** (`whatsapp_phone_number_id`,
`whatsapp_business_account_id`, `whatsapp_access_token_encrypted`), never in `.env` —
configured via the dashboard's **Restaurants → [restaurant] → Settings → WhatsApp Cloud API**
section, which PATCHes `/restaurants/{id}`.

Currently connected: restaurant **"KelvionTech Business OS"**
(`id=95ed1473-431d-4ed5-84f0-4d1cfab5333a`) holds `phone_number_id=1277847032070891`, a real
access token, and is the one wired to the live ngrok tunnel/webhook. It's a **Meta free test
number**, and Business Verification IS already complete on this Meta Business Manager account.

**Known unresolved external limitation**: sending **interactive** message types (buttons/lists)
through this test number gets rejected by Meta with:
```
(#139000) Blocked by Integrity — "Integrity requirements not met."
```
This is confirmed to be a **Meta-side restriction specific to free test-tier numbers**, not a
bug in this codebase and not fixable by business verification or waiting (verified: business
verification was already done and the block persisted). It reproduces consistently on every
attempt to send `interactive_buttons`/`interactive_list` through this number. **The only
reliable fix documented (see `GOING_LIVE.md` Part 3, "Business verification & a real phone
number") is migrating to a real registered WhatsApp Business phone number** — free test numbers
are tier-restricted for this message type regardless of trust/verification status. Plain
`text` messages are NOT affected (confirmed working — the demo bot's industry picker, which is
plain text, works fine through this same number).

Historical note on this restaurant's `phone_number_id`: it used to be attached to a different
restaurant row, **"KelvionTech Restaurant"** (`id=b1122c30-8be8-4319-b8ca-00352cd3fbe8`), before
being reassigned to "KelvionTech Business OS". `app/repositories/restaurant_repository.py` has
an in-memory `_phone_number_id_cache` (60s TTL) mapping `phone_number_id → restaurant` — **any
time WhatsApp credentials are moved between restaurants, restart uvicorn** to avoid the webhook
routing to a stale cached restaurant for up to 60 seconds.

## 4. Demo Mode / Industry Picker (`app/services/demo_bot_service.py`)

A cross-niche demo feature: any WhatsApp number with `Restaurant.demo_mode_enabled=True` shows
first-time (and returning, per below) messagers a **plain-text numbered picker** of every
active `NicheTemplate` ("1. Automobile Service...", "2. Clinic...", etc. — currently all 12,
since `demo_enabled_niche_codes` is `None` = unrestricted) instead of that restaurant's own
flow. Replying with a number or the niche's name/code (case-insensitive) drops the customer
into that niche's own demo restaurant conversation, tracked per-phone-number in the
`demo_sessions` table (`active_restaurant_id`).

- **Currently ON** for "KelvionTech Business OS" (toggled via the dashboard's "Industry Picker
  Mode" card on the Restaurants page → `PATCH /restaurants/{id}/demo-mode`).
- To leave an active niche and return to the picker: type `industries` / `industry` /
  `other industry`, OR (**as of a change made this session**) any plain greeting ("hi",
  "hello", etc. — reuses `generic_flow_engine._looks_like_greeting`). This was a deliberate,
  explicitly-requested behavior change — **it applies globally**, including to any real
  business running Industry Picker Mode on a real customer-facing number. Before this change,
  "hi" mid-niche intentionally just restarted that same niche (the more realistic per-customer
  behavior); a code comment in `demo_bot_service.py` documents this trade-off in detail —
  read it before "fixing" it back.
- The welcome banner (logo + cover image, sent before the numbered list) comes from the
  **sentinel restaurant's own** `logo_url`/`cover_image_url` fields (i.e. whichever restaurant
  the customer is actually messaging, e.g. "KelvionTech Business OS" — not a separate global
  asset). If these are unset/invalid, the banner silently doesn't send but the text list still
  does (they're independent messages).

## 5. Restaurant branding image upload (added this session)

`logo_url`/`cover_image_url` on `Restaurant` used to be raw text URL fields in the dashboard —
easy to fat-finger (this actually happened: `cover_image_url` was found pointing at the
**webhook endpoint URL** instead of an image, presumably pasted by mistake). Added:

- **Backend**: `POST /restaurants/{restaurant_id}/upload-image` in
  `backend/app/api/v1/routers/restaurants.py` — accepts a multipart file (JPEG/PNG/WebP, 8MB
  cap), Owner/Super-Admin gated, saves via the existing `image_storage_service` (respects
  `STORAGE_BACKEND` — local disk in dev, S3/MinIO in prod), returns `{"url": "..."}` served
  through the existing generic `GET /media/{key:path}` passthrough. Mirrors the pre-existing
  `catalog-categories/upload-image` pattern exactly (same reasoning: these are plain string
  URL fields, not real `Image`-pipeline rows with a `catalog_item_id`/etc. owner).
- **Frontend**: `frontend/app/(dashboard)/restaurants/page.tsx`'s Settings → Branding section
  now uses the pre-existing `TemplateImageUpload` component (already used elsewhere for niche
  templates) instead of plain `<input>`s — gives a working "Upload" button alongside the URL
  field, auto-fills the field with the returned link + shows a preview.

## 6. Image delivery pipeline — media_id caching (pre-existing, not new)

`generic_flow_engine.py::_Engine._media_message` already implements the "upload once, reuse a
Meta-hosted reference" pattern used for every image send (catalog items, categories, flow
steps, and the demo bot welcome banner):
- On a **cache miss** (first time a given image URL is sent to a given `phone_number_id`), the
  message goes out immediately via plain `link` (so the customer waiting on that reply never
  sees added latency) — a background task (`meta_media_upload.py::schedule_background_upload`)
  simultaneously uploads the image bytes to Meta's Media API and caches the resulting
  `media_id` in the `meta_media_cache` table.
- On a **cache hit** (same URL sent again, and the cached id is within
  `MEDIA_ID_FRESHNESS_DAYS`), the message goes out via `image_by_id` — a direct Meta-hosted
  reference, immune to any issue with the source URL being reachable/fast/whatever.
- **Practical implication**: the very first send of any newly-uploaded image may still depend
  on the link being fetchable; the second send onward uses the cached media_id regardless.
  Confirmed working end-to-end this session (verified a real `media_id` got cached after one
  send of a freshly uploaded cover image).

## 7. Bot Preview — fast local iteration without WhatsApp

`frontend/app/(dashboard)/bot-preview/page.tsx` + `POST /restaurants/{id}/flow/preview`
(`backend/app/api/v1/routers/flow_preview.py`) runs the **real** `generic_flow_engine` against
a restaurant's real, live `FlowDefinition`/catalog/messages with `dry_run=True` — zero Meta API
calls, no phone number, no ngrok, no Integrity restrictions, no media upload. This is the
correct tool for iterating on a single restaurant's own conversation flow (menu, buttons,
images, order steps) quickly. **It does NOT cover** `demo_bot_service.py`'s cross-niche
industry-picker routing — that logic only runs on the real inbound-webhook path, so testing the
picker itself still requires a real WhatsApp message.

## 8. Known gotchas / footguns (don't rediscover these)

- Python 3.14 ≠ working venv. Always confirm `(venv)` is active and it's the 3.12 one.
- `alembic upgrade head` will throw `near "TYPE": syntax error` against SQLite — expected, not
  a bug. Use the `Base.metadata.create_all` snippet in §2 instead for local SQLite dev.
- `Base.metadata` is empty unless `app.models` (or something importing it, like `app.main`) has
  actually been imported in the current process — a script that only imports `app.db.base`
  will silently create zero tables.
- Run `python -m app.seed` (module form) from `backend/`, never `python seed.py` from inside
  `app/`.
- ngrok's free-tier URL rotates on restart — keep `.env`'s `PUBLIC_*_BASE_URL` and the Meta App
  dashboard's Callback URL in sync with it.
- `_phone_number_id_cache` (60s TTL) means a just-changed WhatsApp credential assignment needs
  a uvicorn restart to take effect immediately, or up to 60s to self-correct.
- "Blocked by Integrity" (#139000) on interactive sends is a Meta free-test-number restriction,
  not something fixable from this codebase — needs a real registered number (see
  `GOING_LIVE.md` Part 3).
- Local `dev.db`/`media_storage/` and anything else file-based should ideally live outside a
  cloud-synced folder (OneDrive etc.) — not actually an issue on this machine (repo is on
  `D:\`, not under OneDrive), but `app/tests/conftest.py` has a detailed comment on why this
  matters if the repo ever moves under a synced folder.

## 9. Files touched this session (all currently uncommitted — check `git status`/`git diff`)

- `backend/app/api/v1/routers/restaurants.py` — added `POST /{restaurant_id}/upload-image`.
- `frontend/app/(dashboard)/restaurants/page.tsx` — Branding section now uses
  `TemplateImageUpload` instead of plain URL `<input>`s.
- `backend/app/services/demo_bot_service.py` — greeting words now also trigger "leave niche,
  return to industry picker" (see §4).
- `backend/.env` — created fresh (not in git), SQLite-based local dev config.
- `backend/dev.db` — created and seeded with demo data.

Nothing above has been committed to git — review with `git diff` / `git status` before
committing, and note the repo also already had substantial uncommitted changes from before
this session started (see `git status` for the full list — includes webhook.py, restaurant
model/schema, whatsapp_client.py, generic_flow_engine.py, niche_seeds, and several test files).

## 10. Suggested next steps for whoever picks this up

1. Decide whether to migrate off the free test number to a real WhatsApp number (required to
   ever reliably use interactive buttons/lists — currently the single biggest blocker to a
   normal ordering flow working over real WhatsApp).
2. Review and commit (or discard) the pre-existing uncommitted changes from before this
   session, plus this session's changes, as appropriate — nothing has been committed yet.
3. `npm audit fix` (or a manual Next.js upgrade) for the flagged `next@14.2.15` vulnerabilities
   before any real deployment.
4. If picking up Postgres/Redis/MinIO for closer-to-prod local testing, `docker-compose.yml`
   already exists at the repo root (`docker compose up --build`) — the SQLite setup here was
   specifically to avoid needing Docker for quick local iteration.
