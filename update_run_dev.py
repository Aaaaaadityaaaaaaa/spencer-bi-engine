import sys
import re

with open('backend/run_dev.py', 'r', encoding='utf-8') as f:
    content = f.read()

alembic_call = """
# Run database migrations before starting the server
print("Running Alembic migrations...")
migration_code = subprocess.call([sys.executable, "-m", "alembic", "upgrade", "head"])
if migration_code != 0:
    print("Database migration failed. Exiting.")
    sys.exit(migration_code)

sys.exit(
"""
content = content.replace("sys.exit(\n", alembic_call)

with open('backend/run_dev.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("Updated run_dev.py with alembic upgrade head")
