# Local-only dev launcher: load .env into os.environ, then exec uvicorn.
# .env may contain keys with characters that break a shell `source` (e.g. parentheses),
# so we parse with Python (which treats values as opaque strings) and hand the env to
# the uvicorn subprocess via execvp. Not used in production.
import os
import sys
import subprocess

ENV_PATH = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(ENV_PATH):
    with open(ENV_PATH, "r", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip()
            # strip surrounding quotes if present
            if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                v = v[1:-1]
            os.environ[k] = v

host = os.environ.get("SPENCER_HOST", "127.0.0.1")
port = os.environ.get("SPENCER_PORT", "8000")

# Run database migrations before starting the server
print("Running Alembic migrations...")
migration_code = subprocess.call([sys.executable, "-m", "alembic", "upgrade", "head"])
if migration_code != 0:
    print("Database migration failed. Exiting.")
    sys.exit(migration_code)

sys.exit(
    subprocess.call(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "main:app",
            "--host",
            host,
            "--port",
            port,
        ]
    )
)
