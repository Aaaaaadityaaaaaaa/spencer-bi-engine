# Deploying Project Spencer

Spencer ships as a 4-container stack run by Docker Compose:

| Service   | Image           | Role                                                    |
|-----------|-----------------|---------------------------------------------------------|
| `web`     | Caddy 2 (+ SPA) | Serves the built frontend, reverse-proxies the API, TLS |
| `backend` | FastAPI/uvicorn | API + DuckDB analytics engine + Redis client            |
| `db`      | Postgres 16     | Identity / ownership store (users + datasets)           |
| `redis`   | Redis 7         | Working cache + session-liveness TTL markers            |

Everything is same-origin behind Caddy, so there is no CORS to configure and one
hostname serves both the app and the API.

## 0. Prerequisites
- A host with Docker Engine + the Compose plugin (`docker compose version`).
  Target: **Oracle Cloud Always-Free ARM (Ampere A1)** -- 4 vCPU / 24 GB, arm64,
  ~$0/mo -- but any x86/arm64 Docker host works (Fly, Render, a VPS, your laptop).
- A domain name you can point at the host (for automatic HTTPS).
- Ports **80** and **443** reachable from the internet (Caddy needs them for the
  Let's Encrypt challenge).

## 1. Provision the VM (Oracle Ampere example)
1. Create an **Ampere A1 (arm64)** Ubuntu 22.04+ instance (Always-Free shape).
2. In the instance's **VCN security list / NSG**, open ingress TCP **22, 80, 443**.
3. SSH in and install Docker:
   ```bash
   curl -fsSL https://get.docker.com | sh
   sudo usermod -aG docker $USER   # log out/in so `docker` works without sudo
   ```
   If Ubuntu's `ufw` is enabled, also: `sudo ufw allow 80,443/tcp`.

## 2. Get the code + configure
```bash
git clone <your-repo-url> spencer && cd spencer
cp .env.production.example .env
nano .env    # set SITE_ADDRESS, SPENCER_JWT_SECRET, POSTGRES_PASSWORD, LLM keys
```
- `SPENCER_JWT_SECRET` -- generate with `openssl rand -hex 32`. **Required**: in
  production the backend refuses to start without it.
- `SITE_ADDRESS` -- your domain, e.g. `app.example.com`.
- Registration ships **closed** (`SPENCER_ALLOW_REGISTRATION=false`); see §6.

## 3. Point DNS at the host
Create an **A record** for `SITE_ADDRESS` -> the VM's public IP, then verify:
```bash
dig +short app.example.com    # should print the VM IP
```

## 4. Build + launch
```bash
docker compose up -d --build
docker compose ps             # all four services should be healthy/running
docker compose logs -f web    # watch Caddy obtain the TLS certificate
```
Visit `https://app.example.com` -- the login screen loads over HTTPS.

## 5. Verify
```bash
curl -fsS https://app.example.com/health          # {"status":"ok"}
```
Register a user in the UI (see §6), upload a CSV, and confirm a second account
cannot see the first's data.

## 6. First account when registration is closed
The clean path: set `SPENCER_ALLOW_REGISTRATION=true` in `.env`, `docker compose up -d`,
register your account in the UI, then set it back to `false` and `docker compose up -d`
again. To grant admin, flip the flag directly in Postgres:
```bash
docker compose exec db psql -U spencer -d spencer \
  -c "UPDATE users SET is_admin = true WHERE email = 'you@example.com';"
```
(A first-run seed / admin-promotion CLI is a documented follow-on.)

## 7. Backups
Durable state is Postgres (identity) + the backend volume (DuckDB + uploads):
```bash
# Postgres logical backup
docker compose exec db pg_dump -U spencer spencer > backup_$(date +%F).sql
# Backend data volume (DuckDB file + uploaded files)
docker run --rm -v spencer_backend_data:/data -v "$PWD":/out alpine \
  tar czf /out/backend_data_$(date +%F).tgz -C /data .
```

## 8. Updating
```bash
git pull
docker compose up -d --build      # rebuilds changed images, recreates containers
```
Volumes (Postgres, uploads, DuckDB, Caddy certs) persist across rebuilds.

## Running locally without a domain (same stack, no TLS)
Leave `SITE_ADDRESS` blank (or `:80`) in `.env`, then `docker compose up -d --build`
and open `http://localhost`. Caddy serves plain HTTP -- useful for an end-to-end
proof of the container stack before pointing a real domain at it.

## Notes / limits
- **Scale ceiling:** the analytics engine is a single-writer DuckDB file -- great
  for one small-to-medium VM, not horizontally scalable. See `PROJECT.md`.
- **Redis** is published only on `127.0.0.1:6379` (host-local, for the dev
  workflow); it is not exposed to the network.
- **Secrets** live in `.env` on the host (gitignored). A secrets manager is a
  follow-on; for a single VM the env file is the MVP.
- **API docs** (`/docs`, `/openapi.json`, `/redoc`) are proxied through; delete
  those tokens from the `@api` matcher in `Caddyfile` to hide them in production.
