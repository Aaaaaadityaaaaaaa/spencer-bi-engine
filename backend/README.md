# Spencer — Backend

FastAPI + DuckDB backend for Spencer. See the [project README](../README.md) for the full overview, architecture, and the AI-SQL security model.

## Quick start

```bash
pip install -e ".[dev]"
uvicorn main:app --workers 1 --reload
```

Requires Python 3.11+ and a Redis server on `localhost:6379`. `--workers 1` is mandatory — DuckDB is single-writer per file.

## Layout

- `main.py` — app entry, router registration, CORS allowlist
- `routers/` — HTTP endpoints (session/ingestion, query, ai, schedule, admin)
- `services/` — `duckdb_manager` (connection + always-rollback AI sandbox), `redis_manager` (real client + explicit fallback), `sql_validator` (fail-closed), `ai_service`
- `models/` — Pydantic schemas
- `test_*.py` — standalone, idempotent proof scripts; each cache-touching test prints the Redis backend in use

See [`../.ai/`](../.ai/) for design docs and [`../tasks/`](../tasks/) for task proofs.
