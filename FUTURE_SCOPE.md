# Spencer — Future Scope

> **A living roadmap draft.** This is the forward-looking companion to the two working
> registers in [`tasks/`](tasks/): [`BACKLOG.md`](tasks/BACKLOG.md) (features) and
> [`SAAS_READINESS.md`](tasks/SAAS_READINESS.md) (hardening). Both of those were last
> *status-verified* on 2026-08-22 / 2026-08-25 respectively and their status columns have
> since been overtaken by delivery. This document reconciles them against what has actually
> shipped as of **2026-08-26**, then lays out — in detail — everything still ahead: the
> remaining product features, the path from "deployable" to "sellable," and the larger v2
> bets beyond the current 34-feature list.
>
> Drafted for discussion. Nothing here is a commitment or a sign-off; sequencing is a
> proposal with a clear recommendation, and the final call is yours.

---

## 0. How to read this document

- **Part I — Finish the product.** The features still open on the 34-item backlog.
- **Part II — The road to "sellable."** The SaaS-readiness hardening, by risk tier.
- **Part III — Beyond the backlog.** The v2 / competitive bets that aren't on the 34-item
  list yet but define where Spencer goes after it's "complete + safe."
- **Part IV — Architecture evolution & cross-cutting work.** The scaling ceiling, testing,
  observability, and developer experience.
- **Part V — Recommended sequencing & open decisions.**
- **Appendix — Status reconciliation** (feature-by-feature, with a confidence flag on each,
  since the source docs are stale).

**Legend** (matches the working docs): ✅ built · 🟡 partial · ⬜ not built · ⏳ awaiting
sign-off · 🔴🟠🟡🟢 severity · ⚠ *my status read needs a fresh code re-verification before
it's trusted* (the source docs predate several shipped waves).

---

## 1. Where Spencer is today (baseline, reconciled)

Spencer is a three-pillar, single-page analytics workbench: **upload a messy dataset →
clean it → visualise it → query it in SQL/English**, multi-tenant, and packaged to deploy.

The product is organised as three workspaces, matching the product vision:

- **Table** — the data-prep surface. Auto-shows the full table after upload; column profiler,
  a whole-table data-quality scanner with one-click fixes, an Ibis-compiled transform engine
  (cast / normalize / split / bin / date-parts / fill-down / impute / dedupe / filter /
  in-cell edit / **make-positive**), undo/redo with server snapshots, and a multi-table
  switcher.
- **Canvas** — a Power BI-style dashboard: a movable/resizable tile grid across multiple
  pages, KPI cards with delta-vs-target + sparklines, ~9 chart types on a 2-D aggregate
  contract, cross-filtering, per-tile presentation controls, named save/load slots,
  live auto-persist, and PNG/PDF export + a present/fullscreen mode.
- **Query Engine** — a MySQL-Workbench-style SQL editor (schema-aware autocomplete, clickable
  column pills, query history) fused with an AI layer (natural-language → SQL, a
  self-correction loop, and a fail-closed sandboxed `/execute`), plus the ability to send a
  result to a new working table or to a Canvas tile.

Underneath: FastAPI + on-disk DuckDB (via a single connection) + Redis for session/schema
state, an **Ibis-as-compiler** transform path (ADR-012), JWT auth with real per-tenant
isolation (ADR-027-era work), and a Docker/Caddy same-origin deployment package.

### 1.1 What has actually shipped (reconciling the stale tallies)

The [`BACKLOG.md`](tasks/BACKLOG.md) tally reads *"7 built · 10 partial · 17 not built"* —
but that snapshot is from **2026-08-22**. Since then the task queue has been cleared through
**TASK-039**, delivering essentially all of Waves 1–6 and two of Wave 7's five connectors.
The real picture:

| Wave | Scope | Status (2026-08-26) |
|------|-------|---------------------|
| **1 — Table toolkit** | split/extract, binning, date-parts/reformat, regex/pad/strip, fill-down/outlier (#3–#7) | ✅ shipped (TASK-018, TASK-019) |
| **2 — Round-trip data** | upload formats + Parquet fix, export cleaned, export results (#31, #10, #24) | ✅ shipped ⚠ *(re-verify #24 multi-tab / clipboard)* |
| **3 — In-grid power** | multi-sort, reorder, pin, hide, search, inline edit (#8) | ✅ shipped (TASK-022) + extended by TASK-041 (in-cell edit) |
| **4 — AI batch** | explain/optimize SQL, chart rec, auto-EDA, storytelling, explain-chart, conversational (#22, #30, #26, #29, #18, #21) | ✅ shipped as a batch (TASK-023) ⚠ *per-feature completeness needs a fresh audit* |
| **5 — Canvas chart types** | 2-D aggregate contract + new chart types (#11) | ✅ shipped (TASK-025) |
| **6 — Dashboard persistence + polish** | drag/resize grid, save/load, KPI deltas/sparklines, export/present (#15, #14, #17) | ✅ shipped (TASK-030–037) — **except** #16 templates and #13 date-range picker (still 🟡) |
| **7 — Cross-pillar connectors** | switcher, result→table/tile, params, snapshot, session I/O (#32, #23, #25, #34, #33) | 🟡 **2 of 5**: #32 signed off (TASK-039); #23 built (TASK-040, awaiting sign-off). #25/#34/#33 open. |

**Bottom line:** the 34-feature list is *far* more complete than either working doc reflects.
The genuinely-remaining product work is small and specific (§2), and the larger lift now is
**readiness**, not features.

### 1.2 Open loops right now

- **Three tasks await your `mv` sign-off** (built + verified, left in `tasks/active/`, not
  self-closed): **TASK-040** (#23 materialize result→table/Canvas), **TASK-041** (10-item
  data-grid/quality/chart batch), **TASK-042** (3-item data-prep batch).
- **Uncommitted working tree.** Commit tip `2a63d7f` is **ahead of `origin/master` by 1
  (not pushed)**; the working tree additionally carries all of TASK-040/041/042's code plus
  the TASK-038/039 sign-off renames. A push has not been requested.
- **The two working docs are stale.** Their status columns predate Waves 1–6; a
  reconciliation pass (§2.5) is itself a recommended near-term action.

### 1.3 Readiness verdict (from the audit)

> *"Deployable, not yet sellable."* Fine today for a **closed/invite pilot with disposable
> data**; roughly one hardening wave from public sale.

That audit named two Tier-0 criticals (**S-1** cross-tenant `/execute` read, **S-2**
Redis-restart data loss). **Both were fixed in TASK-029 and shipped in commit `2a63d7f`
("harden /execute + Redis (S-1/S-2)").** [`SAAS_READINESS.md`](tasks/SAAS_READINESS.md) still
shows them as `⏳ TASK-029` — that status is stale; the code is in. What remains is the
residual **D-2** (ownership-aware sweep) plus all of Tiers 1–3 (§3).

---

## 2. Part I — Finish the product (remaining features)

Five discrete pieces of feature work remain on the 34-item list. All ride on foundations that
are **already built** (§4.1), so each is small.

### 2.1 #25 — Parameterized queries *(Query Engine)*  ⬜

**What:** let a saved/typed query carry run-time variables — `:param` or `{{var}}` — that the
user fills in before running, instead of editing raw SQL each time. Today SQL is sent verbatim.

**Why it matters:** turns one-off queries into reusable, shareable reports ("sales for
`{{region}}` in `{{month}}`"), and is a prerequisite for a clean shareable-snapshot story (#34)
and for any "report template" concept later.

**Approach (small, security-first):**
- Parse `:name` / `{{name}}` placeholders client-side, render an input per variable, and
  substitute **as bound values, never string-concatenated SQL**.
- The substitution must run through the **same fail-closed validator** that `/execute` uses
  (`sql_validator.validate` + `scope_violation`) *after* binding — a parameter value can never
  introduce a new table reference or an IO function. Values are typed literals, not SQL text.
- Persist variable definitions alongside the saved query (localStorage today; server-side once
  #33/#34 add a durable store).

**Risk:** low, if and only if params are bound values. The one trap is letting a param inject
identifiers (table/column names) — disallow that in v1, or validate against the live schema
allowlist exactly like the existing scope gate.

**Effort:** **S** (one Query Engine feature; reuses the existing validator and history store).

### 2.2 #34 — Shareable read-only dashboard snapshot *(Canvas)*  ⬜

**What:** a "Share" action that produces a read-only, link-addressable snapshot of a dashboard
(a specific Canvas page or slot) that someone can open without editing.

**Why it matters:** this is the first genuinely *outbound* feature — the first time Spencer
produces something a non-user consumes. It's the natural "so what do I do with my dashboard"
payoff after all the Canvas work, and a strong demo/portfolio moment.

**Approach:**
- Serialize the dashboard definition (tile layout + each tile's aggregate request + chart
  config) into a durable snapshot record keyed by a share id. Reuse **Foundation 6** (the
  save/load persistence store from TASK-034/035) — a snapshot is a frozen, read-only slot.
- A read-only render route that re-runs each tile's aggregate against the **snapshot's**
  data and renders the existing tiles with all editing affordances stripped.
- **This is where the single-user model must be revisited** (the audit flagged exactly this):
  who can open a share link? Options, in order of increasing effort:
  1. **Owner-only re-open** (a saved view, not really "shared") — trivial, but not the feature.
  2. **Unguessable-token public link** (anyone with the URL; data is effectively public) —
     medium effort, the classic "share by link." Needs an explicit product decision because it
     exposes tenant data outside auth.
  3. **Authenticated share to named users** — highest effort; needs a sharing/ACL model.

  **Recommendation:** ship **(2) unguessable-token, read-only, snapshot-frozen data** for v1 —
  it's the feature people mean by "share," and freezing the data into the snapshot avoids
  live cross-tenant reads. Gate it behind an explicit "this link is public" confirmation, and
  make snapshots revocable. Defer (3) to the collaboration bet in Part III.

**Risk:** **medium** — it's the first feature that can leak tenant data by design. The
snapshot-frozen-data approach contains the blast radius; a live-query share would not.

**Effort:** **M** (persistence record + read-only route + the sharing decision above).

### 2.3 #33 — Session export / import *(Data in/out)*  ⬜

**What:** export a whole working session (uploaded tables + transform recipe + Canvas
dashboards + saved queries) to a file, and import it to reconstruct the session elsewhere.
Today there's no serialize/restore and `DELETE` is a stub.

**Why it matters:** portability + durability. It's the backup story for a user's work, the way
to move a session between environments, and the foundation of a "project file" concept. It also
finally implements a real session lifecycle (the stubbed `DELETE`).

**Approach:**
- Define a versioned session-manifest format: table data (Parquet, reusing **Foundation 4**
  export encoders) + the full transform recipe + Canvas/query definitions (reusing
  **Foundation 6**). Note this depends on **Feature #9's** recipe being *fully* replayable —
  BACKLOG flagged #9 as 🟡 ("history stores only `{op, column, ts}`, not full params"). If
  that's still true, promoting the recipe to full-param capture is a prerequisite (or import
  restores data + dashboards but not a replayable recipe).
- Import = create a fresh session, register the tables, replay the recipe, restore dashboards.
- Implement the real `DELETE` as part of the same lifecycle work.

**Risk:** low-to-medium — mostly a data-format + completeness question (does the recipe capture
enough to replay?). No new external surface.

**Effort:** **M** (format design + the possible #9 recipe upgrade + a real delete).

### 2.4 Deferred Wave-6 tail *(Canvas)*

Two Canvas items were consciously deferred and remain 🟡:

- **#16 — Dashboard templates auto-built from schema.**  Today `ChartCanvas.seed()` is one
  generic heuristic. The feature is a *picker* of named starter templates ("Sales overview,"
  "Time-series explorer") chosen by schema shape. Rides Foundation 6 + the existing seed logic.
  **Effort: S–M.** Pairs naturally with the AI "auto starter-dashboard" (#27) — consider
  unifying deterministic templates with an optional LLM-suggested layout.
- **#13 — Global date-range picker + drill-down.**  Drill-down (cross-filter) is built; the
  standalone global **date-range** control is not, and the cross-filter wire is equality-only.
  The picker needs a range predicate in the aggregate filter contract (extend beyond equality).
  **Effort: M** (touches the aggregate filter substrate, so it's slightly more than a widget).

### 2.5 Reconcile the backlog (housekeeping — recommended first)

Because both working docs predate Waves 1–6, several Section-D AI features (#18 explain-chart,
#21 conversational refinement, #22 explain/optimize SQL, #26 auto-EDA, #29 storytelling,
#30 chart recommendation) are marked ⬜ in BACKLOG but were delivered *as a batch* in TASK-023.
Their true per-feature status is **⚠ unverified** — a batch can ship the substrate while
leaving one sub-feature thin.

**Recommended action:** a short reconciliation pass — re-verify each Section-D item against the
code, then update `BACKLOG.md`'s status column and its tally. This is cheap, it's the honest
prerequisite to trusting any "what's left" number, and it may reveal that Part I is even
smaller than it looks (or surface a thin spot worth a quick follow-up). **This is my
recommended #1 near-term action** — verify before you build.

---

## 3. Part II — The road to "sellable" (SaaS-readiness hardening)

This is the larger remaining lift. It follows the audit's **fix-by-risk-tier** policy: fix
criticals immediately, gate the rest against the milestone that needs them, and keep each fix
its own small, revertible task (never bundled into a feature commit).

### 3.1 Tier 0 — Criticals ✅ *(shipped; verify the doc)*

- **S-1 — cross-tenant + filesystem read via `/execute`** → fixed by a per-session scope gate
  (`scope_violation()`: own-table allowlist + IO-function denylist + structural
  table-function block) called in `/execute` after `validate()`.
- **S-2 — Redis-restart data loss** → prod `RedisManager` now fails hard (no silent fakeredis
  fallback), `sweep()` refuses when the backend isn't real Redis, and the boot-time sweep was
  removed.

Both shipped in commit `2a63d7f` via **TASK-029** (now in `completed/`). **Action: update
[`SAAS_READINESS.md`](tasks/SAAS_READINESS.md) to mark S-1/S-2 ✅** — the register still says
`⏳`, which is stale. The residual **D-2** (below) is the one Tier-0-adjacent item still open.

### 3.2 Tier 1 — Pre-pilot hardening ⬜ *(before a non-you human can hit it)*

The gate before the invite pilot. These bound blast radius the moment a stranger can touch the
system — wallet (LLM cost) and brute-force.

| # | Sev | Gap | Fix | Effort |
|---|-----|-----|-----|--------|
| **S-3** | 🟠 | No per-user LLM quota/attribution — one pilot user can drain the whole Gemini quota. (Note: TASK-024 added *server-side key-pool rotation*; that is **not** per-user metering.) | Thread the account id into `_call_llm`; meter + cap per-user calls/tokens. | M |
| **S-4** | 🟠 | No rate limiting on auth/AI endpoints → brute-force + cost-bomb. | Per-IP/per-user limits (e.g. slowapi) on login/register + AI routes. | S |
| **S-5** | 🟡 | Stateless JWT, no server-side revocation — logout/compromise stays valid until expiry. | Token version / denylist, or short expiry + refresh. | M |
| **S-6** | 🟡 | Token in `localStorage` → readable by any XSS. | Accept as MVP risk, or httpOnly cookie + CSRF (revisit with S-5). | M |
| **D-1** | 🟡 | `schema:{uuid}` catalog lives only in Redis with no TTL — a flush strands data as 404s. | Mirror the catalog into Postgres, or rebuild from the DuckDB catalog on boot. | M |
| **D-2** | 🟠 | Empty *real* Redis still risks a reap (residual of S-2): connected but key-less → "absent marker = dead" reaps live sessions. | Ownership-aware sweep: cross-check the `datasets` table (owner row + no marker = *idle*, not *dead*); and/or enable Redis AOF persistence. Pairs with D-1. | M |

**Recommendation:** do **S-4 + S-3 first** (cheapest + highest abuse-surface), then **D-2 + D-1
together** (they share the durable-catalog idea and close the last data-loss residual). S-5/S-6
can ship with, or just after, the pilot — they're real but lower-likelihood for an invite pilot.

### 3.3 Tier 2 — Foundational infra ⬜ *(do before real data accrues)*

Cheap now, exponentially more expensive to retrofit once production has rows to preserve.

| # | Sev | Gap | Fix | Effort |
|---|-----|-----|-----|--------|
| **I-1** | 🟠 | No schema migrations — `create_all` only, no forward path once prod has rows. | Add Alembic; baseline current schema; migrate forward. | M |
| **I-2** | 🟠 | No DB backups — no `pg_dump`/restore story. | `pg_dump` cron (or managed snapshot) + documented restore. | S |
| **A-1** | 🟠 | Single DuckDB connection + single-writer file — the real scaling ceiling (one box, no horizontal scale). | Accept for pilot; true scale = re-architect the analytical layer (see Part IV). | XL (deferred) |
| **A-2** | 🟡 | Synchronous file I/O on the event loop in `_persist_upload` — a big upload stalls all requests. | Move blocking read/write to a threadpool. | S |
| **A-3** | 🟡 | Non-atomic `DROP`+`RENAME` in transform apply — a crash mid-swap loses the table. | Single-transaction swap, or swap-then-drop. | S |
| **I-3** | 🟢 | `web` starts before `backend` is healthy in compose → transient 502s. | `depends_on: condition: service_healthy` + healthcheck. | S |

**Recommendation:** **I-1 + I-2** are the priority (migrations + backups — do them while data
is still disposable). **A-2 + A-3 + I-3** are small, self-contained robustness wins worth
folding in opportunistically. **A-1** is the ceiling, not a bug — deferred to Part IV.

### 3.4 Tier 3 — Product-completeness ⬜ *(milestone-gated; before you charge)*

Build just-in-time — no value until the milestone needs it.

| # | Sev | Gap | When |
|---|-----|-----|------|
| **P-1** | 🟠 | No billing / plans / usage metering. | Before you charge (Stripe + plan gating once pricing exists). |
| **P-2** | 🟡 | No password reset / email verification. | Before *public* self-serve signup (not needed for invite pilot). |
| **P-3** | 🟡 | No observability (Sentry, structured logs, metrics). | Before scaling users. |
| **P-4** | 🟢 | Register tab still shipped though registration defaults closed. | Quick win: hide when `ALLOW_REGISTRATION=false`. |

**Recommendation:** **P-4 now** (one-line polish, removes a confusing dead-end). **P-3
(observability) earlier than its tier suggests** — even a light Sentry + structured request
logs pays for itself the first time a pilot user hits a bug you can't reproduce. P-1/P-2 are
genuinely milestone-gated; don't build them early.

---

## 4. Part III — Beyond the backlog (v2 / competitive bets)

Once the 34 features are complete and the product is safe to sell, these are the bets that
decide whether Spencer is "a nice cleaning tool" or "the thing a team standardises on." None
are committed; they're the strategic menu.

### 4.1 The leverage: six foundations are already built

Every near-term feature is cheap because six reusable substrates already exist (per BACKLOG):
1. **Transform-op plumbing** (schema union → one compile branch → one dialog block).
2. **LiteLLM AI-route pattern** (one route + one `AIService` method).
3. **Ingestion reader** (one branch per format).
4. **Export encoders** (shared Excel/Parquet/JSON writer).
5. **Aggregate 2-D contract** (the chart data contract).
6. **Dashboard/session persistence store**.

New work should keep riding these rather than inventing parallel paths — that discipline is
what kept Waves 1–7 small.

### 4.2 Multi-table joins / a relationship model ⚑ *(revisit ADR-006)*

**Today:** ADR-006 constrains Spencer to single-table — the multi-table switcher (#32) switches
the active table but there are **no joins**, and charts are single-table. This is the single
biggest *capability* ceiling in the product.

**The bet:** a relationship/join model — let users define keys between tables and build
charts/queries across them (the Power BI "model" tab). This is a large architectural decision,
not a feature; it touches the aggregate contract, the transform engine, and the Canvas. It's
also the most-requested capability for anyone with real (relational) data.

**Recommendation:** keep ADR-006 for the pilot, but treat "revisit single-table" as the
headline v2 decision. Scope it explicitly before building — a half-done join model is worse
than none.

### 4.3 Deeper AI: from assistant to analyst

The Foundation-2 AI route makes each of these one route + one method:
- **Agentic multi-step analysis** — "find what's driving the Q3 drop" → the model runs several
  queries, reasons over results, and returns a narrative (builds on #29 storytelling / #26
  auto-EDA).
- **Scheduled / proactive insights** — a daily "what changed in your data" digest.
- **NL → full dashboard** — extend #16/#27 so a prompt lays out a whole Canvas page, not one
  seed chart.
- **Confirm & deepen the Wave-4 batch** — the honest first step (see §2.5): verify #18/#21/#22/
  #26/#29/#30 are each solid, then deepen the thin ones.

### 4.4 More connectors (Data in/out, v2)

Today ingestion is file-upload (CSV shipped; xlsx/JSON/Parquet/TSV per Wave 2). The v2 bet is
**live sources**: a Postgres/MySQL/BigQuery connector, Google Sheets, and a generic REST/API
puller. Each is one ingestion-reader branch conceptually, but connections introduce credential
storage + refresh — a real security surface to design deliberately.

### 4.5 Collaboration & sharing

The snapshot (#34) is the first outbound step. The full bet: real multi-user workspaces —
shared sessions, per-object ACLs, comments/annotations on tiles, and presence. This depends on
revisiting the single-user model (§2.2 option 3) and pairs with the billing/plan work (P-1).

### 4.6 A semantic layer / reusable measures

Let users define named measures ("Net Revenue = …") and dimensions once, reused across every
chart and query. This is what turns ad-hoc dashboards into a governed, consistent model — the
difference between a BI *tool* and a BI *platform*. Larger bet; sits on the aggregate contract.

---

## 5. Part IV — Architecture evolution & cross-cutting work

### 5.1 The scaling ceiling (A-1) and the path through it

The single DuckDB connection + single-writer file means **one box, no horizontal scale**. This
is fine — genuinely fine — for a pilot and for a long time after. But it *is* the ceiling, and
the path through it is a real re-architecture of the analytical layer, not a tweak:
- **MotherDuck** (managed, DuckDB-native — smallest conceptual jump),
- **A dedicated OLAP engine** (ClickHouse) for scale,
- or **per-tenant connection pooling** as an interim step.

**Recommendation:** do **not** pre-build this. Instrument first (P-3), watch where it actually
hurts, and re-architect only when a real workload demands it — "out of scope until it hurts,"
exactly as the audit put it. Flagging it here so it's a *conscious* deferral, not a blind spot.

### 5.2 Testing & CI

There are proof tests for the deploy-safety and S-1/S-2 hardening, and each feature ships with
a live-HTTP verification run — but there's no mention of a standing regression suite or CI
gate. As the surface grows, a **CI pipeline** (build + a core transform/quality/aggregate
regression suite + the existing safety tests) is the cheapest insurance against the review debt
that batching features naturally accrues. **Recommendation: stand up CI around the S-1/S-2 +
deploy-safety tests that already exist, then grow coverage on the transform engine** (the
highest-churn, highest-risk surface).

### 5.3 Observability (P-3, pulled forward)

Restating the Tier-3 note because it's cross-cutting: even minimal Sentry + structured request/
latency logs should land **before** the pilot scales, not after. You cannot fix what a pilot
user hit if you can't see it.

### 5.4 Documentation & DX

`README.md` and `.ai/CURRENT_STATE.md` are owned by you and deliberately untouched by this
process. As features stabilise, the user-facing docs (what each pillar does, the deploy story
in `DEPLOY.md`) are worth a pass — but that's your call and your surface.

---

## 6. Part V — Recommended sequencing

A proposal, milestone-gated, with the reasoning. Reorderable on request.

### Milestone A — "Trustworthy state" (housekeeping, do first)
1. **Reconcile the backlog** (§2.5) — re-verify Section-D, update `BACKLOG.md` + tally.
2. **Update `SAAS_READINESS.md`** — mark S-1/S-2 ✅ (shipped in `2a63d7f`).
3. **Clear the sign-off queue** — TASK-040/041/042 (your `mv` call).

*Why first: everything downstream is planned off these numbers; make them true before building.
Cheap, and it's the honest prerequisite.*

### Milestone B — "Feature-complete" (finish the 34)
4. **#25 parameterized queries** (S) → **#16 templates** (S–M) → **#13 date-range picker** (M)
   → **#33 session I/O** (M) → **#34 shareable snapshot** (M, includes the sharing decision).

*Why this order: cheapest-first, and #34 last because it carries the single-user-model decision
and the first outbound-data risk — best done once the rest is stable.*

### Milestone C — "Pilot-ready" (Tier 1 hardening)
5. **S-4 rate-limit + S-3 per-user quota** (bound abuse/cost) → **D-2 + D-1** (close the last
   data-loss residual + durable catalog) → **S-5/S-6** (token hardening) → **P-4** (hide the
   register tab).

### Milestone D — "Data-durable" (Tier 2 infra)
6. **I-1 migrations + I-2 backups** (while data is still disposable) → **A-2/A-3/I-3** (small
   robustness wins) → **light P-3 observability**.

### Milestone E — "Sellable" (Tier 3, milestone-gated)
7. **P-1 billing** (when pricing exists) → **P-2 password reset** (before public signup) →
   full **P-3 observability**.

### Beyond — v2 bets (Part III), sequenced by strategy, not by this list
Multi-table joins (§4.2) is the headline capability decision; deeper AI (§4.3) is the fastest
differentiation given Foundation 2; the scale re-architecture (§5.1) waits until it hurts.

**My single strongest recommendation:** do **Milestone A this week** regardless of anything
else — the two stale docs and three pending sign-offs are the only things currently making the
project *look* less finished than it is. It's an afternoon of housekeeping that makes every
subsequent plan trustworthy.

---

## 7. Open decisions (need your call)

These genuinely change what gets built and can't be defaulted:

1. **Pilot timing.** Is a closed/invite pilot imminent? If yes, Milestone C jumps ahead of
   finishing the last features (safe-to-invite beats feature-complete). If no, finish the 34
   first. *This single answer reorders everything.*
2. **Share model for #34** (§2.2) — owner-only, unguessable public link, or authenticated ACL?
   (Recommended: unguessable link + frozen snapshot data for v1.)
3. **ADR-006 / multi-table joins** (§4.2) — is cross-table analysis a v2 goal, or is
   single-table the deliberate product boundary? Affects how much of the aggregate contract to
   generalise now vs. later.
4. **How far to push AI** (§4.3) — is Spencer "a clean tool with an AI helper," or "an AI
   analyst with a clean tool underneath"? Determines whether Foundation-2 gets a big v2 invest.
5. **Push cadence** — the local branch is ahead of `origin/master` by 1 and the working tree
   carries three tasks' code; when do you want it committed/pushed? (Not done without your ask.)

---

## Appendix — Status reconciliation (feature-by-feature)

My best current read as of 2026-08-26. ⚠ marks a status that predates a shipped wave and should
be re-verified against code (§2.5) before it's trusted.

| # | Feature | BACKLOG (2026-08-22) | Reconciled read |
|---|---------|----------------------|-----------------|
| 1 | Column profiler | ✅⏳ | ✅ signed off |
| 2 | Data-quality panel | ✅⏳ | ✅ + extended (TASK-041/042: partial-null, inconsistent-values, make-positive, ignore/restore) |
| 3 | Split / merge / extract | ⬜ | ✅ (Wave 1) |
| 4 | Date toolkit | 🟡 | ✅ (Wave 1) ⚠ |
| 5 | Text toolkit | 🟡 | ✅ (Wave 1) + collapse-whitespace (TASK-041) ⚠ |
| 6 | Binning | ⬜ | ✅ (Wave 1) |
| 7 | Fill down / outlier | ⬜ | ✅ (TASK-019) |
| 8 | In-grid power | 🟡 | ✅ (TASK-022) + in-cell edit (TASK-041) ⚠ |
| 9 | Transform recipe (replayable/exportable) | 🟡 | 🟡 **likely still partial** — history may not capture full params; prerequisite for #33 |
| 10 | Export cleaned (CSV/Excel/Parquet/JSON) | 🟡 | ✅ (Wave 2) ⚠ |
| 11 | More chart types | 🟡 | ✅ (TASK-025) |
| 12 | Slicers / cross-filter | ✅⏳ | ✅ (standalone slicer widgets still a nice-to-have) |
| 13 | Global date-range picker + drill-down | 🟡 | 🟡 **open** — drill-down done, picker not |
| 14 | KPI deltas / sparkline / target | ⬜ | ✅ (TASK-030/031) |
| 15 | Drag/resize grid; save/load dashboards | ⬜ | ✅ (TASK-034/035) |
| 16 | Dashboard templates from schema | 🟡 | 🟡 **open** — generic seed only |
| 17 | Export dashboard PNG/PDF; present | 🟡 | ✅ (TASK-032) |
| 18 | Explain this chart (LLM) | ⬜ | ✅ batch (TASK-023) ⚠ verify |
| 19 | Query history | ✅⏳ | ✅ signed off |
| 20 | Schema-aware autocomplete | ✅⏳ | ✅ signed off |
| 21 | Conversational refinement | ⬜ | ✅ batch (TASK-023) ⚠ verify |
| 22 | Explain / optimize / fix SQL | ⬜ | ✅ batch (TASK-023) ⚠ verify |
| 23 | Result → tile / new table | ⬜ | ⏳ built (TASK-040, awaiting sign-off) |
| 24 | Export results | 🟡 | ✅ (Wave 2) ⚠ verify multi-tab/clipboard |
| 25 | Parameterized queries | ⬜ | ⬜ **open (next)** |
| 26 | Auto-EDA on upload | ⬜ | ✅ batch (TASK-023) ⚠ verify |
| 27 | Auto starter-dashboard | ✅⏳ | ✅ (deterministic seed) |
| 28 | Auto-cleaning suggestions | ✅⏳ | ✅ + extended (TASK-041 seeds) |
| 29 | Data storytelling | ⬜ | ✅ batch (TASK-023) ⚠ verify |
| 30 | Chart-type recommendation | ⬜ | ✅ batch (TASK-023) ⚠ verify |
| 31 | More upload formats | ⬜ | ✅ (Wave 2, Parquet bug fixed) ⚠ |
| 32 | Multi-table switcher | ⬜ | ✅ signed off (TASK-039) |
| 33 | Session export / import | ⬜ | ⬜ **open** |
| 34 | Shareable snapshot | ⬜ | ⬜ **open** |

**Net remaining product work:** #25, #33, #34 (open), #13, #16 (deferred partials), #9 (recipe
completeness, likely partial), plus the §2.5 verification of the Wave-4 AI batch. Everything
else on the 34-item list is built or awaiting your sign-off.

---

*This is a draft for discussion, grounded in the repo's own planning docs and the actual
completed-task inventory. Correct anything that doesn't match your intent and it'll be revised.*
