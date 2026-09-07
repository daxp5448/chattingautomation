# Deploying to `whatsapp.kelviontech.in` on Your Existing Oracle VM

This puts the WhatsApp Business OS platform on the same Oracle Cloud Always Free VM
already running your other 4-5 projects, as its own subdomain — following the exact
pattern documented in `Resources/Personal/DEPLOYMENT_ORACLE_SUBDOMAIN_GUIDE.md` for
`restaurent.kelviontech.in`. Once this is live, it **replaces ngrok entirely** — Meta's
webhook points straight at this domain, permanently, with no rotating URL to re-paste
after every restart (see `GOING_LIVE_LOCAL_TESTING.md` for why ngrok was needed at all).

This file only covers what's specific to *this* project. General Oracle/Docker/nginx
concepts (dual firewall, `make` targets, certbot renewal) are already explained in your
existing four guides — this doesn't repeat them.

## What's already prepared in this repo

- **`docker-compose.oracle.yml`** — an override file that remaps this stack's ports so it
  doesn't collide with your other projects (following the same numbering the restaurant
  app used: 8001/3001/5433 → this one takes 8002/3002/5434, plus 6380 for redis and
  9002/9003 for minio). It does **not** touch `docker-compose.yml` — local
  `docker compose up --build` for anyone testing on their own machine is unaffected.
- **`nginx/whatsapp.kelviontech.in.conf`** — the vhost config, routing `/api/*` and the
  WebSocket path to the backend, everything else to the frontend.

**Before you deploy**: SSH into the VM and check those port numbers are actually free —
```bash
docker compose ps -a          # in each existing project's directory
sudo ss -tlnp | grep LISTEN
```
If any of `5434`/`6380`/`9002`/`9003`/`8002`/`3002` are taken, edit the port numbers in
`docker-compose.oracle.yml` (left side of each `"host:container"` pair only — never touch
the container-side number) and the two upstream ports in the nginx config to match.

## Steps

### 1. DNS
At your registrar (wherever `kelviontech.in` is managed): add an **A record**.

| Host | Type | Value |
|---|---|---|
| `whatsapp` | A | `<YOUR_ORACLE_VM_PUBLIC_IP>` |

### 2. Get the code onto the VM
```bash
ssh -i /path/to/oracle_key.pem ubuntu@<YOUR_PUBLIC_IP>
cd /home/ubuntu
git clone <YOUR_WHATSAPP_GITHUB_REPO_URL> whatsapp-app
cd whatsapp-app
```

### 3. Production `.env`
```bash
cp .env.example .env
nano .env
```
Generate fresh secrets — **never reuse the values from your local `backend/.env`**:
```bash
python3 -c "import secrets; print(secrets.token_urlsafe(24))"   # -> POSTGRES_PASSWORD
python3 -c "import secrets; print(secrets.token_urlsafe(48))"   # -> JWT_SECRET_KEY
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"  # -> FIELD_ENCRYPTION_KEY
```
Set at minimum:
```env
ENVIRONMENT=production
POSTGRES_PASSWORD=<generated>
JWT_SECRET_KEY=<generated>
FIELD_ENCRYPTION_KEY=<generated>
WHATSAPP_WEBHOOK_VERIFY_TOKEN=<pick a real secret string, not the local "change-me-verify-token">
CORS_ORIGINS=["https://whatsapp.kelviontech.in"]
FRONTEND_URL=https://whatsapp.kelviontech.in
PUBLIC_API_BASE_URL=https://whatsapp.kelviontech.in/api/v1
PUBLIC_MEDIA_BASE_URL=https://whatsapp.kelviontech.in/api/v1/media
S3_ACCESS_KEY=<generated>
S3_SECRET_KEY=<generated>
MINIO_ROOT_USER=<same as S3_ACCESS_KEY>
MINIO_ROOT_PASSWORD=<same as S3_SECRET_KEY>
```
`WHATSAPP_APP_SECRET` — leave blank for now; you'll paste this in once you're in the Meta
App dashboard (see §6). `ENVIRONMENT=production` means the backend **fails closed** on an
unsigned webhook until you do — no accidental "unsafe unsigned" fallback like local dev
gets (see `GOING_LIVE_LOCAL_TESTING.md` §6).

### 4. Launch
```bash
docker compose -f docker-compose.yml -f docker-compose.oracle.yml up -d --build
docker compose -f docker-compose.yml -f docker-compose.oracle.yml ps
curl http://127.0.0.1:8002/health   # expect {"status":"ok"}
```
The backend's own `command:` already runs `alembic upgrade head` on boot — no separate
migration step needed.

### 5. nginx + SSL
```bash
sudo cp nginx/whatsapp.kelviontech.in.conf /etc/nginx/sites-available/
sudo ln -s /etc/nginx/sites-available/whatsapp.kelviontech.in.conf /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

sudo certbot --nginx -d whatsapp.kelviontech.in
sudo systemctl reload nginx
```
Visit `https://whatsapp.kelviontech.in` — you should see the login page.

### 6. Seed + first login
```bash
docker compose -f docker-compose.yml -f docker-compose.oracle.yml exec backend python -m app.seed
docker compose -f docker-compose.yml -f docker-compose.oracle.yml exec backend python -m app.scripts.seed_niche_templates
```
Log in at `https://whatsapp.kelviontech.in` with the seeded super admin
(`admin@kelviontech.dev` / `ChangeMe123!`) — **change that password immediately** from the
dashboard, same rule as your other projects.

### 7. Point Meta at this domain instead of ngrok
This is the whole payoff. In the Meta App dashboard (**WhatsApp → Configuration**):
- **Callback URL**: `https://whatsapp.kelviontech.in/api/v1/webhook`
- **Verify Token**: the `WHATSAPP_WEBHOOK_VERIFY_TOKEN` you set in step 3
- **Verify and Save**, then **Subscribe** to `messages` under Webhook fields

Copy the real **App Secret** from **App Settings → Basic** into `.env`'s
`WHATSAPP_APP_SECRET`, then:
```bash
docker compose -f docker-compose.yml -f docker-compose.oracle.yml restart backend
```
From here the rest of `GOING_LIVE_LOCAL_TESTING.md` §8 (connecting a business's Phone
Number ID/Access Token from the dashboard, sending "hi") applies exactly the same —
you're just doing it against a permanent URL instead of ngrok.

## Day-to-day

Same `make`-style workflow as your other projects, just always pass both compose files:
```bash
git pull
docker compose -f docker-compose.yml -f docker-compose.oracle.yml up -d --build   # ship a change
docker compose -f docker-compose.yml -f docker-compose.oracle.yml logs -f backend  # tail logs
```
If you want a `Makefile` wrapping these (matching your other two projects' `make deploy`/
`make logs`/`make check` convenience), that's a small addition worth doing once this is
confirmed working — not included here to keep this first pass minimal and verifiable.

## What's deliberately not covered here

- **Backups** — `GOING_LIVE.md` §6 already documents `backend/scripts/backup_db.sh` and a
  cron entry; wire it up the same way you did for your other Postgres-backed projects.
- **Multiple backend workers/replicas** — same caveat as your other projects' `DEPLOYMENT.md`:
  the rate limiter and the WebSocket `ConnectionManager` both keep state in process memory,
  so don't scale this past one backend container without moving that state to Redis first.
