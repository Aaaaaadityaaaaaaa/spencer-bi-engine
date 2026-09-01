import sys
import re

with open('backend/main.py', 'r', encoding='utf-8') as f:
    content = f.read()

middleware_code = """
import re
from services.duckdb_manager import current_session_id

@app.middleware("http")
async def extract_session_context(request: Request, call_next):
    # Set the ContextVar for DuckDB if this is a session route
    m = re.match(r"^/sessions/([a-f0-9\\-]{36})", request.url.path)
    if m:
        current_session_id.set(m.group(1))
    else:
        # Clear it just in case
        current_session_id.set(None)
    return await call_next(request)
"""

# Insert it before `app.include_router(auth.router, ...)`
content = content.replace('app.include_router(auth.router', middleware_code.lstrip() + '\napp.include_router(auth.router')

with open('backend/main.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("Added contextvars middleware to main.py")
