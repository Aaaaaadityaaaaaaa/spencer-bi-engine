"""TASK-027 proof #2: per-user data isolation (multi-tenancy).

User A creates a session; user B must get **404** (never 403 -- no existence
leak) on every representative route, and **401** with no token at all; A succeeds
on its own session; /admin/* is 403 for a non-admin, 401 with no token, 200 for an
admin. Finally A deletes its own session (exercising delete_session) and then 404s.

Hermetic + coexists with a running uvicorn -- run from a throwaway CWD:

    TMPD=$(mktemp -d) && cd "$TMPD" && python "E:/SPENCER V1/backend/test_tenant_isolation.py"

No LLM is called: the ownership guard 404s B before any handler runs, and A's
success paths use only /schema + /data. Touches Redis (schema cache) + a fresh
throwaway DuckDB.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("SPENCER_APP_DB_URL", "sqlite:///test_tenant_app.db")
os.environ.setdefault("SPENCER_JWT_SECRET", "test-secret-key-that-is-32plus-bytes-long")

if os.path.exists("test_tenant_app.db"):
    os.remove("test_tenant_app.db")

from fastapi.testclient import TestClient
from main import app
from services.app_db import init_db, SessionLocal
from services import auth_service, cleanup_service
from services.redis_manager import redis_manager

init_db()
client = TestClient(app)

FIXTURE_CSV = "id,region,amount\n1,West,100\n2,East,30\n3,West,20\n"
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


def register(email):
    r = client.post("/auth/register", json={"email": email, "password": "password123"})
    assert r.status_code == 200, f"register {email} failed: {r.status_code} {r.text[:200]}"
    return r.json()["access_token"]


def run():
    uuid_a = None
    try:
        print(f"backend redis = {getattr(redis_manager, 'backend', '?')}")
        token_a = register("a@example.com")
        token_b = register("b@example.com")

        # A creates a session (upload a small CSV).
        r = client.post("/sessions", headers=hdr(token_a),
                        files={"file": ("sales.csv", FIXTURE_CSV, "text/csv")})
        check("A create session 200", r.status_code == 200, f"status={r.status_code} body={r.text[:200]}")
        uuid_a = r.json().get("session_uuid") if r.status_code == 200 else None
        check("session_uuid returned", bool(uuid_a))
        if not uuid_a:
            raise SystemExit("cannot continue without a session")

        # A succeeds on its OWN session (non-LLM routes).
        r = client.get(f"/sessions/{uuid_a}/schema", headers=hdr(token_a))
        check("A GET own /schema 200", r.status_code == 200, f"status={r.status_code}")
        r = client.get(f"/sessions/{uuid_a}/data", headers=hdr(token_a))
        check("A GET own /data 200", r.status_code == 200, f"status={r.status_code}")

        # B is DENIED on A's session -> 404 (NOT 403 -- no existence leak).
        for path in (f"/sessions/{uuid_a}/schema", f"/sessions/{uuid_a}/data",
                     f"/sessions/{uuid_a}/history", f"/sessions/{uuid_a}/quality"):
            r = client.get(path, headers=hdr(token_b))
            check(f"B GET /{path.split('/')[-1]} -> 404", r.status_code == 404, f"status={r.status_code}")

        # POST routes with valid bodies: guard 404s before handler/LLM.
        r = client.post(f"/sessions/{uuid_a}/transform", headers=hdr(token_b), json={"op": "dedupe"})
        check("B POST /transform -> 404", r.status_code == 404, f"status={r.status_code}")
        r = client.post(f"/sessions/{uuid_a}/ask", headers=hdr(token_b), json={"question": "how many rows?"})
        check("B POST /ask -> 404 (no LLM reached)", r.status_code == 404, f"status={r.status_code}")

        # No token at all -> 401 (authentication before authorization).
        r = client.get(f"/sessions/{uuid_a}/schema")
        check("no-token /schema -> 401", r.status_code == 401, f"status={r.status_code}")
        r = client.post(f"/sessions/{uuid_a}/ask", json={"question": "x"})
        check("no-token /ask -> 401", r.status_code == 401, f"status={r.status_code}")

        # Unknown uuid + valid token -> 404 (indistinguishable from not-owned).
        r = client.get("/sessions/00000000-0000-0000-0000-000000000000/schema", headers=hdr(token_a))
        check("A GET unknown uuid -> 404", r.status_code == 404, f"status={r.status_code}")

        # /admin/* : non-admin 403, no-token 401, admin 200.
        r = client.get("/admin/storage", headers=hdr(token_a))
        check("non-admin /admin/storage -> 403", r.status_code == 403, f"status={r.status_code}")
        r = client.get("/admin/storage")
        check("no-token /admin/storage -> 401", r.status_code == 401, f"status={r.status_code}")
        db = SessionLocal()
        auth_service.create_user(db, "admin@example.com", "password123", is_admin=True)
        db.close()
        radm = client.post("/auth/login", json={"email": "admin@example.com", "password": "password123"})
        token_admin = radm.json().get("access_token")
        r = client.get("/admin/storage", headers=hdr(token_admin))
        check("admin /admin/storage -> 200", r.status_code == 200, f"status={r.status_code} body={r.text[:200]}")

        # A deletes its OWN session (exercises delete_session), then 404s on it.
        r = client.delete(f"/sessions/{uuid_a}", headers=hdr(token_a))
        check("A DELETE own session 200", r.status_code == 200, f"status={r.status_code} body={r.text[:200]}")
        check("delete reports deleted + counts", r.json().get("status") == "deleted", r.text[:200])
        r = client.get(f"/sessions/{uuid_a}/schema", headers=hdr(token_a))
        check("A GET deleted /schema -> 404", r.status_code == 404, f"status={r.status_code}")
        r = client.delete(f"/sessions/{uuid_a}", headers=hdr(token_a))
        check("A DELETE again -> 404 (already gone)", r.status_code == 404, f"status={r.status_code}")
        uuid_a = None  # cleaned up by the delete; skip the finally reclaim

    finally:
        # Best-effort reclaim if a mid-test failure skipped the delete.
        if uuid_a:
            try:
                import asyncio
                asyncio.run(cleanup_service.reclaim_session_storage(uuid_a))
            except Exception:
                pass

    print()
    if _failures:
        print(f"RESULT: {len(_failures)} FAILED -> {_failures}")
        sys.exit(1)
    print("RESULT: ALL CHECKS PASSED")


if __name__ == "__main__":
    run()
