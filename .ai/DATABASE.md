# DATABASE.md

## DuckDB
- Single file: `spencer.db`
- Table naming: `t_{session_uuid}_{tablename}`
- Snapshot naming: `backup_{session_uuid}_{tablename}_step_{n}`, capped at last 5–10 per table, oldest dropped on overflow (or `CREATE VIEW` instead of materialized snapshot where the transform is cheap to re-derive)
- **Single connection** (`self._conn = duckdb.connect(db_path)`) — DuckDB rejects a second connection to the same file with a different `read_only` config while one is open in-process (empirically confirmed, ADR-003 superseded).
- **AI-generated SQL execution (ADR-010):** runs on this same connection, but wrapped in an explicit transaction that is **always rolled back** — `BEGIN` → execute → fetch results → `ROLLBACK`, unconditionally, regardless of statement type or outcome. Never `COMMIT` on this path. This relies on DuckDB's (unusual) support for transactional DDL — pending empirical proof via TASK-001-FIX-02 that a rollback genuinely leaves no trace for both DDL and DML.
- Method naming: avoid `get_readonly_connection()`/`run_readonly()` going forward — these names imply a connection-level guarantee that no longer exists this way. Use something accurate, e.g. `run_sandboxed()`.
- `PRAGMA memory_limit` **applied at app startup** (TASK-013) via `run_readwrite` in `main.py` — the frozen `duckdb_manager` is untouched. Configurable via `SPENCER_DUCKDB_MEMORY_LIMIT` (default `4GB`; operator value regex-validated so a malformed knob can't break out of the PRAGMA literal). Optional `SPENCER_DUCKDB_TEMP_DIR` sets the disk-spill location. Confirm the live value via `GET /admin/storage` → `duckdb_memory_limit`.

## Redis Key Schema
| Key pattern | Value | TTL | Notes |
|---|---|---|---|
| `session:{session_uuid}` | `"1"` | sliding, `SPENCER_SESSION_TTL_HOURS` (default 24h) | **liveness marker (TASK-013).** Set on create/upload; slid on any `/sessions/{uuid}/...` request (incl. read-only). Its expiry is what the cleanup sweep treats as a "dead session." `refresh_session` is EXPIRE-only, so a request to a reaped/bogus uuid does not resurrect it. |
| `schema:{session_uuid}` | `{table_name: {ddl, cardinality, samples}}` | no per-key TTL; session lifetime is defined by the `session:{uuid}` marker above, and this key is purged by the cleanup sweep when the session dies | multi-table dict since v1.2 |
| `joins:{session_uuid}` | list of confirmed join relationships | session lifetime | feeds AI prompt assembly |
| `bizdict:{session_uuid}` | `{term: definition}` | session lifetime | Custom Instructions |
| `query:{question_hash}:{schema_version}:{bizdict_version}` | generated SQL | no TTL (version-keyed, not time-keyed) | |
| `fail:{question_hash}:{schema_version}:{bizdict_version}` | cached failure/error shape | 5 min | avoids repeat LLM burn on identical failing question |
| `job:{session_uuid}:{job_id}` | status/stage | job lifetime | |
| `pinned_schema:{schedule_id}` / `pinned_bizdict:{schedule_id}` | snapshot copies | until schedule deleted | decouples scheduled runs from session expiry |
| APScheduler job store | — | persistent | **must be configured as Redis-backed, not default in-memory — currently unimplemented, see CURRENT_STATE.md** |

`question_hash` = SHA-256 of lowercased, whitespace-normalized question string.
`schema_version` increments on any table transform or join add/remove.
`bizdict_version` increments on any Custom Instructions add/update/delete.