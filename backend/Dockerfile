# syntax=docker/dockerfile:1

# Project Spencer — backend API image (FastAPI + DuckDB + Ibis + Redis client).
# Slim CPython; every declared dependency (duckdb, psycopg[binary], bcrypt,
# openpyxl, litellm, ...) ships a wheel, so no compiler or system libraries are
# needed. The base is multi-arch: `docker build` produces a native arm64 image on
# the Oracle Ampere target and amd64 locally, with no code change.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # Code lives in /app (kept on PYTHONPATH); the process RUNS from /data so that
    # DuckDB's relative "spencer.db" + the uploads dir land on the persisted volume
    # declared below, and an image rebuild never wipes user data.
    PYTHONPATH=/app \
    SPENCER_UPLOADS_DIR=/data/uploads

WORKDIR /app

# Dependencies are declared in pyproject.toml. There is no lockfile in the repo,
# so this resolves latest-compatible wheels at build time; adding a lockfile for
# byte-reproducible rebuilds is a documented follow-on.
COPY . /app
RUN pip install .

# Runtime data volume: the single-file DuckDB (spencer.db + .wal) and the
# per-session upload dirs. Owned by the non-root runtime user.
RUN useradd --system --uid 10001 --create-home spencer \
    && mkdir -p /data/uploads \
    && chown -R spencer:spencer /data
VOLUME ["/data"]

USER spencer
WORKDIR /data
EXPOSE 8000

# 0.0.0.0 so the container is reachable across the compose network. `main` is
# importable via PYTHONPATH (/app); the relative DuckDB path resolves under the
# current working directory (/data), i.e. on the volume.
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
