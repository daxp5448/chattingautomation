# Testing With a Real WhatsApp Number — ngrok, Webhooks, and Meta's API Explained

You've tested everything with simulated requests (curl, the Bot Preview screen). This doc
is for the next step: sending a real "hi" from your own phone and watching your real local
server answer it. It explains every piece involved and ends with the exact steps to do it.

This is a companion to **[GOING_LIVE.md](GOING_LIVE.md)**, which already covers this same
setup plus the full path to production later. This file exists because you specifically
asked "what is ngrok / why do I need it / what are the alternatives" — a deeper answer to
one part of that doc, written for someone doing this for the first time.

---

## 1. Why any of this is needed at all

WhatsApp doesn't let your business send messages by connecting directly to a customer's
phone. Every message — in both directions — goes through **Meta's servers** (the company
that owns WhatsApp). That's the whole reason the pieces below exist:

```
Customer's phone  <-->  Meta's WhatsApp servers  <-->  Your backend
```

Meta's servers are the only thing a customer's WhatsApp app ever talks to. Your backend
never receives a message directly from a phone — it receives it from Meta, after Meta
receives it from the phone. Same going out: your backend never sends straight to a phone,
it asks Meta's API to deliver it.

That single fact is why you need **two separate things**, covered next.

---

## 2. The Meta Cloud API — why you need it

The **Meta Cloud API** (also called the **WhatsApp Business Platform** or **Graph API**) is
Meta's programmatic interface for sending/receiving WhatsApp messages as a business. You
can't just "connect" to WhatsApp the way you'd connect to a chat protocol — Meta requires
every business to go through this API, authenticated with credentials tied to a specific
phone number.

What it gives you, concretely (all already wired into this codebase):
- **Outbound**: your backend calls `POST https://graph.facebook.com/.../messages` with an
  access token to send a message — see `backend/app/services/whatsapp_client.py`.
- **Inbound**: Meta calls **your** server whenever a customer messages your number — this
  is the "webhook" part, covered next.

There is no working alternative to this for real WhatsApp — it's not this codebase's
choice, it's a hard requirement from Meta for any business account. (If you ever wanted to
skip WhatsApp entirely and simulate a different channel — SMS, a web chat widget — that
would be a different, unbuilt feature, not a substitute for this.)

---

## 3. The webhook — why Meta needs to reach *you*

A **webhook** is just "a URL you give another service, so it can call you when something
happens" — the mirror image of you calling an API. You call Meta to *send*; Meta calls
**your webhook URL** to hand you an *inbound* message.

In this codebase, that URL is:
```
POST /api/v1/webhook
```
(`backend/app/api/v1/routers/webhook.py`) — this is the single entry point every inbound
WhatsApp message arrives through, for every business on the platform. It looks up which
restaurant the message belongs to (via `phone_number_id` in the payload), then hands it to
the flow engine, which decides the reply and sends it back out through the Cloud API.

**The problem**: Meta's servers are out on the public internet. Your laptop, running
`uvicorn` on `localhost:8000`, is not reachable from the public internet — your home/office
router blocks unsolicited inbound connections by default (this is normal, correct, and not
something you'd usually want to change). Meta literally cannot reach `http://localhost:8000`
no matter how correct your code is, because "localhost" means "this exact machine" — Meta's
servers have no way to resolve that to *your* machine from the outside.

This is the entire reason a tunnel tool is needed for local testing.

---

## 4. ngrok — what it actually does

**ngrok** is a tunnel: it gives your local server a real public HTTPS address (like
`https://abc123.ngrok-free.dev`) that forwards every request straight through to
`localhost:8000` on your machine. You run one command:

```bash
ngrok http 8000
```

and it prints a public URL. Anything sent to that public URL instantly appears on your
local server — no port forwarding, no firewall changes, no router configuration. That's the
whole trick: instead of opening your network to the internet, you open one outbound
connection *from* your machine *to* ngrok's servers, and ngrok relays inbound traffic back
through that same connection. Nobody can reach your laptop directly; they reach ngrok, and
ngrok reaches you.

You give that public URL to Meta as your webhook Callback URL. Now Meta can deliver inbound
messages to your local server exactly as if it were deployed.

**Meta specifically requires HTTPS** for the Callback URL (not plain HTTP) — ngrok's tunnel
already terminates HTTPS for you automatically, which is a big part of why it's the
easiest option for this.

### The free-tier catch (already documented in this repo)

`AGENT_HANDOFF.md` flags this from a previous session: **ngrok's free-tier URL changes
every time you restart it.** Each new `ngrok http 8000` gives you a *different* random
subdomain. That means every restart requires:
1. Updating `PUBLIC_MEDIA_BASE_URL` / `PUBLIC_API_BASE_URL` in `backend/.env`
2. Updating the Callback URL in the Meta App dashboard

Forgetting step 2 is the single most common "why isn't my bot replying" cause during local
testing — the webhook is pointed at a URL that no longer exists. A paid ngrok plan gets you
a fixed subdomain that never changes, which removes this entirely if you're doing this
often.

---

## 5. Other options besides ngrok

You don't have to use ngrok — anything that gives your local server a public HTTPS URL
works. Here's how the real alternatives compare:

| Tool | Free tier | Fixed URL on free tier? | Notes |
|---|---|---|---|
| **ngrok** | Yes | No (rotates on restart) | Easiest to set up, most widely documented, what this repo's docs already assume |
| **Cloudflare Tunnel** (`cloudflared`) | Yes | Yes, if you own a domain | No rotating-URL problem at all if you point a real domain at it — but needs a domain and slightly more setup |
| **localtunnel** | Yes | No | Similar to ngrok, less reliable/maintained |
| **VS Code / GitHub port forwarding** | Yes (with a GitHub account) | Semi-stable | Convenient if you're already in VS Code, less standard for this use case |
| **Skip tunneling — deploy for real** | N/A | Yes, always | See §7 below — the actual answer once you're past "just testing," not a local-testing option |

**Recommendation for right now**: stick with ngrok. It's what the rest of this repo's docs
(`GOING_LIVE.md`) already assume, it needs zero account/domain setup, and the rotating-URL
annoyance is a two-minute fix each time, not a blocker. Switch to Cloudflare Tunnel later
only if you're testing daily and the URL-rotation dance gets old.

---

## 6. The other pieces you'll configure (quick reference)

You've likely seen these terms in `GOING_LIVE.md` already — a short recap of what each one
*is*, since the question here was about understanding, not just steps:

| Term | What it is | Where it lives here |
|---|---|---|
| **Meta App** | A container you register once in Meta's developer portal | Nothing to store — it's Meta-side |
| **App Secret** | Proves an inbound webhook call genuinely came from Meta (HMAC signature check) | `WHATSAPP_APP_SECRET` in `backend/.env` |
| **Verify Token** | A password *you* pick, used once so Meta can confirm the Callback URL is really yours | `WHATSAPP_WEBHOOK_VERIFY_TOKEN` in `backend/.env` |
| **Phone Number ID** | Meta's internal ID for one WhatsApp number (not the phone number itself) — this is how an inbound message gets routed to the right business in a multi-tenant platform | Stored per-restaurant, set from the dashboard (Restaurants → Settings → WhatsApp Cloud API) |
| **Access Token** | Bearer credential used to call the Graph API and send messages | Stored per-restaurant, same settings screen |

One important detail specific to this codebase: **`WHATSAPP_APP_SECRET` is currently
blank** in your local `.env`. `webhook.py` (lines 40-53) checks for this and, because
`ENVIRONMENT=development`, logs a loud warning and accepts the webhook **unsigned** rather
than rejecting it — this is what lets you test with `curl` today without a real Meta
App Secret. The moment `ENVIRONMENT` is anything other than `development`, an unsigned
webhook is rejected outright (fail-closed) — so this convenience only exists for local dev,
by design, not a gap that needs fixing before you go live for real testing with Meta.

---

## 7. Do you need ngrok forever?

No — ngrok (or any tunnel) is **only for local development**, i.e. running the backend on
your own laptop. Once the backend is deployed somewhere with a real public URL (a VPS,
Render, Railway, Fly.io — anything with HTTPS), that URL itself becomes the Callback URL
and no tunnel is needed at all — Meta reaches your server directly, the same way it reaches
ngrok's forwarding address today. `GOING_LIVE.md` Part 3 covers that full jump; this doc is
specifically about the "still on my laptop" phase.

---

## 8. Step-by-step: connect a real WhatsApp number right now

This gets a real message from your own phone flowing through your real local server, using
Meta's free test number (no business verification needed for this step).

### One-time Meta setup (~10 minutes)
1. Go to [developers.facebook.com](https://developers.facebook.com), create a developer
   account if you don't have one.
2. **Create an App** → type **Business** → any name.
3. In the App dashboard: **Add Product** → **WhatsApp** → **Set up**.
4. Meta gives you, on the same screen:
   - A **Phone Number ID**
   - A **WhatsApp Business Account ID**
   - A **temporary Access Token** (valid ~24h — fine for this)
5. Under **WhatsApp → API Setup**, add your own phone number as a recipient and verify it
   with the OTP Meta texts you (free-tier numbers can only message pre-approved recipients).
6. Under **App Settings → Basic**, copy the **App Secret** — you'll paste it in below.

### Start your local stack
```powershell
# Terminal 1 — backend
cd backend
.\venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --port 8000

# Terminal 2 — frontend
cd frontend
npm run dev

# Terminal 3 — the tunnel
ngrok http 8000
```
Copy the `https://xxxx.ngrok-free.dev` URL ngrok prints.

### Wire the tunnel into your app
Edit `backend/.env`:
```
WHATSAPP_APP_SECRET=<paste the App Secret from step 6>
PUBLIC_MEDIA_BASE_URL=https://xxxx.ngrok-free.dev/api/v1/media
PUBLIC_API_BASE_URL=https://xxxx.ngrok-free.dev/api/v1
```
Restart the backend (Terminal 1) so it picks up the new `.env` values — this file is only
read at startup.

### Wire your app into Meta
Back in the Meta App dashboard, **WhatsApp → Configuration**:
- **Callback URL**: `https://xxxx.ngrok-free.dev/api/v1/webhook`
- **Verify Token**: the exact value of `WHATSAPP_WEBHOOK_VERIFY_TOKEN` from `backend/.env`
  (`change-me-verify-token` if you haven't changed it — fine for testing, change it before
  anything resembling production)
- Click **Verify and Save** — this triggers the handshake `webhook.py` already handles
  (`GET /api/v1/webhook` with `hub.mode`/`hub.verify_token`/`hub.challenge`).
- Under **Webhook fields**, click **Subscribe** next to `messages`. Skipping this is the
  second most common "nothing happens" cause — without it Meta never forwards anything.

### Connect a business to this number
In your dashboard (`http://localhost:3000`), either:
- **Use an existing business** (from all the signup/billing testing) — go to
  **Restaurants → [pick one] → Settings → WhatsApp Cloud API**, paste in the Phone Number
  ID / WABA ID / Access Token from Meta, save. If it's still `pending_review`, log in as
  the super admin and approve it first (or it'll get the "still being set up" auto-reply
  instead of the real bot — see the self-serve signup work).
- **Or sign up a brand-new one** through `/signup` for a clean end-to-end test.

### Send the real message
From your own phone, message the Meta test number: **"hi"**.

You should get the bot's welcome menu within a couple of seconds. If you don't, check:

| Symptom | Likely cause |
|---|---|
| Nothing at all happens | Webhook fields → `messages` not subscribed, or the ngrok URL rotated since you last set the Callback URL |
| Meta's "Verify and Save" fails | `WHATSAPP_WEBHOOK_VERIFY_TOKEN` mismatch, or backend wasn't restarted after editing `.env` |
| Backend logs `unknown phone_number_id` | The Phone Number ID pasted into the dashboard doesn't match what Meta's sending |
| Interactive buttons/lists silently fail (`#139000 Blocked by Integrity`) | A known Meta restriction on some free test numbers — plain text still works; see `AGENT_HANDOFF.md` §3 |

`GOING_LIVE.md`'s own Troubleshooting table has more of these if you hit something not
listed here.

---

## 9. What's genuinely different about "real" vs. everything you tested before

Nothing about your backend code changes for this. Every test you already ran (signup, bot
preview, billing) hit the exact same `process_inbound_message`/`process_generic_inbound_message`
logic a real WhatsApp message hits — Bot Preview *is* that same engine with `dry_run=True`
and no Meta involved. What's new here is purely the delivery path: a real phone, through
real Meta infrastructure, through a real tunnel, into the same code you've already verified
works.
