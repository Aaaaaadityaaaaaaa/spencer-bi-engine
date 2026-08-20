# CODING_STANDARDS.md

## Confirmed Anti-Patterns (do not repeat — each was an actual bug caught during this build)

**AP-1: Cursor-off-shared-connection masquerading as isolation.**
A method named `get_readonly_*` must return a cursor from a connection object itself opened with `read_only=True`. Never a `.cursor()` off the read-write connection. Proof required: a test that deliberately attempts a write through the "read-only" path and confirms DuckDB itself raises an error — code review alone does not close this class of bug.

**AP-2: Silent scope/sequence changes.**
Any deviation from the agreed task/roadmap order must be explicitly flagged and wait for confirmation — never presented as the default next step.

**AP-3: Contradictory report sections.**
A report/log section marked "none" must not also contain a real entry elsewhere that contradicts it (e.g., "deviations: none" while a tooling fallback is described under "assumptions").

**AP-4: Patchwork status reports instead of full rewrites.**
Any status/state file is a full regeneration each time, not an edit/append against the previous version. Duplicate entries are a sign this rule was violated.

**AP-5: Claims without attached proof.**
Never describe code as working, correct, or complete without the actual test/output that demonstrates it. "Should work" or "meticulously implemented" is not evidence.

**AP-6: Assuming a plausible-sounding architecture works without testing it.**
ADR-003's dual-connection design (read-write + read-only to the same DuckDB file, in-process) was reasonable on paper and still failed immediately on first real test — DuckDB rejects a second connection with a different config to an already-open file. This is exactly why every security-relevant design gets an explicit verification task before being trusted, not just a code read. See ADR-010 for the replacement (transaction-rollback on a single connection) — also unverified until tested, not assumed correct just because it sounds right.

**Naming rule:** a method's name must not imply a guarantee the implementation doesn't actually provide. `get_readonly_connection()` was misleading even before AP-1 (it returned a cursor with full write access) and would still be misleading now if reused for the transaction-rollback approach (there is no "read-only connection" anymore). Name methods for what they actually do — e.g. `run_sandboxed()`.

**AP-7: Proof scripts that can only pass once.**
`test_transaction_rollback_full.py` and `test_concurrent.py` each did `CREATE TABLE probe_table` with no teardown, against the **persistent** `spencer.db`. They passed on their original run and then failed on every subsequent run with `CatalogException: Table with name "probe_table" already exists!` — caught 2026-08-21 when re-running them as a regression check. Two compounding harms: (a) the project's most important security proofs could not be re-verified after any later change, and (b) the failure mode *impersonates a security regression*, so the natural reaction is to go hunting for a bug in the rollback model that isn't there. **Rule: every proof script must be idempotent — `DROP TABLE IF EXISTS` its own fixtures up front — and must be demonstrated by running it twice consecutively.** A proof you cannot re-run is not a regression test; it is a one-time anecdote. (Both suites fixed and shown green across two back-to-back runs, 12/12 assertions.)

**AP-8: Trusting a security control to cover a path it doesn't actually cover.**
ADR-010's rollback sandbox genuinely secures AI-generated SQL — and that created a blind spot. Ingestion interpolated a user-controlled filename straight into `read_csv_auto('{file_path}')` on `run_readwrite()`, the path with **no** rollback protection, so a filename containing `'` could break out of the string literal and persist injected DDL/DML. Verified live pre-fix, and verified neutralized post-fix via a sentinel table (`x'); DROP TABLE sentinel; --.csv` → sentinel survives). **Rule: when reasoning about whether input is safe, name the exact execution path it takes and confirm the control applies to *that* path.** "We're protected because of ADR-010" was true of one path and false of the one that mattered here. Related to AP-6: the failure is again an assumption that went untested.

**AP-9: Security stubs that fail OPEN, and fallbacks that fail SILENTLY.**
Two instances, same root cause — a component that was not yet load-bearing was written to succeed by default, so nothing looked wrong.
- `SQLValidator.validate()` was `return True`, unconditionally. It reads as a working security control and is a rubber stamp; the first time Phase 6 called it, `DROP TABLE` would have been approved. It would also have quietly reduced the documented 3-layer AI-SQL defense to 2. See ADR-013.
- `redis_manager` silently substituted `fakeredis`, so **every** Redis "proof" in this project's history actually exercised an in-memory fake. When a real Redis was finally started, the client *still* fell back (redis-py RESP3 `HELLO` vs Redis 5) — and only the explicit `.backend` attribute plus a logged warning revealed it. A silent fallback had turned a green test into a meaningless one.

**Rule:** a stub for a security-relevant component must fail **closed** (`return False` / raise `NotImplementedError`), never open. A fallback must be **loud** — logged, and exposed as inspectable state (e.g. `redis_manager.backend`) that proof scripts are required to print. If a test cannot tell you *which* implementation served it, it cannot certify anything. Corollary to AP-5: attached proof is only proof if it also identifies what produced it.

## Query Construction Rules
- Spencer's own queries (transforms, chart aggregation, joins) are built via **Ibis expressions**, compiled to SQL, then executed through the existing connection wrapper. Ibis never opens its own connection or executes directly in this codebase.
- Ibis's table schema must be **re-fetched per request**, never cached long-term — stale schema after a transform produces incorrect SQL silently.
- AI-generated SQL is never built with Ibis — it comes only from the LLM, validated by `sqlglot`, and executed **via `run_sandboxed()`** (single connection, unconditional-rollback transaction per ADR-010). There is no "read-only connection" — that was ADR-003, which was disproven.
- **User-controlled values are never string-interpolated into SQL.** File paths are passed as bound parameters (`read_csv_auto(?, header=true)`); identifiers derived from user data (CSV column headers, filenames) are sanitized and/or double-quote-escaped. This applies with *extra* force on `run_readwrite()` — ADR-010's rollback sandbox protects only `run_sandboxed()`, so anything injected on the read-write path **persists**. See ADR-012 / AP-8.

## SQL Validation Rules
- `sqlglot.parse_one(sql, read="duckdb")` — always specify the DuckDB dialect explicitly. Default/generic parsing risks false accepts or false rejects on DuckDB-specific syntax.
- Only a parsed result resolving to pure `Select` (optionally wrapped in `With`) may proceed to execution.

## Naming Conventions
- Table: `t_{session_uuid}_{tablename}`
- Snapshot: `backup_{session_uuid}_{tablename}_step_{n}`
- Upload path: `uploads/{session_uuid}/{sanitized_filename}` — the on-disk name is derived from the sanitized table name plus a whitelisted extension, never the raw client-supplied `filename` (path traversal / SQL-breakout vector, see AP-8).

## Error Handling
- Uniform error shape (see API.md) enforced via a **central FastAPI exception handler**, not per-router formatting.
- LLM API failures (timeout, rate limit, malformed response) must be handled as a distinct failure mode from "DuckDB rejected the SQL" — do not feed an API failure into the same duplicate-SQL-detection logic used for bad-query retries.

## Reporting Format (build logs / implementation reports)
- Full rewrite every time (AP-4)
- Every section explicitly filled, "none" only where genuinely true and non-contradictory (AP-3)
- Any assumption made without asking is flagged, not silently baked in