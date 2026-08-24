# TASK-027 — User Accounts + Per-User Data Isolation (Multi-Tenancy)

**Status: ✅ SIGNED OFF by user (2026-08-25) — live 2-user isolation proven; moved to completed/**

## Objective
Turn Spencer from a single-analyst tool into a **deployable multi-tenant SaaS**: real user
accounts (email + password) and **strict per-user data isolation**, so two users on the same
deployment cannot see or touch each other's datasets. This deliberately revises the old
`PROJECT.md` stance ("single analyst per session — not multi-tenant"): every `/sessions/*`
route is now gated by authentication **and** an ownership check.

Before this task the app had **zero auth**: every `/sessions/{uuid}/*` route trusted the path
UUID as an unguessable capability with no owner check, and `/admin/*` was wide open. This is
the first half of the "make it a deployable SaaS" master request (the deploy-packaging half —
Docker/Compose/Caddy on an Oracle Ampere VM — is a documented follow-on; see Non-goals).

## Decisions (locked with the user)
- **Auth mechanism:** JWT bearer (`Authorization: Bearer <token>`), HS256, signed with
  `SPENCER_JWT_SECRET`. Stored client-side, attached by an Axios request interceptor.
  Host-agnostic; no CSRF machinery, no server-side session store.
- **Identity store:** **SQLAlchemy 2.x** behind a single `SPENCER_APP_DB_URL` — **SQLite by
  default** (zero-infra dev, testable here) and **Postgres in prod** (`postgresql+psycopg://`).
  ORM models are dialect-neutral so the same code runs on both. Separate from the analytical
  DuckDB (rebuildable) and Redis (ephemeral).
- **Ownership source of truth:** a `datasets` row (`session_uuid → user_id`) in the app DB.
  DuckDB/Redis are unchanged as the working/analytical layer; the only new gate is
  "does this user own this session_uuid?".
- **Isolation contract:** a request for someone else's (or a nonexistent) session returns
  **404, never 403** — the API must not leak which UUIDs exist. Missing/invalid token → **401**
  (authentication is checked *before* ownership, so no-token is always 401 even on a real UUID).

Assumptions (stated; change on request): open self-serve registration (env-toggleable via
`SPENCER_ALLOW_REGISTRATION`); **no** email-verification / password-reset / OAuth for the MVP;
auth is **required** on all `/sessions` routes (no anonymous mode); pre-auth dev data has no
owner and 404s for everyone (disposable — wipe `spencer.db`/uploads if desired).

## Architecture at a glance
```
Browser ──JWT Bearer──▶ FastAPI
  │                       ├─ Depends(get_current_user) ────▶ app DB: users      [durable identity]
  │                       ├─ Depends(require_session_owner) ▶ app DB: datasets   [ownership map]
  │                       └─ existing singletons: DuckDB (t_{uuid}_*), Redis (schema/TTL)
  └─ localStorage: spencer.auth.v1 (token+user) + per-user-namespaced convenience stores
```

## What changed

### Backend — new files
- **`services/app_db.py`** — one SQLAlchemy `engine` + `SessionLocal` chosen by
  `config.APP_DB_URL` (SQLite gets `check_same_thread=False`; both get `pool_pre_ping`).
  Dialect-neutral models: `User(id, email unique+indexed, password_hash, is_admin, created_at)`,
  `Dataset(session_uuid PK, user_id FK+indexed, primary_table, file_name, created_at,
  last_active_at)`. `init_db()` = `Base.metadata.create_all` (called fail-fast from startup).
- **`services/auth_service.py`** — password hashing + JWT + user CRUD. Typed errors
  (`AuthError` → 401, `DuplicateUserError` → 400). `normalize_email` (strip+lower) so case/space
  variants collide as one account. `authenticate` returns the **same** generic error for
  unknown-email and wrong-password (no account enumeration).
- **`services/ownership_service.py`** — thin helpers over `datasets`: `record_dataset`
  (defensive upsert — never rebinds an existing owner), `get_dataset`, `user_owns`,
  `list_user_datasets`, `touch_dataset` (slides `last_active_at`), `delete_dataset`.
- **`deps.py`** — the DI seam (the codebase's **first `Depends()`**):
  `get_db` (request-scoped Session, closed in `finally`); `get_current_user`
  (parse `Bearer`, decode, load User → 401 with `WWW-Authenticate: Bearer` on any failure);
  `require_session_owner` (404 if no row or not owner; else slides owned-TTL + returns the
  `Dataset`); `require_admin` (403 unless `is_admin`).
- **`routers/auth.py`** (prefix `/auth`, **no** session guard) — `POST /register` (honors
  `config.ALLOW_REGISTRATION` live → 403 if disabled; dup → 400), `POST /login` (→ 401 on bad
  creds), `GET /me` (behind `get_current_user`). register/login both return `TokenResponse`.

### Backend — edits
- **`main.py`** — `init_db()` at startup; mount `auth` at `/auth` (public); guard the existing
  surface at include time: `query`/`ai`/`schedule` routers each get
  `dependencies=[Depends(require_session_owner)]`, `admin` gets `Depends(require_admin)`,
  `/test-duckdb` is now admin-gated, `/health` stays public. `session.router` is **mixed**
  (it mints UUIDs) so it is guarded per-route (below).
- **`routers/session.py`** — `create_session` gets `user=Depends(get_current_user)` **only**
  (it creates the UUID) and, after the table exists, calls `ownership_service.record_dataset`.
  Every `/{session_uuid}/*` route gets `Depends(require_session_owner)`. `delete_session` is
  **implemented** (was a no-op stub): drops the session's DuckDB tables, purges its Redis keys,
  removes `uploads/{uuid}`, deletes the `datasets` row — a real "delete my dataset".
- **`services/cleanup_service.py`** — new `reclaim_session_storage(session_uuid)` (used by
  `delete_session`): snapshots the catalog, drops only this session's prefix-matched tables
  (quote-escaped), purges Redis, rmtrees the upload dir, CHECKPOINTs. Returns drop/removal counts.
- **`models/schemas.py`** — `RegisterRequest{email:EmailStr, password:8..72}`,
  `LoginRequest{email:EmailStr, password:1..200}`, `UserResponse{id,email,is_admin,created_at}`,
  `TokenResponse{access_token, token_type="bearer", user}`.
- **`config.py`** — `JWT_SECRET` (+ `JWT_SECRET_IS_DEV_FALLBACK` with a loud startup warning),
  `JWT_ALGORITHM`, `JWT_EXPIRY_HOURS` (168), `APP_DB_URL` (`sqlite:///spencer_app.db`),
  `ALLOW_REGISTRATION` (true), `OWNED_SESSION_TTL_DAYS`/`_SECONDS` (30d) — all `os.getenv`.
- **`pyproject.toml`** — `pydantic[email]`, `sqlalchemy>=2.0`, `pyjwt>=2.8`, `bcrypt>=4.0`,
  `psycopg[binary]>=3`. **`.env.example`** — a documented "Auth & multi-tenancy" section.

### DEVIATION from the plan — bcrypt used directly (not `passlib[bcrypt]`)
The plan said `passlib[bcrypt]`. **passlib is not used.** Modern `bcrypt` (≥4.1) removed the
`__about__.__version__` attribute passlib probes at import, so `passlib` + a current `bcrypt`
emits a spurious error / can fail to detect the backend. `bcrypt` is already a transitive dep and
its API is tiny, so `auth_service` calls it directly: `hashpw`/`checkpw` with `gensalt()`.
- **72-byte rule:** `bcrypt` ≥4.1 *raises* past 72 bytes (older versions silently truncated), so
  the password is UTF-8 encoded and sliced `[:72]` before hash/verify (matching bcrypt's own
  historical truncation). `RegisterRequest.password` is also capped `max_length=72` for a clean
  422 instead of a 500. `verify_password` catches `ValueError/TypeError` → returns False.

### Frontend — new files
- **`composables/useAuth.ts`** — module-scoped reactive singleton (mirrors `useSession`).
  State `{ token, user }`, `isAuthenticated` computed. Actions `register`/`login`/`logout`/
  `loadFromStorage`/`fetchMe`. Persists `spencer.auth.v1`. On any user change it re-scopes the
  per-user convenience stores and (on logout) resets the session singleton + clears the token
  from the Axios layer.
- **`views/AuthView.vue`** — full-screen sign-in / register card (segmented toggle), standalone
  layout (no sidebar), house style reused from `OpDialog` (`inputCls`/`labelCls`, the
  `bg-primary … hover:bg-primary-7` button).

### Frontend — edits
- **`services/api.ts`** — module-level token + `setAuthToken`; a **request interceptor** attaching
  `Authorization: Bearer`; a **response interceptor** that on a non-`/auth/*` 401 calls a
  registered `onUnauthorized()` hook (wired by `useAuth` → logout + redirect; avoids an
  api→router import cycle). New calls `registerUser`/`loginUser`/`fetchMe`.
- **`composables/useQueryHistory.ts` + `useDashboards.ts`** — per-user key namespacing: state
  starts **empty**, `loadForUser(userId)` (re)loads from `${base}:${userId}` (replace, not
  append) on login and clears on logout, so a shared browser never leaks one user's
  history/queries/dashboards to another. (Pre-auth un-namespaced data is not migrated — disposable.)
- **`router/index.ts`** — public `/login` route (`meta.public`); a global `beforeEach`:
  non-public + unauthenticated → `/login?redirect=…`; authenticated on `/login` → `/table`.
- **`App.vue`** — renders the sidebar/header shell only when authenticated (bare `<router-view>`
  for `/login`); a user-email + **Logout** control in the sidebar footer; `restoreSession()` runs
  only when authenticated (and when auth flips on).
- **`main.ts`** — `useAuth().loadFromStorage()` **before** `mount()` so the router guard sees the
  right auth state on the very first navigation.

## Config (all new; documented in `.env.example`)
`SPENCER_JWT_SECRET` (required in prod; insecure dev fallback + startup warning),
`SPENCER_JWT_EXPIRY_HOURS` (168), `SPENCER_APP_DB_URL` (`sqlite:///spencer_app.db` dev /
`postgresql+psycopg://…` prod), `SPENCER_ALLOW_REGISTRATION` (true),
`SPENCER_OWNED_SESSION_TTL_DAYS` (30). No secrets are committed, logged, or returned by any
endpoint; the JWT secret is read from env only.

## Acceptance criteria
1. ✅ **Register → login → /me** round-trips; token carries `sub`+`email`; `/me` returns the user.
2. ✅ **Duplicate email → 400** (case/space-insensitive: `  ALICE@Example.com ` collides with
   `alice@example.com`).
3. ✅ **Bad credentials → 401**, identical message for wrong-password vs unknown-email (no
   enumeration). Missing / malformed / no-`Bearer`-scheme / bad token → **401**.
4. ✅ **`ALLOW_REGISTRATION=false` → register 403** (read live per request).
5. ✅ **Validation:** short password → 422; invalid email → 422; >72-byte password hashes+verifies
   (no bcrypt 500).
6. ✅ **Isolation:** user A creates a session; user B → **404** on `/schema`, `/data`, `/history`,
   `/quality`, `/transform`, `/ask` (the guard 404s before the handler, so `/ask` never reaches
   the LLM); A succeeds on its own `/schema` + `/data`; a valid token on an unknown UUID → **404**.
7. ✅ **AuthN before authZ:** no token on a real UUID → **401** (not 404).
8. ✅ **Admin gating:** `/admin/*` → 403 for a non-admin, 401 with no token, 200 for an admin.
9. ✅ **delete_session** drops the table + upload dir + Redis keys and deletes the ownership row;
   a second delete → 404 (no double-free).
10. ✅ **Frontend strict build green** — `cd frontend && npx vue-tsc --noEmit` exits 0 (no errors).
11. ✅ **Live 2-user isolation proof** (browser, real backend + Redis): guard redirect
    (`/table` → `/login?redirect=/table`); register A → lands in app with a persisted token; A
    uploads → 5-row grid renders over **guarded** routes (proves the Bearer header attaches, since
    the guarded `/data` returns 200); sign out → `/login`, auth + session cleared; register B →
    empty upload workspace (**A's dataset NOT visible**, no session pointer); B (valid token)
    hitting A's session UUID → **404**; corrupted persisted token on reload → boot `fetchMe` 401
    → auto-logout → redirect to `/login` with storage cleared.
12. ✅ **Must-not-change:** `README.md` and `.ai/CURRENT_STATE.md` untouched by me. (`session.py`,
    `CURRENT_STATE.md`, `redis_manager.py` diffs at session start are pre-existing parallel
    TASK-013 work; I only added the auth/ownership seam to `session.py`.)

## Verification (real output)
- **`backend/test_auth.py`** — **18/18 PASS** on **real Redis** + a throwaway SQLite app DB.
  `TMPD=$(mktemp -d) && cd "$TMPD" && SPENCER_APP_DB_URL="sqlite:///test_auth_app.db"
  SPENCER_JWT_SECRET="…" python "E:/SPENCER V1/backend/test_auth.py"` → `RESULT: ALL CHECKS PASSED`.
- **`backend/test_tenant_isolation.py`** — **22/22 PASS** on real Redis + a fresh throwaway DuckDB.
  Same throwaway-CWD invocation. Confirms B→404 everywhere (incl. `/ask` with no LLM reached),
  no-token→401, unknown-UUID→404, admin 403/401/200, and `delete_session` returning
  `{tables_dropped:1, dir_removed:true, redis_keys_deleted:2}` then 404 on re-delete.
- Both tests run from a throwaway CWD so `duckdb.connect("spencer.db")` opens a fresh unlocked DB
  and coexists with the live uvicorn (single write lock). Module-scope `TestClient` does not fire
  startup, so `init_db()` is called explicitly.
- **Frontend:** `cd frontend && npx vue-tsc --noEmit` → **exit 0** (strict build clean).
- **Live browser proof** (Vite :5173 + uvicorn :8000 + real Redis :6379): full 2-user run passed
  end-to-end — guard redirect, register A, A upload → grid over guarded routes (Bearer attaches),
  sign-out clears auth+session, register B sees an empty workspace (no A data), B → 404 on A's UUID,
  and a corrupted persisted token on reload self-heals to `/login` with storage cleared. Three
  console errors observed (one 404, two 401) are exactly the deliberately-triggered failures from
  the isolation/expiry checks — no unexpected errors.

## Non-goals this wave (documented follow-ons)
Email verification / password reset / OAuth; per-user LLM-key quota attribution (the key pool
stays global); billing; **server-side** sync of query history / saved queries / dashboards
(still client-side, now per-user-namespaced); indefinite retention + per-user storage quotas;
and the **deploy packaging** itself (Docker/Compose/Caddy arm64 images + a Postgres service for
the Oracle Ampere VM — this wave only keeps config deploy-ready).

## Definition of Done
Real accounts + strict per-user isolation across the whole `/sessions` surface, enforced by a
`get_current_user` → `require_session_owner` dependency chain that 404s (never 403s) on
foreign/unknown sessions and 401s before authZ; admin routes gated; a working delete-my-dataset;
identity in a dialect-neutral SQLAlchemy store (SQLite dev / Postgres prod). Backend 18/18 + 22/22
green on real infra. Frontend auth shell + strict build + live 2-user proof to follow. Left in
`tasks/active/` for the single sign-off. **Not self-closed.**

## Self-review (severity-graded)
Scale: 🔴 Critical (blocks sign-off) · 🟠 High (must fix before a *public* deploy) · 🟡 Medium
(should fix soon) · 🟢 Low (minor / edge) · ℹ️ Note (by-design tradeoff, on record).

**Verdict:** no 🔴 — the wave's contract (real accounts + strict per-user isolation, 404-never-403,
401-before-authZ, admin gating, delete-my-dataset) is implemented and proven on real infra
(18/18 + 22/22 + full browser 2-user run). The two 🟠 items are **not** defects in the isolation
logic; they are **deploy-hardening gates** that land naturally in the deferred Docker/Compose/Caddy
phase. Listed so the sign-off is fully informed.

- 🟠 **JWT dev-fallback still boots in prod.** `config.py:88-99` — if `SPENCER_JWT_SECRET` is unset
  the app logs a loud warning but **runs anyway** with a fixed, repo-shipped HS256 key. On a public
  deploy that forgets the env var, that key is public → anyone can forge a token for any user id
  (ids are sequential integers), a full auth bypass. `is_admin` is read from the DB (not the token),
  so admin isn't directly forgeable, but user impersonation is total.
  *Mitigation in place:* the loud warning + a ready `JWT_SECRET_IS_DEV_FALLBACK` flag.
  *Recommend (deploy phase):* fail-fast at startup when `JWT_SECRET_IS_DEV_FALLBACK` **and** a prod
  indicator (e.g. `SPENCER_ENV=production`) are both set. One `if` in `startup_event`.
- 🟠 **Open registration + global LLM key pool.** `ALLOW_REGISTRATION` defaults true and the Gemini
  key pool (`llm_key_pool.py`) is global/unattributed (a documented non-goal). A public deploy with
  open registration therefore lets any anonymous registrant consume the shared *paid* LLM quota.
  *Mitigation in place:* set `SPENCER_ALLOW_REGISTRATION=false` (lock to provisioned accounts) and/or
  `SPENCER_LLM_DAILY_LIMIT_PER_KEY`. *Recommend:* ship the public deploy with registration closed
  until per-user quota attribution (the named follow-on) exists.
- 🟡 **No rate-limit on `/auth/login`.** Nothing throttles credential-stuffing/brute-force. The generic
  same-message error avoids enumeration, but online guessing is unbounded. *Recommend:* a per-IP
  limiter (or fail2ban at Caddy) in the deploy phase.
- 🟡 **Stateless JWT — no server-side revocation.** Logout is client-only; a leaked token stays valid
  until expiry (default 7 days). Standard bearer-token tradeoff, but the window is long.
  *Recommend:* consider a shorter TTL + refresh, or a Redis denylist, if tokens are ever at risk.
- 🟢 **bcrypt 72-byte slice.** Two ≥72-**byte** passwords sharing a 72-byte prefix collide. Only
  reachable with multibyte (non-ASCII) passwords, since `RegisterRequest.password` caps at 72 *chars*;
  matches bcrypt's own historical truncation. Documented in the DEVIATION note. Accept.
- 🟢 **create_session orphan window.** If `record_dataset` fails *after* the DuckDB table is
  registered, the table is unowned (404s for everyone) until the TTL sweeper reclaims it. Rare (app-DB
  write failure), self-healing via the owned-TTL sweep, no data leak. Accept / could wrap in a txn.
- 🟢 **Frontend redirect guard misses `/\`.** `AuthView.vue:49` rejects `//…` but not `/\evil.com`.
  vue-router resolves the value as an in-app path (it's `router.replace`, not a `location` assignment),
  so there's no actual cross-origin navigation — but the guard is narrower than ideal. *Recommend:*
  also reject a leading `/\`.
- ℹ️ **Per-user localStorage namespacing is convenience-only.** The `:${userId}` suffix stops one
  logged-in user from seeing another's history/dashboards in a shared browser; it is **not** at-rest
  encryption — anyone with device access can read localStorage. Server-side ownership is the real
  authority; this only scopes client convenience state. By design.
- ℹ️ **`get_current_user` hits the app DB every guarded request.** Fine at SQLite/dev scale and for
  Postgres at expected load; cacheable later if it ever shows up in a profile. By design.
- ℹ️ **`@app.on_event("startup")`** is FastAPI-deprecated in favor of `lifespan`. Pre-existing
  (TASK-013); I only added `init_db()` to it. Out of scope here; worth a sweep later.

**CORS checked, not a finding:** `main.py:76-93` uses an explicit origin allowlist
(`SPENCER_CORS_ORIGINS`, default localhost:5173) with a comment explaining why `*`+credentials is
invalid — already correct; a deploy just points it at the real origin.
