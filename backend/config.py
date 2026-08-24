"""Central deployment knobs (TASK-013).

One tiny module so the upload cap, session-TTL, and sweep parameters are read
from the environment in exactly one place and shared (DRY) across
``routers/session.py``, ``main.py``, ``services/cleanup_service.py`` and
``routers/admin.py``. Matches the existing inline-``os.getenv`` convention used
for ``SPENCER_CORS_ORIGINS`` -- values are resolved once at import time.

All knobs have safe defaults so an un-configured deploy still runs bounded.
"""
import os

# --- Upload guardrails ---------------------------------------------------
# Hard ceiling on a single upload. Enforced in three coordinated layers
# (proxy client_max_body_size -> Content-Length middleware -> streaming
# byte-count backstop), because Starlette has already spooled the body before
# the route runs, so the app layers are defense-in-depth, not the airtight gate.
MAX_UPLOAD_MB: int = int(os.getenv("SPENCER_MAX_UPLOAD_MB", "100"))
MAX_UPLOAD_BYTES: int = MAX_UPLOAD_MB * 1024 * 1024

# Comma-separated extension allowlist (no leading dot, case-insensitive). The
# default covers every format the ingestion reader understands (Wave 2 / TASK-020):
# csv + tsv (read_csv_auto), parquet (read_parquet), json (read_json_auto), and
# xlsx (openpyxl bridge). A disallowed extension is rejected up front (415).
_raw_ext = os.getenv("SPENCER_UPLOAD_ALLOWED_EXT", "csv,tsv,parquet,json,xlsx")
ALLOWED_EXTENSIONS: frozenset[str] = frozenset(
    e.strip().lstrip(".").lower() for e in _raw_ext.split(",") if e.strip()
)

# Chunk size for the streaming persist/backstop copy (256 KiB).
UPLOAD_CHUNK_BYTES: int = 256 * 1024

# --- Session lifetime / cleanup sweep ------------------------------------
# The `session:{uuid}` liveness marker's TTL. This is the value the DATABASE.md
# Redis schema previously listed as an undefined "session lifetime" gap.
SESSION_TTL_HOURS: int = int(os.getenv("SPENCER_SESSION_TTL_HOURS", "24"))
SESSION_TTL_SECONDS: int = SESSION_TTL_HOURS * 3600

# How often the background sweeper runs.
SWEEP_INTERVAL_MIN: int = int(os.getenv("SPENCER_SWEEP_INTERVAL_MIN", "30"))
SWEEP_INTERVAL_SECONDS: int = SWEEP_INTERVAL_MIN * 60

# Never reap an upload dir whose mtime is younger than this -- protects an
# in-flight upload whose session marker/table doesn't exist *yet*.
SWEEP_GRACE_MIN: int = int(os.getenv("SPENCER_SWEEP_GRACE_MIN", "15"))
SWEEP_GRACE_SECONDS: int = SWEEP_GRACE_MIN * 60

# --- DuckDB runtime hardening (applied at startup via run_readwrite) ------
# Closes the documented-but-unimplemented memory_limit claim (DATABASE.md) and
# bounds RAM / enables disk spill under concurrent ingest, without touching the
# frozen duckdb_manager.
DUCKDB_MEMORY_LIMIT: str = os.getenv("SPENCER_DUCKDB_MEMORY_LIMIT", "4GB")
DUCKDB_TEMP_DIR: str = os.getenv("SPENCER_DUCKDB_TEMP_DIR", "").strip()

# --- LLM API key pool (TASK-024) -----------------------------------------
# Quota-aware rotation across multiple provider keys (see services/llm_key_pool.py).
# The secrets themselves (GEMINI_API_KEYS / ANTHROPIC_API_KEYS) are parsed in the pool
# module, never here -- these are the non-secret behaviour knobs only.
#
# PROACTIVE soft cap: max successful requests per key per UTC day before the pool skips
# it without trying. 0 = off (pure reactive rotation on 429). Set to 20 to mirror the
# Gemini free tier (20 requests/day/model).
LLM_DAILY_LIMIT_PER_KEY: int = int(os.getenv("SPENCER_LLM_DAILY_LIMIT_PER_KEY", "0"))

# REACTIVE cooldown (seconds) when a 429 carries no parseable retryDelay -- bench the
# key this long (treated as a per-minute rate limit) before it is eligible again.
LLM_KEY_COOLDOWN_SECONDS: int = int(os.getenv("SPENCER_LLM_KEY_COOLDOWN_SECONDS", "60"))

# REACTIVE cooldown (seconds) for a per-DAY quota exhaustion (e.g. Gemini free-tier
# daily cap). ~6h benches then retries, which self-heals across the provider's midnight
# reset without any timezone math. Default 21600 = 6h.
LLM_DAILY_COOLDOWN_SECONDS: int = int(os.getenv("SPENCER_LLM_DAILY_COOLDOWN_SECONDS", "21600"))

# --- Filesystem layout ----------------------------------------------------
# Root directory holding per-session upload dirs (`uploads/{uuid}/...`).
UPLOADS_DIR: str = os.getenv("SPENCER_UPLOADS_DIR", "uploads")


def ext_of(filename: str) -> str:
    """Lowercased extension without the dot (``"data.CSV"`` -> ``"csv"``)."""
    return os.path.splitext(filename or "")[1].lstrip(".").lower()


def is_allowed_upload(filename: str) -> bool:
    """True iff `filename`'s extension is in the allowlist. Fails closed: a
    filename with no extension (or an empty name) is rejected."""
    return ext_of(filename) in ALLOWED_EXTENSIONS
