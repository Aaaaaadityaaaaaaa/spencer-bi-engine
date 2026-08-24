"""TASK-028 deploy-safety gate proof.

`config.assert_production_safety()` reads the environment at IMPORT time (module-
level constants, per the repo's config convention), so each case runs in a fresh
subprocess with a controlled environment. `import config` pulls only stdlib and
does NOT load any .env, so the subprocess env is authoritative.

Run:  python test_deploy_safety.py
"""
import os
import subprocess
import sys

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
SNIPPET = "import config; config.assert_production_safety(); print('BOOTED_OK')"


def run(env_overrides):
    env = dict(os.environ)
    # Clear the vars we toggle so a stray real value can't skew a case.
    for k in ("SPENCER_ENV", "SPENCER_JWT_SECRET", "SPENCER_APP_DB_URL"):
        env.pop(k, None)
    env.update(env_overrides)
    return subprocess.run(
        [sys.executable, "-c", SNIPPET],
        cwd=BACKEND_DIR, env=env, capture_output=True, text=True,
    )


def main():
    checks = []

    # 1. production + no JWT secret -> MUST refuse to boot (RuntimeError).
    r = run({"SPENCER_ENV": "production"})
    checks.append((
        "prod + no JWT secret refuses to boot",
        r.returncode != 0 and "forgeable" in r.stderr,
    ))

    # 2. production + JWT secret set -> boots (SQLite default only warns).
    r = run({"SPENCER_ENV": "production", "SPENCER_JWT_SECRET": "x" * 40})
    checks.append((
        "prod + JWT secret boots",
        r.returncode == 0 and "BOOTED_OK" in r.stdout,
    ))

    # 3. production + JWT secret + Postgres URL -> boots cleanly, no SQLite warning.
    r = run({
        "SPENCER_ENV": "production",
        "SPENCER_JWT_SECRET": "x" * 40,
        "SPENCER_APP_DB_URL": "postgresql+psycopg://u:p@db:5432/s",
    })
    checks.append((
        "prod + Postgres boots cleanly (no SQLite warning)",
        r.returncode == 0 and "BOOTED_OK" in r.stdout and "SQLite" not in r.stderr,
    ))

    # 4. development (default, no SPENCER_ENV) + no secret -> boots (permissive).
    r = run({})
    checks.append((
        "dev default boots on the fallback key",
        r.returncode == 0 and "BOOTED_OK" in r.stdout,
    ))

    passed = sum(1 for _, ok in checks if ok)
    for name, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    print(f"RESULT: {passed}/{len(checks)} checks passed")
    sys.exit(0 if passed == len(checks) else 1)


if __name__ == "__main__":
    main()
