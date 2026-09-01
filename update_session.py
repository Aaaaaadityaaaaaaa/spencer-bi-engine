import sys
import re

with open('backend/routers/session.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Add import
if 'from services.duckdb_manager import' in content:
    content = content.replace('from services.duckdb_manager import db_manager', 'from services.duckdb_manager import db_manager, current_session_id')
else:
    content = content.replace('import uuid\n', 'import uuid\nfrom services.duckdb_manager import current_session_id\n')

# Find create_session
create_session_target = """    session_uuid = str(uuid.uuid4())"""
create_session_replacement = """    session_uuid = str(uuid.uuid4())
    current_session_id.set(session_uuid)"""

content = content.replace(create_session_target, create_session_replacement)

with open('backend/routers/session.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("Updated session.py with manual ContextVar setting")
