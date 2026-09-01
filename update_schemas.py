import sys
import re

with open('backend/models/schemas.py', 'r', encoding='utf-8') as f:
    content = f.read()

if "from pydantic import BaseModel, Field" not in content:
    content = content.replace("from pydantic import BaseModel, ConfigDict", "from pydantic import BaseModel, ConfigDict, Field")

# Apply constraints
replacements = {
    "question: str": 'question: str = Field(..., max_length=2000)',
    "sql: str": 'sql: str = Field(..., max_length=50000)',
    "email: str": 'email: str = Field(..., max_length=255)',
    "name: str": 'name: str = Field(..., max_length=255)'
}

for old, new in replacements.items():
    # Only replace exact matching definitions (to avoid replacing e.g. "table_name: str")
    content = re.sub(r'^(\s*)' + re.escape(old) + r'$', r'\1' + new, content, flags=re.MULTILINE)

with open('backend/models/schemas.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("Updated schemas.py with max_length constraints")
