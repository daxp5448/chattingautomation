# What's New

A plain-language changelog of everything added to this repo recently, split by where it
came from: the work done in our chat session, and a separate batch that was pushed from
somewhere else and just pulled in. Dates are approximate (repo clock reads early Sept
2026); read this alongside `git log --oneline` if you want exact commit boundaries.

---

## Part A — Built in our session (commit `6bead67`)

### 1. Rule-based conversational humanization layer

The WhatsApp bot now understands more than exact button taps, and sounds less robotic —
all without any LLM/AI API call (zero added cost, zero added latency of consequence).

- **Typo & Hinglish-tolerant free text**: typing "jwellery" or "bhai ring dikhana" now
  fuzzy-matches the right menu option, same as tapping the button would.
- **Natural commands as free text**: "back", "start again", "change quantity", "show
  more", "anything cheaper?" now work typed, not just via buttons.
- **Ambiguous input asks, never guesses**: typing "gold" when both "Gold Ring" and "Gold
  Bangles" are options asks you to confirm which one instead of picking wrong.
- **"Are you a bot?" gets an honest answer** — never pretends to be human.
- **Per-niche personality**: each of the 12 industries (restaurant, jewellers, salon,
  gym, hotel, real estate, automobile, clinic, education, electronics, grocery, retail)
  now has its own tone (e.g. jewellers = premium/elegant, restaurant = friendly/casual),
  configurable per business in **Restaurants → Settings → Conversation Style**.
- New files: `backend/app/services/conversational_intent.py`,
  `conversational_style.py`, `conversation_lexicon.py`. New `Restaurant.
  conversation_settings` / `NicheTemplate.default_personality` columns.
- **What this is NOT**: still not true natural-language understanding — genuinely novel
  phrasing outside the recognized patterns falls back to the existing "please pick one of
  the options below" prompt, which is the correct safe behavior for a deterministic bot.

### 2. Niche-aware template selection for Broadcast Campaigns

WhatsApp Message Templates (used for the existing Broadcast Campaign / bulk marketing
feature, sent outside the 24-hour chat window) can now be tagged with a **purpose**
(Product Showcase, Enquiry, Appointment, Confirmation, Reminder, Follow-up, Offer,
Booking, Order Confirmation, General).

- **Templates page** now shows a "Recommended for your business" table — which purposes
  your industry typically needs, and whether you already have an approved template for
  each.
- **Broadcast Campaign creation** now groups your approved templates under "⭐
  Recommended for your business" in the picker, ahead of everything else.
- Note: this deliberately does **not** touch the live bot conversation — WhatsApp
  Templates are plain-text-only and only usable outside the active chat session, so they
  were never a fit for the interactive button-driven flow itself.

### 3. Demo Bot / Industry Picker fixes

- Sending "hi"/"hello" now returns you to the industry picker from inside any niche demo
  (previously only the word "industries" did this).
- Fixed a bug that regressed: right after an order/enquiry finishes, the bot correctly
  still offers explicit "Continue" / "Switch Industry" buttons instead of the new "hi"
  shortcut jumping in too early.
- Fixed the "🌐 Try Another Industry" button showing up cut off as "Try Another Indust"
  in WhatsApp — it silently hit Meta's 20-character button-title limit. Shortened to "🌐
  Switch Industry".

### 4. Restaurant branding image upload

**Restaurants → Settings → Branding** now has a real file-upload button for the cover
image and logo, instead of only a raw URL field — picks a file from your computer,
uploads it, and fills in a permanent link automatically. (Previously a business's
cover_image_url had been mistakenly set to a non-image URL, which this replaces with a
correct workflow.)

---

## Part B — Pulled in from elsewhere (commit `fcbb423`)

This next batch was **not** built in our session — it was already pushed to the repo by
the time we ran `git pull`. Summarized here so you have one place to see everything new,
but verify details against that commit's own author if you have questions about intent.

### 5. Self-serve signup with email OTP verification

A stranger can now sign up without any admin involvement: `frontend/app/signup/page.tsx`
lets someone pick an industry, create an account, and verify their email with a typed
6-digit code (`backend/app/api/v1/routers/signup.py`). Their new business starts in a
**`PENDING_REVIEW`** status — the dashboard is fully usable immediately, but the WhatsApp
bot itself stays silent until a Super Admin approves it.

### 6. Demo billing / 7-day trial paywall

Every self-serve signup gets a 7-day free trial clock (`Restaurant.trial_ends_at`, set at
signup). Once it expires, a `TrialBanner` shows across the dashboard with a "Pay Now"
button opening `DemoPaywallModal`. **Explicitly a demo/mock of the billing flow** — no
real payment gateway is wired in; "paying" is one API call that just flips a flag
(`backend/app/api/v1/routers/billing.py`'s own docstring says real billing is a separate,
future build).

### 7. Oracle VM deployment docs

Two new docs: `DEPLOYMENT_ORACLE.md` (steps to put this platform on an existing Oracle
Cloud VM at `whatsapp.kelviontech.in`, replacing ngrok with a permanent domain) and
`GOING_LIVE_LOCAL_TESTING.md` (a beginner-friendly explainer of what ngrok/webhooks/Meta's
API actually do, companion to the existing `GOING_LIVE.md`). Plus `docker-compose.
oracle.yml` and an nginx config for that subdomain.

---

## Where to look next

- `AGENT_HANDOFF.md` — local dev environment setup gotchas (Python version, SQLite vs
  Postgres, seeding) from our session.
- `PROJECT_OVERVIEW.md` — a broader orientation doc (also pulled in with Part B) if you
  want the full picture of the whole platform, not just what's new.
