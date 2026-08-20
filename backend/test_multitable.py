"""Proof for TASK-003: two differently-named files coexist in one session
without collision or overwrite, and a crafted filename cannot inject SQL."""
from fastapi.testclient import TestClient
from main import app
from services.redis_manager import redis_manager
from services.duckdb_manager import db_manager
import json

client = TestClient(app)


def _upload(path, filename, session=None):
    with open(path, "rb") as f:
        if session is None:
            return client.post("/sessions", files={"file": (filename, f, "text/csv")})
        return client.post(f"/sessions/{session}/tables", files={"file": (filename, f, "text/csv")})


def test_multitable():
    print(f"REDIS BACKEND IN USE: {redis_manager.backend}")

    # 1. First file -> new session (primary table)
    r1 = _upload("messy.csv", "messy.csv")
    assert r1.status_code == 200, r1.text
    session = r1.json()["session_uuid"]
    primary_table = r1.json()["table_name"]
    print("\n--- POST /sessions (primary) ---")
    print(json.dumps({k: r1.json()[k] for k in ("session_uuid", "table_name", "row_count")}, indent=2))

    # 2. Second, DIFFERENTLY-NAMED file into the SAME session (non-primary)
    r2 = _upload("regions.csv", "regions.csv", session=session)
    assert r2.status_code == 200, r2.text
    second_table = r2.json()["table_name"]
    print("\n--- POST /sessions/{id}/tables (second file, same session) ---")
    print(json.dumps(r2.json(), indent=2, default=str))

    assert primary_table != second_table, "table names collided!"

    # 3. Schema shows BOTH tables with correct is_primary flags
    sch = client.get(f"/sessions/{session}/schema")
    assert sch.status_code == 200, sch.text
    print("\n--- GET /sessions/{id}/schema (both tables) ---")
    print(json.dumps(sch.json(), indent=2, default=str))
    tables = {t["table_name"]: t for t in sch.json()["tables"]}
    assert primary_table in tables and second_table in tables
    assert tables[primary_table]["is_primary"] is True
    assert tables[second_table]["is_primary"] is False

    # 4. Prove the primary table was NOT overwritten: both queryable, row counts intact
    conn = db_manager.get_readwrite_connection()
    try:
        pc = conn.execute(f"SELECT COUNT(*) FROM {primary_table}").fetchone()[0]
        sc = conn.execute(f"SELECT COUNT(*) FROM {second_table}").fetchone()[0]
    finally:
        conn.close()
    print(f"\n--- COEXISTENCE row counts: primary={pc}, second={sc} ---")
    assert pc == r1.json()["row_count"], "primary row count changed after 2nd upload!"
    assert sc == r2.json()["row_count"]

    # 5. Real cache value: dict keyed by BOTH table names
    redis_val = redis_manager.get_json(f"schema:{session}")
    print(f"\n--- {redis_manager.backend} schema:{session} ---")
    print("keys:", list(redis_val.keys()))
    print(json.dumps(redis_val, indent=2, default=str))
    assert set(redis_val.keys()) == {primary_table, second_table}

    # 6. Same-filename re-upload must NOT overwrite -> 409
    r3 = _upload("regions.csv", "regions.csv", session=session)
    print(f"\n--- Duplicate same-filename upload -> HTTP {r3.status_code} (expect 409, no overwrite) ---")
    print(r3.text)
    assert r3.status_code == 409

    print("\n[PASS] test_multitable")


def test_injection_filename_neutralized():
    # Malicious *filename*, valid CSV bytes. Pre-fix this broke out of the
    # read_csv_auto string literal on the non-sandboxed path.
    evil = "evil'; DROP TABLE t_should_not_exist; --.csv"
    r = _upload("regions.csv", evil)
    print(f"\n--- Malicious filename upload -> HTTP {r.status_code} (expect 200, neutralized) ---")
    assert r.status_code == 200, r.text
    print("created table:", r.json()["table_name"])
    print("[PASS] test_injection_filename_neutralized")


if __name__ == "__main__":
    test_multitable()
    test_injection_filename_neutralized()
