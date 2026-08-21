# Spencer

**An in-process, columnar BI engine.** Upload CSV/Parquet, clean it visually, build charts by dragging columns onto axes, and ask questions in plain English that are translated to SQL and executed **only after you approve them**. The full analyst workflow — ingest → clean → visualize → query — on a single machine, no data-warehouse stack required.

Built as a portfolio project around a real design constraint: *how do you let an LLM write SQL against your database without ever letting it damage your data?*

---

## Status

Early build, developed in verifiable phases. Every "done" below is backed by committed test output, not assertion — see [`.ai/CURRENT_STATE.md`](.ai/CURRENT_STATE.md) for the reproducible green state and [`tasks/`](tasks/) for per-task proofs.

| Phase | Scope | State |
|------:|-------|-------|
| 1 | DuckDB connection layer, concurrency model, Redis cache | ✅ Verified (sequential + concurrent) |
| 2 | Multi-table ingestion, session & schema management | ✅ Verified (real DuckDB inference, real Redis round-trip) |
| 3 | Visual data cleaning + per-table undo/redo (via Ibis) | ✅ Verified (10 ops incl. predicate filtering, dry-run preview, snapshot undo/redo, fail-closed formula/predicate validation + function allowlist) |
| 4 | Virtualized data grid + pagination | ✅ Verified (paginated `/data`, virtualized infinite-scroll grid, first live Axios wiring) |
| 5 | Drag-and-drop charting canvas | ▫️ Not started |
| 6 | Natural-language → SQL | ◐ Validator done & verified; LLM call, retry loop, and Review Gate UI unbuilt |
| 7 | Scheduled recurring queries (APScheduler) | ▫️ Not started |

The backend core (connection safety, ingestion, the cleaning/transform pipeline, the SQL security layers) is built and tested. The frontend's upload → schema → virtualized-grid path is now wired to the backend over Axios (Phase 4); the charting canvas and the AI query palette remain a component shell.

---

## The interesting part: making AI-generated SQL safe

Letting a language model emit SQL against a live database is the risky heart of this product. Spencer's answer is **three independent layers**, each of which must pass before a single AI-authored row of SQL can touch data:

**1 — Static validation (fail-closed).**
Every candidate query is parsed with [`sqlglot`](https://github.com/tobymao/sqlglot) in the DuckDB dialect and rejected unless it is *exactly one* statement and *purely* a `SELECT`/`WITH`. The whole parse tree is walked for forbidden nodes (`INSERT`, `UPDATE`, `DELETE`, `DROP`, `CREATE`, `ALTER`, `ATTACH`, `COPY`, `SET`, transaction control, …). Anything unparseable, empty, stacked, or write-shaped is refused. The default is *reject* — a parse failure denies the query rather than passing it through.
→ 25/25 adversarial cases, including writes smuggled inside CTEs (`WITH c AS (DELETE … RETURNING *)`), statement stacking, `ATTACH`/`COPY`/`SET`, and a benign `SELECT` whose *string literal* merely contains the text `DROP TABLE`.
See [`backend/services/sql_validator.py`](backend/services/sql_validator.py), [`backend/test_sql_validator.py`](backend/test_sql_validator.py), and ADR-013.

**2 — Rollback sandbox (engine-level guarantee).**
Validation can have blind spots, so it is not trusted alone. AI-path SQL executes inside an explicit transaction that is **always rolled back** — unconditionally, in a `finally`, regardless of statement type, success, or failure. Nothing on this path is ever committed. Because DuckDB uniquely supports *transactional DDL*, even a `CREATE`/`DROP` that somehow slipped past layer 1 cannot persist: the database engine itself throws the work away.
→ Verified both sequentially and under concurrent load. See [`backend/services/duckdb_manager.py`](backend/services/duckdb_manager.py) (`run_sandboxed`) and ADR-010.

**3 — Human Review Gate.**
No AI-generated SQL runs until a person reads it and confirms. Validation result is irrelevant to this step — the gate is mandatory. *(UI lands in Phase 6.)*

User-driven queries (cleaning, charting) travel a **separate** read-write path that never sees the LLM — and that path uses bound parameters and quoted identifiers throughout, closing an ingestion-time SQL-injection / path-traversal hole found and fixed during the build (ADR-012).

---

## Architecture at a glance

```
Vue 3 + TS frontend          upload · schema pills · virtualized grid ·
(grid path wired)            ECharts canvas · Ctrl-K AI palette · Review Gate

FastAPI backend              single Uvicorn worker; every DuckDB call routed
(--workers 1)                through a ThreadPoolExecutor

DuckDB                       one file (spencer.db), one connection.
                             AI SQL → always-rollback transaction.
                             User SQL → bound-parameter read-write path.

Redis                        schema / join / query cache, session & job state,
                             APScheduler job store

LLM API (Claude / Gemini)    direct prompting, no RAG / vector store
```

**Deliberate single-machine constraints** (features, not bugs): one DuckDB file and one worker, because DuckDB is single-writer per file; realistic scale is 2–5 tables per session, not dozens. The whole point is a full BI workflow without a client-server warehouse.

Design rationale lives in [`.ai/DECISIONS.md`](.ai/DECISIONS.md) (14 ADRs, including the ones disproven and superseded along the way) and [`.ai/ARCHITECTURE.md`](.ai/ARCHITECTURE.md).

---

## Repository layout

```
.ai/            Living design docs — PROJECT, ARCHITECTURE, DATABASE, API,
                DECISIONS (ADRs), CODING_STANDARDS (confirmed anti-patterns),
                CURRENT_STATE (reproducible status)
backend/        FastAPI app, services (duckdb / redis / sql_validator / ai),
                routers, and standalone proof scripts (test_*.py)
frontend/       Vue 3 + TypeScript + Tailwind + Vite (component shell)
tasks/          Task files with attached proofs — active / completed / failed
```

---

## Running it locally

**Prerequisites:** Python 3.11+, Node 18+, and a running Redis on `localhost:6379`.

### 1. Redis
Any Redis server on `6379` works. On Windows without a Redis service, a portable `redis-server.exe` is the simplest route:
```bash
redis-server --port 6379 --save 60 1
```

### 2. Backend
```bash
cd backend
pip install -e ".[dev]"
uvicorn main:app --workers 1 --reload
```
API comes up at `http://localhost:8000` (`--workers 1` is required — see the DuckDB constraint above). Copy [`.env.example`](.env.example) to `.env` and fill in what you need; nothing secret is committed.

### 3. Frontend
```bash
cd frontend
npm install
npm run dev
```
Vite serves the UI at `http://localhost:5173` (the default CORS allowlist origin).

### 4. Tests / proofs
Each `backend/test_*.py` is a standalone script that prints real output and is safe to re-run (idempotent). With Redis up:
```bash
cd backend
python test_sql_validator.py            # 25/25 adversarial validator cases
python test_transaction_rollback_full.py # rollback sandbox
python test_concurrent.py                # concurrent safety
python test_multitable.py                # multi-table ingest + real-Redis proof
```
Any test that touches the cache prints the Redis backend in use — if it says anything other than `redis`, the proof is void (a silent `fakeredis` fallback once quietly invalidated every cache test in this project's history; that failure mode is now impossible to miss).

---

## Engineering approach

This repo doubles as a record of how it was built:

- **No claim without attached proof.** Status docs quote real command output; "should work" is not evidence.
- **Fail-closed by default.** Security controls deny on error rather than pass through — the SQL validator being the clearest example.
- **Idempotent, self-describing tests.** Proof scripts can run twice in a row and announce which backend actually served them, so a green run can't be faked by hidden state or a substituted dependency.
- **Decisions are recorded, including the wrong ones.** [`.ai/DECISIONS.md`](.ai/DECISIONS.md) keeps superseded ADRs (e.g. the dual-connection design that DuckDB empirically rejected) rather than quietly deleting them, and [`.ai/CODING_STANDARDS.md`](.ai/CODING_STANDARDS.md) catalogs anti-patterns that were real bugs caught here, not hypotheticals.

---

## Non-goals (intentional scope)

- Not multi-tenant SaaS — one analyst per session
- No live external database connections — upload-only
- No bring-your-own-key — single server-side API key
- No RAG / vector store / Vanna.ai — direct prompting only, at any table count in scope
- No Streamlit — a properly decoupled FastAPI + Vue app
- No saved/persisted dashboards in this version
- Not horizontally scalable — the DuckDB single-writer-file model is accepted by design
