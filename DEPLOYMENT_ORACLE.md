# Deploying to `whatsapp.kelviontech.in` on Your Existing Oracle VM

Puts the WhatsApp Business OS platform on the same Oracle Cloud VM already running your
other projects, as its own subdomain. Once this is live, it **replaces ngrok entirely** —
Meta's webhook points at this domain permanently, no rotating URL to re-paste after every
restart (see `GOING_LIVE_LOCAL_TESTING.md` for why ngrok was needed for local testing at
all).

This has been corrected against the **actual live state of the VM** (confirmed by SSHing
in and inspecting it directly — see `Deployment-context.txt`), not just the general
pattern described in your four `DEPLOYMENT*`/`PROJECT_OVERVIEW*` docs. Two things those
docs don't tell you, learned from the real server:

1. **nginx is dockerized, not host-level.** It runs as a container
   (`kelviontech-nginx-1`, part of the main `KelvionTech` project's compose stack), with
   its config directory bind-mounted from `/home/ubuntu/KelvionTech/nginx/conf.d/` on the
   host. There is no `/etc/nginx/sites-available` to `sudo cp` into — you edit files in
   the `KelvionTech` repo's checkout on the VM instead.
2. **It reaches every other project through the Docker bridge gateway
   (`172.17.0.1:<host-port>`)**, not `127.0.0.1` or a shared Docker network — each project
   is its own separate `docker compose` stack. This is why every port this project
   publishes to the host must bind to `0.0.0.0`, not `127.0.0.1` (a loopback-only bind is
   invisible from that gateway address, even though both are "the same machine").

## What's already prepared in this repo

- **`docker-compose.oracle.yml`** — port-remap override, run alongside the base compose
  file. Doesn't touch `docker-compose.yml` itself, so local `docker compose up --build`
  for anyone testing on their own machine is unaffected.
- **`nginx/whatsapp.kelviontech.in.bootstrap.conf`** — a temporary HTTP-only vhost,
  installed first (before a certificate exists).
- **`nginx/whatsapp.kelviontech.in.conf`** — the final HTTP-redirect + HTTPS vhost,
  installed after the certificate is issued.
- **`Makefile`** — wraps the whole sequence (`nginx-bootstrap` → `ssl` → `nginx-install`),
  mirroring the exact steps already proven working for `jamanvar.kelviontech.in` and
  `restaurant.kelviontech.in` on this VM.

## Ports — confirmed, not guessed

Checked directly against the live VM:

| Port | Already used by |
|---|---|
| `3001` / `8001` | `restaurant.kelviontech.in` |
| `3002` | `jamanvar.kelviontech.in` |
| `5433` | restaurant's own Postgres |

This project takes the next free slot — **`3004`** (frontend), **`8002`** (backend),
**`5434`** (postgres), **`6380`** (redis), **`9002`**/**`9003`** (minio) — already set in
`docker-compose.oracle.yml`. **Re-verify before deploying**, the same way the real
session that surfaced the `3002` conflict did:
```bash
sudo ss -ltnp | grep -E ':(3004|8002|5434|6380|9002|9003)\b'
```
Empty output means all clear. If anything's taken, edit the host-side port number (left
side of each `"host:container"` pair) in `docker-compose.oracle.yml`, and the matching
`172.17.0.1:<port>` references in both nginx conf files, to match.

## Steps

### 1. DNS
At your registrar: add an **A record** — Host `whatsapp`, Type `A`, Value your VM's public IP.

### 2. Get the code onto the VM
```bash
ssh kelvion   # or: ssh -i /path/to/oracle_key.pem ubuntu@<PUBLIC_IP>
cd /home/ubuntu
git clone git@github.com:<you>/whatsapp.git whatsapp-app   # use the already-authorized
cd whatsapp-app                                             # github_deploy key, same as
                                                              # every other project here
```

### 3. Production `.env`
```bash
cp .env.example .env
nano .env
```
Generate fresh secrets — **never reuse your local `backend/.env` values**:
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
WHATSAPP_WEBHOOK_VERIFY_TOKEN=<pick a real secret string>
CORS_ORIGINS=["https://whatsapp.kelviontech.in"]
FRONTEND_URL=https://whatsapp.kelviontech.in
PUBLIC_API_BASE_URL=https://whatsapp.kelviontech.in/api/v1
PUBLIC_MEDIA_BASE_URL=https://whatsapp.kelviontech.in/api/v1/media
S3_ACCESS_KEY=<generated>
S3_SECRET_KEY=<generated>
MINIO_ROOT_USER=<same as S3_ACCESS_KEY>
MINIO_ROOT_PASSWORD=<same as S3_SECRET_KEY>
```
Leave `WHATSAPP_APP_SECRET` blank for now — pasted in during step 8. With
`ENVIRONMENT=production`, the backend **fails closed** on an unsigned webhook until you
set it (no unsafe dev fallback — see `GOING_LIVE_LOCAL_TESTING.md` §6).

### 4. Bring the stack up
```bash
make up
make ps          # all containers healthy?
make check        # backend/frontend reachable directly AND across the bridge gateway
```

### 5. Bootstrap nginx (HTTP only, before the cert exists)
```bash
make nginx-bootstrap
curl -I http://whatsapp.kelviontech.in/    # expect 200
```

### 6. Issue the certificate
```bash
make ssl
```
Watch for `Successfully received certificate.` If it hangs, you likely forgot step 5 (the
ACME challenge path has to be reachable over plain HTTP first) — `Ctrl+C` and re-check.

### 7. Install the real HTTPS vhost
```bash
make nginx-install
curl -I https://whatsapp.kelviontech.in/    # expect 200, and 301 on the plain-HTTP version
```

### 8. Seed the database
```bash
make seed
```
Log in at `https://whatsapp.kelviontech.in` with the seeded super admin
(`admin@kelviontech.dev` / `ChangeMe123!`) — **change that password immediately**.

### 9. Point Meta at this domain instead of ngrok
In the Meta App dashboard (**WhatsApp → Configuration**):
- **Callback URL**: `https://whatsapp.kelviontech.in/api/v1/webhook`
- **Verify Token**: the `WHATSAPP_WEBHOOK_VERIFY_TOKEN` from step 3
- **Verify and Save**, then **Subscribe** to `messages`

Copy the real **App Secret** (App Settings → Basic) into `.env`'s `WHATSAPP_APP_SECRET`,
then:
```bash
make restart
```
From here, `GOING_LIVE_LOCAL_TESTING.md` §8 (connecting a business's Phone Number
ID/Access Token from the dashboard, sending "hi") applies exactly the same — just against
a permanent URL instead of ngrok.

## Day-to-day

```bash
git pull
make up            # ship a code change
make logs-backend  # tail logs
make restart       # after an .env-only change, no rebuild needed
```

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `make ssl` hangs / times out | Bootstrap vhost (step 5) wasn't installed first, or DNS hasn't propagated yet — `dig +short whatsapp.kelviontech.in` should return your VM's IP |
| `nginx -t` fails during `nginx-install` | Certificate wasn't actually issued — check `make ssl`'s output for `Successfully received certificate` |
| 200 on port 8002 directly but nginx returns a gateway error | Backend/frontend bound to `127.0.0.1` instead of `0.0.0.0` — check `docker-compose.oracle.yml`'s port lines have no `127.0.0.1:` prefix for backend/frontend (postgres/redis/minio SHOULD keep it) |
| Everything works over HTTP but not HTTPS | `make nginx-install` wasn't run, or ran before `make ssl` finished |

## What's deliberately not covered here

- **Backups** — `GOING_LIVE.md` §6 already documents `backend/scripts/backup_db.sh`; wire
  it into cron the same way as your other Postgres-backed projects.
- **Multiple backend workers/replicas** — the rate limiter and the WebSocket
  `ConnectionManager` both keep state in process memory; don't scale past one backend
  container without moving that state to Redis first (same caveat noted in your other
  projects' `DEPLOYMENT.md`).
