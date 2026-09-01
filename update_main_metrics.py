import sys
import re

with open('backend/main.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Add imports
imports = """from fastapi import FastAPI, HTTPException, Request, Response
import logger # initializes structured logging
from middleware.metrics import RequestTracingMiddleware
from routers import dashboard, session, ai, query, schedule, admin, auth, health
"""
content = re.sub(r'from fastapi import FastAPI.*?\nfrom routers import.*?\n', imports, content, flags=re.MULTILINE)

# Add middleware
middleware = """
app = FastAPI(title="Spencer BI Engine", version="0.1.0")

app.add_middleware(RequestTracingMiddleware)
"""
content = content.replace('app = FastAPI(title="Spencer BI Engine", version="0.1.0")', middleware)

# Add router
router = """
app.include_router(health.router, tags=["Health"])
app.include_router(auth.router, prefix="/api/auth", tags=["Auth"])
"""
content = content.replace('app.include_router(auth.router, prefix="/api/auth", tags=["Auth"])', router)

with open('backend/main.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("Updated main.py")
