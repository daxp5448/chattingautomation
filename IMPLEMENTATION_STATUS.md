# Implementation Status

Snapshot as of 2026-08-11. This is a factual status check (grepped/queried against the real
codebase and the real Postgres database), not a plan — see `SUPER_ADMIN_FEATURES.md` for the
feature-by-feature catalog and the proposed Feature Package system.

## Snapshot summary

| | |
|---|---|
| Backend tests | 307 passing, 0 failing |
| Alembic migrations applied to real Postgres DB | 14, at head (`c5d6e7f8a9b0`) |
| Niche templates seeded | 12 (hotel, real_estate, restaurant, salon, automobile, clinic, education, electronics, grocery, gym, jewellers, retail) |
| Real restaurants in the database | 1 — **Prince Corner** (legacy engine, `is_demo=False`) |
| Demo restaurants provisioned | **0** — see "Demo Bot" below, this is the open item blocking your client demo |
| Frontend `tsc --noEmit` / `next build` | Clean |

## Architecture: two engines, one platform

- **Legacy engine** (`flow_engine.py`) — powers Prince Corner only. Restaurant-specific,
  predates the multi-niche pivot. Every change in this project has been scoped to never touch
  it.
- **Generic multi-niche engine** (`generic_flow_engine.py`) — powers all 12 niches, config- and
  database-driven (no code change to add a niche, menu, or flow). This is where all Phase 2
  work has landed.

Which engine a business runs on is `Restaurant.uses_generic_engine`; the frontend branches on
it in the few places behavior differs (`/home-builder`, `/live-chat`), and shows one dashboard
otherwise.

## Phase 1 — Core Platform (done)

Restaurant/branch management, menu & catalog, orders, coupons, FAQ, customers, image
pipeline, POS/KDS display devices, dashboard analytics, role-based auth, audit log, home
builder (buttons), demo bot dispatcher (code complete — not live yet, see below).

## Phase 2 — Business OS build-out (in progress, confirmed order)

| # | Item | Status |
|---|---|---|
| 1 | WhatsApp Template Manager | ✅ Done — 19 tests, migration applied |
| 2 | Broadcast Module | ✅ Done — 16 tests, migration applied |
| 3 | Drag & Drop Flow Builder | ✅ Done — 24 tests, migration applied. **Frontend not yet manually exercised in a browser** (no browser-automation tool was available in that session — `tsc`/`next build` are clean and an SSR smoke check passed, but nobody has actually dragged a node around yet) |
| 4 | AI Knowledge Base | ❌ Not started |
| 5 | Marketplace | ❌ Not started |
| 6 | Billing (Razorpay, platform-level) | ❌ Not started |
| 7 | White Label | ❌ Not started |
| 8 | Multi-language | ❌ Not started |

## Demo Bot: code-complete, not live — this is what's blocking your client demo

The Demo Bot feature itself (one WhatsApp number → industry picker → live demo of any of the
12 niches, fully isolated per niche) is **fully built and tested** —
`app/services/demo_bot_service.py`, `app/services/demo_restaurant_sync.py`, paginated
industry picker (handles >10 niches correctly, Meta's list-message row cap), dedicated tests
in `test_demo_bot.py`.

**What's actually missing is data, not code**: querying the real database directly confirms
**zero demo restaurants exist**, because the one prerequisite step has never been run — there
is no "sentinel" restaurant yet (a restaurant with `is_demo=True` and a real
`whatsapp_phone_number_id` configured).

### Exact steps to get this live for your client demo

1. **Get a WhatsApp number for the Demo Bot.** This must be a *different* number from Prince
   Corner's (a phone-number-id can only route to one restaurant) — either a second Meta test
   number (fast, fine for a demo) or your real business number if you want it to look
   permanent. `GOING_LIVE.md` in the repo root already documents this exact process end to
   end (Meta App → WhatsApp product → Phone Number ID / WABA ID / access token).
2. In the dashboard, go to **Restaurants → Add Restaurant**, check **"Demo Bot restaurant"**,
   and fill in that number's Phone Number ID + Access Token. This is a real-credentials step
   only you can do — I don't have and shouldn't be given your Meta tokens.
3. Once that restaurant exists, run:
   ```
   cd backend && python -m app.scripts.seed_demo_restaurants
   ```
   This auto-provisions all 12 niche demo restaurants behind that one number (each gets its
   own catalog + flow copied from its `NicheTemplate`, fully isolated from each other and
   from Prince Corner). **I can run this command for you the moment step 2 is done** — say
   the word once the sentinel restaurant exists.
4. Confirm the webhook is pointed at this number (same Meta dashboard steps as `GOING_LIVE.md`
   Part 2, step 8-9) and subscribed to `messages`.
5. Message "hi" to that number — you should get the industry picker.

## Known gaps worth knowing about (not hidden in the catalog doc, called out directly here)

- **Inbound "STOP" is not auto-handled anywhere in the webhook.** `marketing_opt_in` is
  respected when *sending* a broadcast, but nothing flips it off automatically when a customer
  replies STOP. Currently a manual admin action only. Flagged in the feature catalog as
  🟡 PARTIAL, repeating it here because it's a compliance-adjacent gap, not just a missing
  nice-to-have.
- **Loyalty point redemption via chat** ("REDEEM 100") exists in the legacy engine only — the
  generic multi-niche engine (all 12 niches) doesn't have an equivalent in-chat command yet.
- **Flow Builder frontend** — code-complete and passes static checks, but hasn't been clicked
  through in a real browser. Worth doing before demoing it specifically, even though the
  underlying save/load API is fully tested server-side.

## Next steps (pick what matters most to you)

1. Get the Demo Bot live on a real number (see above — mostly your action, small assist from
   me).
2. Decide the Feature Package system's open questions (see `SUPER_ADMIN_FEATURES.md` Part A)
   so it can go through the same design → review → build cycle as everything else here.
3. Continue the confirmed Phase 2/3 order (AI Knowledge Base next) whenever you're ready.
