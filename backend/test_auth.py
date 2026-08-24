"""TASK-027 proof #1: authentication (register / login / me; token & error paths).

Standalone + hermetic. Sets SPENCER_APP_DB_URL to a throwaway SQLite file in the
CURRENT directory and SPENCER_JWT_SECRET *before* importing the app, so config
resolves them at import. Run from a throwaway CWD so the DuckDB singleton opens a
fresh, unlocked spencer.db there and this coexists with a running uvicorn:

    TMPD=$(mktemp -d) && cd "$TMPD" && python "E:/SPENCER V1/backend/test_auth.py"

Module-scope TestClient does NOT fire startup events, so init_db() is called
explicitly. No LLM and no real dataset are touched -- this is the identity layer.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Must be set BEFORE importing config/main (config reads env at import time).
os.environ.setdefault("SPENCER_APP_DB_URL", "sqlite:///test_auth_app.db")
os.environ.setdefault("SPENCER_JWT_SECRET", "test-secret-key-that-is-32plus-bytes-long")

# Fresh app DB each run (a throwaway CWD is already fresh; this is belt+braces).
if os.path.exists("test_auth_app.db"):
    os.remove("test_auth_app.db")

from fastapi.testclient import TestClient
import config
from main import app
from services.app_db import init_db
from services.redis_manager import redis_manager

init_db()
client = TestClient(app)

_failures = []


def check(label, cond, detail=""):
    mark = "PASS" if cond else "FAIL"
    if not cond:
        _failures.append(label)
    line = f"  [{mark}] {label}"
    if detail:
        line += f"  ->  {detail}"
    print(line)


def hdr(token):
    return {"Authorization": f"Bearer {token}"}


def run():
    print(f"backend redis = {getattr(redis_manager, 'backend', '?')}")

    # 1. register -> token + normalized user
    r = client.post("/auth/register", json={"email": "Alice@Example.com", "password": "password123"})
    check("register 200", r.status_code == 200, f"status={r.status_code} body={r.text[:200]}")
    body = r.json() if r.status_code == 200 else {}
    token_a = body.get("access_token")
    check("register returns token", bool(token_a))
    check("register email normalized", body.get("user", {}).get("email") == "alice@example.com",
          body.get("user", {}).get("email"))
    check("register user not admin", body.get("user", {}).get("is_admin") is False)

    # 2. /me with token
    r = client.get("/auth/me", headers=hdr(token_a))
    check("me 200 with token", r.status_code == 200, f"status={r.status_code}")
    check("me returns same email", r.json().get("email") == "alice@example.com")

    # 3. /me without token -> 401
    r = client.get("/auth/me")
    check("me 401 without token", r.status_code == 401, f"status={r.status_code}")

    # 4. /me malformed token -> 401
    r = client.get("/auth/me", headers=hdr("not-a-real-token"))
    check("me 401 bad token", r.status_code == 401, f"status={r.status_code}")

    # 5. /me malformed header (no scheme) -> 401
    r = client.get("/auth/me", headers={"Authorization": token_a or "x"})
    check("me 401 header without Bearer scheme", r.status_code == 401, f"status={r.status_code}")

    # 6. duplicate email (case/space-insensitive) -> 400
    r = client.post("/auth/register", json={"email": "  ALICE@Example.com ", "password": "password123"})
    check("duplicate email 400", r.status_code == 400, f"status={r.status_code}")

    # 7. login ok
    r = client.post("/auth/login", json={"email": "alice@example.com", "password": "password123"})
    check("login 200", r.status_code == 200, f"status={r.status_code}")
    check("login returns token", bool(r.json().get("access_token")))

    # 8. login wrong password -> 401
    r = client.post("/auth/login", json={"email": "alice@example.com", "password": "WRONG-pass"})
    check("login 401 wrong password", r.status_code == 401, f"status={r.status_code}")

    # 9. login unknown email -> 401 (same generic message; no enumeration)
    r = client.post("/auth/login", json={"email": "nobody@example.com", "password": "password123"})
    check("login 401 unknown email", r.status_code == 401, f"status={r.status_code}")

    # 10. short password -> 422 (pydantic min_length)
    r = client.post("/auth/register", json={"email": "shorty@example.com", "password": "short"})
    check("short password 422", r.status_code == 422, f"status={r.status_code}")

    # 11. invalid email -> 422 (EmailStr)
    r = client.post("/auth/register", json={"email": "not-an-email", "password": "password123"})
    check("invalid email 422", r.status_code == 422, f"status={r.status_code}")

    # 12. ALLOW_REGISTRATION=false -> 403 (router reads config live)
    config.ALLOW_REGISTRATION = False
    try:
        r = client.post("/auth/register", json={"email": "late@example.com", "password": "password123"})
        check("registration disabled 403", r.status_code == 403, f"status={r.status_code}")
    finally:
        config.ALLOW_REGISTRATION = True

    # 13. a second, independent account still registers
    r = client.post("/auth/register", json={"email": "bob@example.com", "password": "password123"})
    check("second user register 200", r.status_code == 200, f"status={r.status_code}")

    print()
    if _failures:
        print(f"RESULT: {len(_failures)} FAILED -> {_failures}")
        sys.exit(1)
    print("RESULT: ALL CHECKS PASSED")


if __name__ == "__main__":
    run()
