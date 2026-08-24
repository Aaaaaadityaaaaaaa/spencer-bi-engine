# TASK-028 — Deploy Packaging (Docker + Caddy + Postgres, single-VM SaaS)

**Status: ✅ SIGNED OFF by user (2026-08-25) — static validation green; live `compose up` (AC #5) deferred to the deploy VM**

## Objective
Make Spencer actually deployable on a domain as a single-VM SaaS: containerize the backend and the
built frontend, put **Caddy** in front for same-origin routing + automatic HTTPS, run **Postgres** as
the identity/ownership store and **Redis** as the working cache — all via one `docker compose up`.
Completes the second half of the "make it a deployable SaaS" master request (TASK-027 delivered auth +
per-user isolation and kept config deploy-ready; this wave adds the packaging that stands it up).

Target: **Oracle Cloud Always-Free ARM (Ampere A1)** VM, arm64, ~$0/mo — but every base image is
multi-arch and nothing is Oracle-specific, so the same stack runs on any Docker host (Fly / Render /
a VPS); only DNS + the domain differ.

## Decisions
- **Topology — 4 services:** `web` (Caddy: serves the built SPA, reverse-proxies the API, terminates
  TLS), `backend` (uvicorn/FastAPI), `db` (Postgres 16), `redis` (7). Same-origin in prod, so CORS is
  a non-issue behind the proxy. Caddy routes the backend prefixes
  (`/auth`, `/sessions`, `/admin`, `/health`, `/test-duckdb`, `/docs`, `/openapi.json`, `/redoc`) to
  `backend:8000`; every other path serves the SPA with a `try_files … /index.html` fallback.
- **Frontend build:** multi-stage — `node:22-alpine` (`npm ci && npm run build` with `VITE_API_BASE=""`
  → relative, same-origin API calls) → `caddy:2-alpine` serving `/srv`.
- **Backend image:** `python:3.13-slim`; every dep ships a wheel (no compiler/system libs); runs as a
  non-root user; runtime data (the DuckDB file + uploaded files) lives on a named volume so it survives
  image rebuilds / `compose down`.
- **Identity store:** Postgres in prod (`postgresql+psycopg://…@db:5432/spencer`) — the dialect-neutral
  path TASK-027 already supports; SQLite stays the zero-infra dev default.
- **Security gates (folded in from the TASK-027 self-review 🟠 items):**
  - JWT **fail-fast**: the app refuses to boot when the insecure built-in dev key is active AND
    `SPENCER_ENV=production` (else a prod that forgets `SPENCER_JWT_SECRET` runs with a forgeable key).
  - Registration **closed** by default in the prod env template (`SPENCER_ALLOW_REGISTRATION=false`),
    because the LLM key pool is global/paid until per-user quota attribution lands.

## What it adds (NEW unless marked EDIT)
- `backend/Dockerfile`, `backend/.dockerignore`
- `frontend/Dockerfile`, `frontend/.dockerignore`
- `Caddyfile` — same-origin routing + `{$SITE_ADDRESS}` (auto-HTTPS on a real domain; `:80` locally)
- `docker-compose.yml` (EDIT: extend the current Redis-only file into the full 4-service stack)
- `.env.production.example` — prod env template (+ a `.gitignore` unignore exception so it commits)
- `DEPLOY.md` — VM provisioning → DNS → `compose up` → TLS → backups → updates runbook
- `backend/config.py` + `backend/main.py` (EDIT) — `SPENCER_ENV` knob + JWT prod fail-fast
- `.env.example` (EDIT) — document `SPENCER_ENV`

## Acceptance criteria
1. ✅ Frontend production build succeeds (`npm run build`, `VITE_API_BASE=""`) → static `dist/`.
   *Proof:* `vue-tsc -b` typecheck clean + `vite build` `✓ built in 40.9s`, `dist/index.html`+assets, exit 0.
2. ✅ `docker compose config` validates the full stack. *Proof:* exit 0; renders 4 services with
   healthchecks + 5 named volumes; `SPENCER_APP_DB_URL` composes to `postgresql+psycopg://spencer:…@db:5432/spencer`,
   `SPENCER_ENV=production`, `SPENCER_ALLOW_REGISTRATION="false"`.
3. ✅ JWT prod fail-fast. *Proof:* `backend/test_deploy_safety.py` 4/4 — prod+no-secret refuses to boot
   ("forgeable"); prod+secret boots; prod+Postgres boots with no SQLite warning; dev default boots on the fallback.
4. ✅ Registration closed in the prod template (`.env.production.example` ships `false`; compose defaults
   `false`) — verified in the #2 render; `test_auth.py` (TASK-027) already proves closed → 403.
5. ⏳ **Live compose proof** (Docker daemon required): `docker compose up` → 4 services healthy; SPA loads
   over the `web` origin; register → login → upload same-origin (Bearer attaches, no CORS); a 2nd user
   cannot see the 1st's dataset; Postgres persists users across `compose restart`. *(Authored + statically
   validated; the daemon is down here — run on the VM or once Docker Desktop is up.)*
6. ✅ **Must-not-change:** `README.md` and `.ai/CURRENT_STATE.md` untouched by me.

## Verification
- **Static (run, all green):** `npm run build` (exit 0); `docker compose config` (exit 0); gate test
  `backend/test_deploy_safety.py` 4/4; backend metadata build `pip install . --dry-run --no-deps` (status
  'done', exit 0 — proves the deps-only `pyproject` fix below).
- **Live (needs the Docker daemon, not run here):** the #5 end-to-end containerized-stack proof.

## Non-goals (documented follow-ons)
Kubernetes / horizontal scale (the DuckDB single-writer file is the ceiling — see `PROJECT.md`);
managed or HA Postgres; a CI/CD pipeline; a secrets manager (the env file is the single-VM MVP);
per-user LLM-key quota; object storage for uploads.

## Definition of Done
One `docker compose up` yields a working, TLS-terminated, same-origin multi-tenant app on a domain:
built SPA served by Caddy, FastAPI backend, Postgres identity store, Redis cache; the prod JWT
fail-fast + closed-registration gates active; a `DEPLOY.md` runbook. Static validation green in this
environment; the live stack proof run when the Docker daemon is available. Left in `tasks/active/` for
the single sign-off. **Not self-closed.**

## Self-review (severity-graded)
Static validation is green (AC #1-4, #6); the live-stack proof (#5) needs the Docker daemon, which is
down in this environment, so the findings below are reasoned from the artifacts + the TASK-027 live auth
proof, not all runtime-exercised.

**Found + fixed during this review**
- 🟠→fixed **Backend image build would fail on setuptools auto-discovery.** `pyproject.toml` had no
  `[build-system]`/package config, and `routers/`, `services/`, `models/` have no `__init__.py`; a
  flat-layout `pip install .` over loose modules + namespace dirs can raise "Multiple top-level packages
  discovered." The image delivers code via `COPY`+`PYTHONPATH` and runs `uvicorn main:app`, so `pip
  install .` only needs the *dependencies* — added `[build-system]` + a deps-only `[tool.setuptools]`
  (empty `packages`/`py-modules`). Proven: `pip install . --dry-run --no-deps` → metadata 'done', exit 0.
- 🟢→fixed **DB-password DSN footgun.** `POSTGRES_PASSWORD` is interpolated raw into `SPENCER_APP_DB_URL`;
  a `@ : / ? # %` in it would corrupt the DSN. Added a "keep it URL-safe" note to `.env.production.example`.

**Open findings**
- 🟠 **Live stack unproven (AC #5).** Image builds, healthcheck timing, Caddy ACME/TLS issuance, and the
  same-origin Bearer flow are validated by construction + static checks only — no `docker compose up` has
  run. This is the DoD's core claim and the one open AC. Mitigated by the four static proofs and TASK-027's
  live auth proof; must be run on the VM (or a local daemon) before real traffic.
- 🟡 **`web` waits on backend *created*, not *healthy*** (`depends_on: - backend`, no `condition`). Caddy
  can accept requests before uvicorn is ready → a few 502s on cold boot until the backend healthcheck
  passes. Self-heals per-request; tightening to `service_healthy` would delay Caddy ~20-40s each boot.
- 🟢 **Register tab shows even when registration is closed.** The SPA can't read
  `SPENCER_ALLOW_REGISTRATION`, so a closed deployment renders a Register form that 403s on submit.
  DEPLOY.md §6 documents the flip-flag path; a `/auth/config` probe to hide the tab is a follow-on.
- 🟢 **`/health` is a liveness, not readiness, probe** — returns before DB/Redis are asserted, so
  "healthy" = "process serving," not "fully wired." Adequate for orchestration; a deeper readiness check
  is a follow-on.
- 🟢 **Frontend image is compose-only.** The Caddyfile is bind-mounted, not baked; the image run
  standalone serves Caddy's default site, not `/srv`. Intended (compose is the deploy unit); noted so it
  is not mistaken for a bug.
- ℹ️ **No pinned lockfile for pip** (`npm ci` is lockfile-pinned; `pip install .` resolves at build time).
  Reproducible-build pinning (uv / pip-tools) is a documented follow-on.
- ℹ️ **Secrets in `.env` on the host** (no secrets manager) — the single-VM MVP, documented in DEPLOY.md.
- ℹ️ `on_event("startup")` deprecation and the per-request `get_current_user` DB read are pre-existing
  (TASK-027), not introduced here.

**Not self-closed** — left in `tasks/active/` for the single user sign-off; the live #5 proof is offered
next (start Docker Desktop, or run it on the VM).
