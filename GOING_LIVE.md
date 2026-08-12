# Going Live: Local Postgres → Real WhatsApp Number → Production

This is a step-by-step walkthrough for three things:

1. Running the platform locally against your real Postgres database (already done for you — see [Part 1](#part-1-local-postgres-already-connected)).
2. Connecting a real WhatsApp number through Meta's Cloud API so messages actually flow (Part 2 — the "how it works" explanation you asked for).
3. Taking the whole thing from a personal test number to a production-ready public deployment (Part 3).

Read Part 2 even if you only want local testing right now — it explains the concepts (App vs. WABA vs. phone number vs. tokens) that everything else depends on.

---

## Part 1: Local Postgres (already connected)

`backend/.env` now points at your local database:

```
DATABASE_URL=postgresql+asyncpg://postgres:<your-postgres-password>@127.0.0.1:5432/whatsapp
```

What was done:
- Verified Postgres is reachable at `127.0.0.1:5432` and the `whatsapp` database exists.
- Generated fresh secrets for this environment (`JWT_SECRET_KEY`, `FIELD_ENCRYPTION_KEY`, `WHATSAPP_WEBHOOK_VERIFY_TOKEN`) and wrote them into `backend/.env`. `FIELD_ENCRYPTION_KEY` encrypts WhatsApp/Razorpay secrets at rest in the `restaurants` table — **do not change it after you've saved real credentials**, or they become undecryptable.
- Ran `alembic upgrade head` against it — all 21 tables were created.
- Ran the full smoke test suite against it end-to-end (auth, orders, coupons, loyalty, multi-branch bot flow, handover) to confirm the real Postgres path works, not just SQLite — then truncated the test data it created, so the database is empty and ready for your real restaurant.

`backend/.env` is already in `.gitignore` — it will never get committed if you put this under git later.

### Running it yourself

```bash
cd backend
.venv\Scripts\activate                          # Windows
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

```bash
cd frontend
# create frontend/.env.local with: NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/api/v1
npm run dev
```

Then open `http://localhost:3000`, register a `super_admin` via `POST /api/v1/auth/register` (or use the login page once you have an account), and create your restaurant. Redis/Celery/MinIO are **not required** to run locally — background WhatsApp delivery via Celery isn't wired into the live webhook path yet (the webhook calls the flow engine directly), and invoice PDF upload just degrades gracefully with a warning if MinIO isn't running.

---

## Part 2: How this connects to WhatsApp (Meta Cloud API)

### The moving pieces, and how they map to this codebase

| Meta concept | What it is | Where it lives in this app |
| --- | --- | --- |
| **Meta App** | A container registered in Meta's developer portal. Has one **App Secret**. | `WHATSAPP_APP_SECRET` in `backend/.env` — used to verify every inbound webhook's signature. |
| **WhatsApp Business Account (WABA)** | The business entity that owns phone numbers. | `whatsapp_business_account_id` on the restaurant (Restaurants → Settings). |
| **Phone Number ID** | Meta's internal ID for a specific WhatsApp number under a WABA (not the phone number itself). | `whatsapp_phone_number_id` on the restaurant. **This is how an inbound message gets routed to the right restaurant** — every webhook payload includes it in `metadata.phone_number_id`, and `backend/app/api/v1/routers/webhook.py` looks up the restaurant by it. |
| **Access Token** | A bearer token used to call the Graph API (send messages) on behalf of a phone number. | `whatsapp_access_token` on the restaurant — stored encrypted (`whatsapp_access_token_encrypted`) using `FIELD_ENCRYPTION_KEY`. |
| **Webhook Verify Token** | A shared secret *you* pick, used once during the initial handshake so Meta can confirm the URL is yours. | `WHATSAPP_WEBHOOK_VERIFY_TOKEN` in `backend/.env` — must match what you type into the Meta App dashboard. |
| **Webhook Callback URL** | The single HTTPS URL Meta POSTs every inbound message to. | `https://<your-domain>/api/v1/webhook` — **one URL for the whole app**, shared by every restaurant/phone number you onboard. Which restaurant a message belongs to is resolved per-message via Phone Number ID, not via the URL. |

This is why onboarding a new restaurant never needs a code change or a new webhook: you register one Meta App, subscribe one webhook URL, and every restaurant you create in the dashboard just gets its own Phone Number ID + Access Token typed into its Settings page.

### The message round-trip

```
Customer's WhatsApp
      │  sends "hi"
      ▼
Meta Cloud API  ──POST /api/v1/webhook (HMAC-signed with App Secret)──▶  FastAPI webhook router
                                                                              │
                                          looks up restaurant by phone_number_id
                                                                              │
                                                                              ▼
                                                                   Flow Engine (per-restaurant
                                                                   bot_messages/bot_buttons/menu/
                                                                   branches from the database)
                                                                              │
                                          decides the reply, calls Graph API to send it
                                                                              │
                                                                              ▼
                                                        POST https://graph.facebook.com/.../messages
                                                          (Authorization: Bearer <access_token>)
                                                                              │
                                                                              ▼
                                                                    Customer's WhatsApp
```

Two different secrets do two different jobs here, easy to mix up:
- **App Secret** verifies that an *inbound* webhook POST genuinely came from Meta (signature check).
- **Access Token** authorizes *outbound* sends to the Graph API.

### Step-by-step: connect a real (test) WhatsApp number

This gets you messaging with your own phone within minutes, using Meta's free test number — no business verification needed yet.

1. **Create a Meta Developer account** at [developers.facebook.com](https://developers.facebook.com) if you don't have one.
2. **Create an App** → type **Business**. Give it any name.
3. In the App dashboard, **Add Product** → **WhatsApp** → **Set up**.
4. Meta gives you a **free test phone number** automatically, plus:
   - A **Phone Number ID** (copy it)
   - A **WhatsApp Business Account ID** (copy it)
   - A **temporary access token** (valid ~24 hours — fine for testing, see Part 3 for a permanent one)
5. Under **WhatsApp → API Setup**, add your own personal phone number as a "recipient" (the free tier only lets pre-approved numbers receive messages) and verify it with the OTP Meta sends.
6. **Expose your local server publicly** so Meta can reach it (it can't call `localhost`). Easiest tool: [ngrok](https://ngrok.com).
   ```bash
   ngrok http 8000
   ```
   Copy the `https://xxxx.ngrok-free.app` URL it prints.
7. In the Meta App dashboard, go to **App Settings → Basic**, copy the **App Secret**, and put it in `backend/.env`:
   ```
   WHATSAPP_APP_SECRET=<paste it here>
   ```
   Restart the backend after editing `.env` (it's read once at startup).
8. Back in **WhatsApp → Configuration**, set:
   - **Callback URL**: `https://xxxx.ngrok-free.app/api/v1/webhook`
   - **Verify Token**: the value of `WHATSAPP_WEBHOOK_VERIFY_TOKEN` from `backend/.env`
   - Click **Verify and Save** — Meta calls `GET /api/v1/webhook` with that token; the backend already handles this handshake in `webhook.py`.
9. Under **Webhook fields**, click **Subscribe** next to `messages`. Without this, Meta never forwards inbound messages to you.
10. In your dashboard (`http://localhost:3000`), go to **Restaurants → (select your restaurant) → Settings**, and fill in the new **WhatsApp Cloud API** section with the Phone Number ID, WABA ID, and Access Token from step 4. Save.
11. From your own phone, send **"hi"** to the Meta test number. You should get the bot's welcome menu (or the branch picker first, if you've added more than one branch) within a couple of seconds.

If nothing arrives, see [Troubleshooting](#troubleshooting) below.

---

## Part 3: Taking it to production

The test setup above has real limits: the access token expires in ~24 hours, only pre-approved recipient numbers can message you, and `ngrok`'s URL changes every time you restart it. Going live means removing each of those.

### 1. Get a permanent access token

Temporary tokens are for prototyping only. For a real deployment:
1. In [Meta Business Settings](https://business.facebook.com/settings), create a **System User** (Business Admin role) under your Business Account.
2. Assign it the WhatsApp Business Account with **Manage** permission.
3. Generate a token for that System User with the `whatsapp_business_messaging` and `whatsapp_business_management` permissions, with **no expiration**.
4. Use this token as the restaurant's Access Token instead of the temporary one — same field, same dashboard.

### 2. Business verification & a real phone number

- Complete **Meta Business Verification** (legal business name, address, documents) in Business Settings — required before you can message non-test recipients or go past a handful of conversations/day.
- Add your real business phone number under **WhatsApp Manager** (it must not already be active on the regular WhatsApp app/Business App — Meta will walk you through porting it in or verifying it by SMS/call).
- Set your **display name** (e.g. your restaurant's brand name) — this goes through Meta's name-approval review, which can take a day or two.

### 3. Understand the 24-hour customer service window

This directly affects bot behavior, so it's worth internalizing:
- Once a customer messages you, you can send **any free-form message** (exactly what this bot does) for **24 hours** after their last message.
- After 24 hours of silence, you can *only* send a pre-approved **Message Template** (for things like "your order is ready") until they message you again.
- This bot's entire flow (menu, cart, confirmations, handover replies) happens inside that 24-hour window, since it's always a reply to something the customer just sent — so no extra work is needed for the ordering flow itself. If you later want proactive re-engagement (e.g. "come back, 20% off today") outside that window, that requires creating and getting Meta to approve a Message Template — not built yet, listed in the README's deferred list.

### 4. Deploy the backend somewhere public with HTTPS

Meta requires a public HTTPS URL — `ngrok` is fine for testing but not for production (it's not durable, and free URLs rotate). Pick one:
- **Your own VPS**: the repo already has `docker-compose.yml`. Point a domain at the VPS, put a reverse proxy in front (Caddy is easiest — automatic HTTPS via Let's Encrypt with zero config), and run `docker compose up --build -d`.
- **A managed platform** (Render, Railway, Fly.io, etc.): point it at this repo, set the same environment variables as `backend/.env` (but with your production `DATABASE_URL`, a freshly generated `FIELD_ENCRYPTION_KEY`/`JWT_SECRET_KEY`, and your real `WHATSAPP_APP_SECRET`), and let the platform issue HTTPS for you.

Either way, once it's live at `https://your-domain.com`, go back to the Meta App dashboard and update the **Callback URL** to `https://your-domain.com/api/v1/webhook` (same verify token as before). Everything else — restaurant records, credentials, bot config — carries over unchanged since it's all just database rows.

### 5. Rate limits and message quality

Meta throttles how many *unique customers* you can message per 24 hours, starting at a low tier (currently 250/day for new numbers) and increasing automatically based on your message quality rating (block/report rate, response rate). Nothing to configure — just be aware the first few weeks on a new number are more limited than they'll become.

### 6. Backups

`backend/scripts/backup_db.sh` dumps the whole Postgres database (every order, payment record, and
customer's data — the one copy that exists) to a timestamped, gzip-compressed file. **The script
existing in the repo does not protect anything by itself** — it only helps once it's actually
running on a schedule on the real server. Two ways to do that on the VPS deployment described above:

- **cron** (simplest): `crontab -e` on the VPS, add a daily line —
  ```
  0 3 * * * cd /path/to/whatsapp && POSTGRES_PASSWORD=$(grep ^POSTGRES_PASSWORD .env | cut -d= -f2) ./backend/scripts/backup_db.sh /var/backups/kelviontech >> /var/log/kelviontech-backup.log 2>&1
  ```
- **systemd timer** (if you'd rather not use cron): a `.service` unit running the same command plus
  a paired `.timer` unit with `OnCalendar=daily`.

Either way, **copy the backup files off the VPS** to somewhere else (S3/another provider's object
storage, a second machine) — a backup that lives on the same disk as the database it's backing up
doesn't survive that disk failing. Restoring: `gunzip -c backup_file.sql.gz | docker compose exec -T postgres psql -U postgres -d kelviontech` against an empty database. **Actually run a test restore once** before you need it for real — a backup strategy nobody has ever restored from is a guess, not a plan.

If you'd rather not manage this yourself, a managed Postgres provider (RDS, Supabase, Neon, Render
Postgres, etc.) typically includes automated backups out of the box — swap `DATABASE_URL` to point
at it and skip this section entirely.

### 7. Go-live checklist

- [ ] System User permanent access token generated and saved on the restaurant (not the 24h temporary one)
- [ ] Business verified in Meta Business Settings
- [ ] Real phone number added and verified under WhatsApp Manager
- [ ] Display name approved
- [ ] Backend deployed with a stable HTTPS URL, `WHATSAPP_APP_SECRET` set (signature verification enforced, not skipped)
- [ ] Meta App's Callback URL points at the production URL, `messages` field still subscribed
- [ ] `backend/.env` (or your platform's env vars) uses production `DATABASE_URL`, and freshly generated `JWT_SECRET_KEY`/`FIELD_ENCRYPTION_KEY` — never reuse local dev secrets in production
- [ ] `ENVIRONMENT=production` set (disables `/docs`, adds the HSTS header, enables `Secure` cookies)
- [ ] Database backups scheduled (see section 6 above) and a test restore has actually been run once
- [ ] `celery-beat` running alongside `celery-worker` (see `docker-compose.yml`) so the stuck-payment reconciliation job actually fires
- [ ] Sent a real end-to-end test message from a non-test phone number

---

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Meta's "Verify and Save" fails on the callback URL | `WHATSAPP_WEBHOOK_VERIFY_TOKEN` in `.env` doesn't match what you typed into Meta, or the backend wasn't restarted after editing `.env` | Confirm they match exactly; restart `uvicorn` |
| Webhook returns 401 | `WHATSAPP_APP_SECRET` set locally doesn't match the App Secret Meta is signing with | Re-copy the App Secret from **App Settings → Basic**; while it's blank, signature checks are skipped entirely (fine for early local testing) |
| Bot never replies, but webhook logs show `Webhook received for unknown phone_number_id=...` | The restaurant's `whatsapp_phone_number_id` in the dashboard doesn't match the number Meta is forwarding for | Double-check the Phone Number ID (not the phone number itself) copied from Meta's API Setup page |
| Bot never replies, and nothing shows in backend logs at all | Webhook not subscribed to the `messages` field, or the callback URL is stale (e.g. old ngrok tunnel) | Re-check **Webhook fields → Subscribe** next to `messages`; re-verify the callback URL |
| `httpx.LocalProtocolError: Illegal header value b'Bearer '` never happens even with no token set | This is handled on purpose — `GraphAPIWhatsAppSender` skips sending (with a warning log) when no access token is configured yet, instead of crashing | N/A — expected during onboarding before credentials are set |
| Access token stops working after ~24 hours | You're using a temporary token from the quick-start flow | Generate a permanent System User token (Part 3, step 1) |
| Can't message your own phone from the test number | Free-tier test numbers can only message pre-approved recipient numbers | Add your number under **WhatsApp → API Setup → To** and verify the OTP |
