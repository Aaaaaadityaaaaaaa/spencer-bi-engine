# API.md

Full, authoritative request/response contract. Self-contained — no external file dependency.

## Naming Conventions
- Session may contain more than one table; each follows `t_{session_uuid}_{tablename}`
- **Primary table:** first table uploaded in a session. Endpoints without `table_name` default to it.
- `join_id`: UUID4

## Session & Ingestion
- `POST /sessions` — first upload, creates session + primary table. Response:
```json
{
  "session_uuid": "uuid",
  "table_name": "t_{uuid}_{tablename}",
  "row_count": 123456,
  "columns": [{"name": "revenue", "type": "DOUBLE", "cardinality": 8421}]
}
```
- `POST /sessions/{session_uuid}/tables` — additional file upload, registers a new (non-primary) table. Response: `{ "table_name": "...", "row_count": ..., "columns": [...] }`
- `GET /sessions/{session_uuid}/tables` — list tables in session
- `DELETE /sessions/{session_uuid}` — teardown

- `GET /sessions/{session_uuid}/schema` — **multi-table array shape (v1.2 — this was stubbed in Day 2 against the old v1.1 single-table shape and needs correcting):**
```json
{
  "tables": [
    {
      "table_name": "t_{uuid}_orders",
      "is_primary": true,
      "columns": [{"name": "revenue", "type": "DOUBLE", "cardinality": 8421}]
    },
    {
      "table_name": "t_{uuid}_customers",
      "is_primary": false,
      "columns": [{"name": "customer_id", "type": "INTEGER", "cardinality": 4021}]
    }
  ]
}
```
Frontend reads `.tables[]`, not `.columns[]` directly.

## Transform / Undo / Redo / History
- `POST /sessions/{session_uuid}/transform` — discriminated union by `op`, optional `table_name` (defaults to primary):
```json
// op: "dedupe"        -> { "op": "dedupe" }
// op: "drop_null"      -> { "op": "drop_null", "column": "col_name" }
// op: "impute_null"    -> { "op": "impute_null", "column": "col_name", "strategy": "zero|mean|median|custom", "fill_value": null }
// op: "cast"           -> { "op": "cast", "column": "col_name", "new_type": "INTEGER" }
// op: "calculated_column" -> { "op": "calculated_column", "new_column_name": "profit", "formula": "revenue - cost" }
```
- `POST .../undo`, `POST .../redo` — per-table independent history
- `GET .../history`:
```json
{ "steps": [{"step": 1, "op": "cast", "column": "revenue", "timestamp": "..."}], "current_step_index": 3, "total_steps": 5, "can_undo": true, "can_redo": true }
```

## Data Grid & Charting
- `GET /sessions/{session_uuid}/data?offset=0&limit=500` — optional `table_name`
- `POST /sessions/{session_uuid}/chart` — optional `chart_type` (auto-suggested if omitted) and `table_name`. Response gains `chart_type_used` and `suggested: bool`. **Charting is single-table only** — no joined-view charts in this version.

## Joins
- `GET /sessions/{session_uuid}/joins/suggestions`:
```json
{ "suggestions": [{ "table_a": "t_{uuid}_orders", "column_a": "customer_id", "table_b": "t_{uuid}_customers", "column_b": "customer_id", "confidence": "high" }] }
```
`confidence`: `"high"` on exact name+type match, `"low"` on fuzzy/type-only. Never auto-applied.
- `POST /sessions/{session_uuid}/joins` — `{ "table_a": ..., "column_a": ..., "table_b": ..., "column_b": ... }` → `{ "join_id": "uuid" }`
- `GET .../joins`, `DELETE .../joins/{join_id}`

## AI Layer
- `POST /sessions/{session_uuid}/ask` — `{ "question": "..." }` → `{ "sql": "...", "cache_hit": bool, "retries_used": int }`
- `POST /sessions/{session_uuid}/execute` — async, no exact-match requirement (validates whatever SQL arrives via sqlglot regardless of source). Returns `{ "query_id": "uuid", "status": "running" }`
- `GET /sessions/{session_uuid}/queries/{query_id}` — `{ "status": "running|completed|failed|cancelled", "result": "<msgpack ref>", "error": null }`
- `GET/POST /sessions/{session_uuid}/instructions`, `DELETE .../instructions/{term}`

## Scheduling
- `POST /sessions/{session_uuid}/schedules` — `{ "question": "...", "cron": "0 8 * * MON" }` → `{ "schedule_id": "uuid", "next_run": "iso" }`
- `GET .../schedules`, `DELETE .../schedules/{schedule_id}`, `GET .../schedules/{schedule_id}/runs`

## Admin
- `POST /admin/kill-query/{query_id}`
- `GET /health` — must verify Redis + DuckDB reachability, not just process liveness (gap, see CURRENT_STATE.md)

## Error Shape (uniform, all endpoints)
```json
{ "error": "short_code", "message": "human-readable", "retryable": false }
```

## Redis Key Schema
See DATABASE.md — this file covers endpoint shapes only.