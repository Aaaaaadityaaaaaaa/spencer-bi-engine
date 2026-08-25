# Spencer — SaaS-Readiness Gaps & Hardening Register

Findings from the full-project SaaS-readiness audit on **2026-08-25** (5 parallel review
tracks: security & multi-tenancy, infra & deploy, architecture & scale, frontend & auth,
product-completeness). This is the single source of truth for **"what stands between us and
safely charging strangers."** Companion to [`BACKLOG.md`](BACKLOG.md) (which tracks *features*);
this file tracks *readiness / hardening*. Nothing here is self-closed — sign-off is the user's.

**Verdict:** _deployable, not yet sellable._ The multi-tenant model is real and boots safely,
but two verified holes break the isolation promise and must close before any real user data
lands. Fine today for a **closed/invite pilot with disposable data**; ~one hardening wave from
public sale.

**Severity:** 🔴 critical · 🟠 high · 🟡 medium · 🟢 low · ℹ️ note
**Status:** ⬜ open · 🚧 in progress · ⏳ awaiting sign-off · ✅ done

---

## When do we fix these? (fix-timing policy)

Not "all at the end," and not "everything before the next step." Fix **by risk tier**, as
**discrete, self-contained tasks** (never bundle hardening into an unrelated feature commit):

| Tier | What | When | Why then |
|------|------|------|----------|
| **0 — Criticals** | Security holes, data-loss/-corruption bugs | **Immediately. Before anything else, including the pilot.** Never defer. | They compound and they breach/lose real data. Cheap now, catastrophic later. |
| **1 — Pre-pilot hardening** | Abuse/cost controls (quota, rate-limit) | **Before the invite pilot goes out.** | The moment a non-you human can hit it, these gate blast radius (wallet + brute-force). |
| **2 — Foundational infra** | Migrations, backups, durability | **Early — before real data accrues.** | Exponentially more expensive to retrofit *after* you have production data to preserve. |
| **3 — Product-completeness** | Billing, password reset, observability polish | **Just-in-time, milestone-gated.** | No value until the milestone needs them (billing before you charge; reset before public signup). Building early = waste. |

**Rule of thumb:** a **bug** (Tier 0/2) is fixed the moment it's found or on a tight leash;
a **gap** (Tier 1/3) is scheduled against the milestone that needs it. Keep each fix its own
reviewable task so it stays revertible and doesn't stall feature work.

---

## Tier 0 — Criticals (verified in source; block real data)

| # | Sev | Finding | Location | Fix | Status |
|---|-----|---------|----------|-----|--------|
| S-1 | 🔴 | **Cross-tenant + filesystem read via `/execute`.** The editor SQL validator blocks only *write* nodes — **no table allowlist, no function allowlist** — and there is **no `enable_external_access=false`** anywhere in the backend. So any authenticated user, from their own session URL, can `SELECT * FROM t_<other-uuid>_data`, or `read_csv_auto('/app/uploads/<other-uuid>/…')` / `read_blob('backend/spencer_app.db')` to read other tenants' raw uploads and (on the SQLite path) every user's email + bcrypt hash. `run_sandboxed`'s rollback undoes *writes* only — a pure read still returns rows. (Distinct from the **transform** path, which *is* fail-closed with a function allowlist — that praise does not cover `/execute`.) | [`sql_validator.py:22-26`](../backend/services/sql_validator.py) · [`ai.py:200-206`](../backend/routers/ai.py) | **TASK-029:** per-session scope gate `scope_violation()` in the validator (own-table allowlist + IO-function denylist + structural table-function block), called in `/execute` after `validate()`. Engine-level `enable_external_access=false` was **not** viable — the shared single connection also runs ingestion's `read_csv_auto`. | ⏳ TASK-029 |
| S-2 | 🔴 | **A Redis hiccup on restart can delete all tenant data.** Three facts compound: (a) `RedisManager` **silently** falls back to an empty in-memory fakeredis if Redis isn't reachable in 1s (just a `logger.warning`); (b) the sweeper DROPs a session's tables + `rmtree`s its uploads purely because its `session:{uuid}` marker is **absent**; (c) `sweep_loop()` runs `sweep()` **immediately** on boot. So: restart while Redis is slow → fakeredis → no markers → first sweep wipes every dataset older than the grace window, while Postgres still lists those users as owners. The grace window only protects in-flight uploads, not established tenants. | [`redis_manager.py:56-59`](../backend/services/redis_manager.py) · [`cleanup_service.py:93,104,110,233`](../backend/services/cleanup_service.py) · [`main.py:180`](../backend/main.py) | **TASK-029:** prod `RedisManager` **fails hard** (no fakeredis fallback); `sweep()` **refuses** when backend≠real-redis; `sweep_loop()` no longer sweeps on boot (first sweep after one 30-min interval). *Residual: empty **real** Redis → see D-2.* | ⏳ TASK-029 |

> **S-1 and S-2 are both a few lines each. Recommend doing them as one small hardening task before Wave 6b or any pilot.**  → **Done as [TASK-029](active/TASK-029.md), ⏳ awaiting sign-off** (both proven green; residual empty-real-Redis case split out as D-2).

---

## Tier 1 — Pre-pilot hardening (before a non-you human can hit it)

| # | Sev | Finding | Location | Fix | Status |
|---|-----|---------|----------|-----|--------|
| S-3 | 🟠 | **No per-user LLM quota/attribution.** The API-key pool is global; `_call_llm` has no account id. One pilot user can drain the whole Gemini quota (this is exactly why registration ships closed). | [`ai_service.py:442`](../backend/services/ai_service.py) | Thread the account id into the LLM path; meter + cap per-user calls/tokens. | ⬜ |
| S-4 | 🟠 | **No rate limiting** on auth or AI endpoints → brute-force + cost-bomb exposure. | routers (`auth.py`, `ai.py`) | Add per-IP/per-user rate limits (e.g. slowapi) on login/register and AI routes. | ⬜ |
| S-5 | 🟡 | **JWT is stateless with no server-side revocation** — a logout or compromised token stays valid until expiry. | [`auth_service.py`](../backend/services/auth_service.py) | Add a token version / denylist, or short expiry + refresh. | ⬜ |
| S-6 | 🟡 | **Token stored in `localStorage`** → readable by any XSS. | [`useAuth.ts:26`](../frontend/src/composables/useAuth.ts) | Accept as MVP risk, or move to httpOnly cookie + CSRF. Revisit with S-5. | ⬜ |
| D-1 | 🟡 | **`schema:{uuid}` catalog lives only in Redis with no TTL** — a Redis flush strands data as 404s (the only map to physical tables is gone) even without deletion. | [`redis_manager.py`](../backend/services/redis_manager.py) | Mirror the catalog into the durable app DB (Postgres), or rebuild it from the DuckDB catalog on boot. | ⬜ |
| D-2 | 🟠 | **Empty *real* Redis still risks a reap (residual of S-2).** TASK-029 closed the silent-fallback restart race, but if Redis stays connected (`backend == "redis"`) yet its keys are lost (flush / eviction / non-persistent restart), the sweep guard passes and "absent marker = dead" would still reap live, owned sessions. The likelihood is lower than the fixed race, but the blast radius is identical. | [`cleanup_service.py:106`](../backend/services/cleanup_service.py) · [`redis_manager.py`](../backend/services/redis_manager.py) | **Ownership-aware sweep:** cross-check the `datasets` table — a session with an owner row but no marker is *idle*, not *dead* (never reaped, or only after a much longer owned-TTL). And/or enable Redis persistence (AOF). Pairs naturally with D-1 (durable catalog). | ⬜ |

---

## Tier 2 — Foundational infra (do before real data accrues)

| # | Sev | Finding | Location | Fix | Status |
|---|-----|---------|----------|-----|--------|
| I-1 | 🟠 | **No schema migrations (Alembic).** Table changes are `create_all` only — no forward path once prod has rows. | [`app_db.py`](../backend/services/app_db.py) | Add Alembic; baseline the current schema; migrate forward from there. | ⬜ |
| I-2 | 🟠 | **No DB backups.** Postgres has no backup/restore story documented or scripted. | `docker-compose.yml` / `DEPLOY.md` | Add a `pg_dump` cron (or managed snapshot) + a documented restore. | ⬜ |
| A-1 | 🟠 | **Single DuckDB connection + single-writer file is the real scaling ceiling** — one box only, no horizontal scale. (On record since `PROJECT.md`; not a regression.) | [`duckdb_manager.py:9`](../backend/services/duckdb_manager.py) | Accept for pilot. True scale = re-architect analytical layer (MotherDuck/Postgres/ClickHouse) — out of scope until it hurts. | ⬜ |
| A-2 | 🟡 | **Synchronous file I/O on the event loop** in `_persist_upload` — a large upload stalls all requests. | [`session.py:59-86`](../backend/routers/session.py) | Move blocking read/write to a threadpool (`run_in_threadpool` / `execute_async`). | ⬜ |
| A-3 | 🟡 | **Non-atomic `DROP`+`RENAME`** in transform apply — a crash mid-swap loses the table. | [`transform_service.py:145-146`](../backend/services/transform_service.py) | Wrap the swap in a single transaction, or swap-then-drop so a crash leaves the old table intact. | ⬜ |
| I-3 | 🟢 | **`web` starts before `backend` is healthy** in compose (startup race → transient 502s on deploy). | `docker-compose.yml` | Add `depends_on: condition: service_healthy` + a backend healthcheck. | ⬜ |

---

## Tier 3 — Product-completeness (milestone-gated; before you charge)

| # | Sev | Finding | Fix | Status |
|---|-----|---------|-----|--------|
| P-1 | 🟠 | **No billing / plans / usage metering.** | Add billing (Stripe) + plan gating once pricing exists. | ⬜ |
| P-2 | 🟡 | **No password reset or email verification.** | Required before *public* self-serve signup (not needed for invite pilot). | ⬜ |
| P-3 | 🟡 | **No observability** — no Sentry, structured logs, or metrics. | Add error tracking + request/latency metrics before scaling users. | ⬜ |
| P-4 | 🟢 | **Register tab still shipped in UI** though registration defaults closed. | Hide the tab when `ALLOW_REGISTRATION=false`, or gate behind invite. | ⬜ |

---

## Already right — do NOT re-flag (credit + regression guard)

- ✅ **Real tenant isolation:** 404-not-403 on foreign sessions via a clean `Depends()` gate chain ([`deps.py`](../backend/deps.py)).
- ✅ **Prod JWT fail-fast:** backend refuses to boot on the forgeable dev key (`config.assert_production_safety`; proven 4/4 in [`test_deploy_safety.py`](../backend/test_deploy_safety.py)).
- ✅ **Registration ships CLOSED** by default, with the reasoning documented ([`.env.production.example:18-21`](../.env.production.example)).
- ✅ **Identity DB gitignored:** `spencer_app.db` (emails + bcrypt hashes) can't be committed ([`.gitignore:23-27`](../.gitignore)).
- ✅ **AI transform path fails closed:** strict function allowlist + unconditional rollback ([`transform_service.py:478`](../backend/services/transform_service.py)).
- ✅ **Same-origin Caddy** design avoids a whole class of CORS bugs in prod.
- ✅ **setuptools flat-layout** image-build blocker fixed ([`pyproject.toml`](../backend/pyproject.toml)).

---

## Recommended order

1. **S-1 + S-2** (one small task) — before Wave 6b or any pilot. _Highest severity: live cross-tenant breach + total-data-loss._ → **[TASK-029](active/TASK-029.md) ⏳ awaiting sign-off.**
2. **S-3 + S-4** — before the invite pilot (quota + rate limiting).
3. **I-1 + I-2** — soon, while data is still disposable (migrations + backups).
4. Everything else — milestone-gated against "going public / charging."
