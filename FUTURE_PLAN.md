# Spencer — Future Improvement Plan

**Generated:** 2026-08-29  
**Basis:** Full codebase audit (backend routers/services, frontend views, tasks/BACKLOG.md, tasks/SAAS_READINESS.md, git history)

---

## Executive Summary

Spencer is a **single-machine, upload-only BI tool** with a real security architecture (3-layer AI-SQL defense). The codebase is **far ahead of the `.ai/*.md` docs** — multi-tenancy/auth, AI NL→SQL, Wave-4 AI assists, export, materialize, and Tier-0 SaaS fixes are all implemented. What's missing is polish, the feature backlog, and SaaS hardening.

**Current state:** Deployable for a closed pilot; not sellable. ~27 features with remaining work (BACKLOG.md) + 11 SaaS gaps (SAAS_READINESS.md).

---

## Phase 0 — Documentation Sync (1 day, do first)

| Task | Why |
|------|-----|
| Rewrite `.ai/CURRENT_STATE.md` to match actual code (TASK-027 auth, TASK-012 AI assists, TASK-029 S-1/S-2, etc.) | All downstream planning assumes truth |
| Update `.ai/ARCHITECTURE.md` — add auth/ownership, Wave-4 AI assists, export, materialize | Reflects reality |
| Sync `.ai/DECISIONS.md` with implemented ADRs (014–016+) | Decision log is stale |
| Delete or archive stale `tasks/completed/TASK-001-FIX-02.md` etc. if superseded | Reduces noise |

**Output:** Single source of truth for any future contributor.

---

## Phase 1 — Critical SaaS Hardening (Tier 0/1 from SAAS_READINESS.md)

*Do before any pilot with real users.*

| # | Task | Effort | Notes |
|---|------|--------|-------|
| **S-3** | Per-user LLM quota/attribution (thread `user_id` into `ai_service._call_llm`, meter in `llm_key_pool` or new user-key pool) | M | Blocks cost explosions |
| **S-4** | Rate limiting on `/auth/*` and `/sessions/*/ask|execute|sql/assist` (slowapi / Redis token bucket) | S | Prevents brute-force + cost bombs |
| **S-5** | JWT revocation (token version in `users` table + short expiry + refresh tokens) | M | Required for real logout/compromise response |
| **D-1** | Mirror `schema:{uuid}` catalog to `app_db` (Postgres) so Redis flush doesn't strand data | M | Durable catalog for production |
| **D-2** | Ownership-aware sweep: cross-check `datasets` table before reaping (never reap owned sessions) | S | Pairs with D-1 |

**Sequencing:** S-3 + S-4 together (one PR). S-5 separate. D-1 + D-2 together.

---

## Phase 2 — Foundational Infra (Tier 2)

*Do before real data accrues (exponentially more expensive later).*

| # | Task | Effort | Notes |
|---|------|--------|-------|
| **I-1** | Add Alembic migrations (baseline current `users`/`datasets` schema) | S | One-time |
| **I-2** | Document + script `pg_dump` cron + restore procedure | S | Can use docker-compose sidecar |
| **A-2** | Move `_persist_upload` blocking I/O to threadpool (`run_in_threadpool`) | S | Prevents event-loop stall on large uploads |
| **A-3** | Atomic transform swap: wrap `DROP`+`RENAME` in single transaction or swap-then-drop | S | Prevents table loss on crash |
| **I-3** | Docker compose: `depends_on: condition: service_healthy` + backend `/health` that verifies Redis + DuckDB | S | Eliminates startup race 502s |

---

## Phase 3 — Feature Waves (from BACKLOG.md, highest value/effort first)

**Each wave = build cluster → self-review with severity grades → one user sign-off.**

### Wave 1 — Finish Table Toolkit (Backend: 1 transform-op branch; Frontend: 1 OpDialog block)
Unlocks BACKLOG #3, #4 (reformat/extract), #5 (regex/pad/strip), #6 (binning).  
**Foundation:** `transform_service._compile_structured` already has allowlisted `SPLIT_PART`, `REGEXP_EXTRACT`, `REGEXP_REPLACE`, `LPAD/RPAD`, `CASE`, `DATE_PART`, `STRFTIME`.  
**Deliverables:** New transform ops + preview/apply/undo/redo + toolbar buttons.

### Wave 2 — Round-Trip Data (Formats + Export)
- **#31** Ingestion: widen `SPENCER_UPLOAD_ALLOWED_EXT` (already `csv,tsv,parquet,json,xlsx` — just fix the Parquet bug where UI advertises but backend rejects)
- **#10** Export cleaned data: add Excel/Parquet/JSON writers to `export_service` (shared with #24)
- **#24** Export query results: same writers, add clipboard/CSV/Excel/multi-tab

**Foundation:** Single `export_service.encode(format)` used by both.

### Wave 3 — In-Grid Power (Frontend-only)
**#8** Multi-sort, drag-reorder, pin/freeze, hide, search, heatmap, inline edit.  
Backend already supports multi-sort + search + heatmap via `/data`; only hide/show exists in `DataGrid.vue`. Pure Vue/TanStack work.

### Wave 4 — AI Batch (6 features, 1 provider pattern)
Reuses `ai_service._call_llm` + LiteLLM routing:  
**#22** Explain/fix/optimize SQL (already have `sql_assist` endpoint, need UI wiring)  
**#30** Chart-type recommendation (endpoint exists, need UI)  
**#26** Auto-EDA on upload (5 questions, one-click run)  
**#29** Data storytelling (LLM narrative of dataset)  
**#18** Explain chart (endpoint exists, need UI)  
**#21** Conversational refinement ("now group by month") — add turn memory to `/ask` history

### Wave 5 — Canvas Chart Types
**#11** Extend `AggregateRequest/Response` to 2-D (`keys[]/values[]` → `series[]` for scatter/stacked/heatmap/box).  
ECharts series config already modular; just needs backend 2-D aggregate contract.

### Wave 6 — Dashboard Persistence + Polish
**#15** Save/load named dashboards (new persistence store → Postgres)  
**#16** Dashboard templates auto-built from schema  
**#13** Global date-range picker + drill-down  
**#14** KPI deltas (sparkline, ▲% vs prior, targets)  
**#17** Export dashboard PNG/PDF; fullscreen

**Foundation:** Persistence store unlocks #15→#16, #13, #14, #17.

### Wave 7 — Cross-Pillar Connectors
**#32** Multi-table switcher UI (cheapest: backend done, only frontend switcher)  
**#23** Result → Canvas tile / Result → new working table (materialize path exists, need UX)  
**#25** Parameterized queries (`:param`/`{{var}}` in SQL editor)  
**#34** Shareable read-only dashboard snapshot  
**#33** Session export/import

---

## Phase 4 — Product-Completeness (Tier 3, milestone-gated)

| Task | Trigger |
|------|---------|
| **P-1** Billing/Stripe + plan gating | Before charging |
| **P-2** Password reset + email verification | Before public signup |
| **P-3** Observability (Sentry, structured logs, request/latency metrics) | Before scaling users |
| **P-4** Hide Register tab when `ALLOW_REGISTRATION=false` | Trivial |

---

## Architecture Guardrails (Non-Negotiable)

1. **Single DuckDB file + single writer** — no horizontal scale; accept it.
2. **AI SQL never executes without:** (a) `sqlglot` validation, (b) `run_sandboxed` rollback, (c) human Review Gate.
3. **No user string interpolated into SQL** — bound params + quote-escaped identifiers everywhere (ADR-012).
4. **Fail-closed defaults** — security stubs return `False`/`NotImplementedError`, never `True`.
5. **Idempotent, self-describing tests** — every proof runs twice, prints `REDIS BACKEND IN USE: redis`.
6. **No silent fallbacks** — `redis_manager.backend` exposed; prod fails hard on missing Redis.
6. **Config in one place** — `config.py` only; no inline `os.getenv` in new code.

---

## Suggested Next 3 Steps (Owner Action)

1. **Sign off pending tasks** (`tasks/active/` empty but `BACKLOG.md` lists 8 awaiting sign-off: TASK-008,009,010,012,013,015,016,017). Clearing review debt unblocks Wave 1.
2. **Pick Wave 1 or #32 (multi-table switcher)** — switcher is the single cheapest win (backend done, ~2h frontend).
3. **Decide pilot vs. public timeline** — if pilot soon, do Phase 1 (S-3, S-4) immediately; if months away, Phase 1 can wait.

---

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Redis wipe on reboot loses all sessions | High (portable Redis) | Data loss for pilot users | D-2 (ownership-aware sweep) + enable Redis AOF |
| LLM cost runaway | Medium | Budget blow | S-3 per-user quota + S-4 rate limits |
| `spencer.db` corruption on crash | Low | Full data loss | A-3 atomic transform + `CHECKPOINT` after sweep |
| Schema drift between code + `app_db` | Medium | Migration pain | I-1 Alembic now, before any schema change |

---

## Quick Wins (≤1 day each)

- [ ] Multi-table switcher UI (#32)
- [ ] Fix Parquet upload bug (#31)
- [ ] Add `blacklist`/`whitelist` for OpenRouter models in config (already supported)
- [ ] `/health` endpoint: verify Redis + DuckDB reachability (currently returns `{"status":"ok"}` only)
- [ ] Hide Register tab when `ALLOW_REGISTRATION=false` (P-4)

---

*Plan is a living document — update after each wave sign-off. All tasks tracked in `tasks/` with attached proofs per AGENTS.md.*