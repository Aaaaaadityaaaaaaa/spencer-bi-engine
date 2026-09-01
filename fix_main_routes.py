import sys
import re

with open('backend/main.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Replace old health check
content = re.sub(r'@app\.get\("/health", tags=\["Admin"\]\)\ndef health_check\(\):\n    return \{"status": "ok"\}', '', content)

# Include health router
if "health.router" not in content:
    content = content.replace('app.include_router(auth.router, prefix="/auth", tags=["Auth"])', 'app.include_router(health.router, tags=["Health"])\napp.include_router(auth.router, prefix="/auth", tags=["Auth"])')

with open('backend/main.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("Fixed main.py health and metrics routing")
