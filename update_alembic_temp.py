import sys
import re

with open('backend/migrations/env.py', 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace("url = config.APP_DB_URL", "url = 'sqlite:///temp.db'")
content = content.replace('configuration["sqlalchemy.url"] = config.APP_DB_URL', 'configuration["sqlalchemy.url"] = "sqlite:///temp.db"')

with open('backend/migrations/env.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("Pointed env.py to temp.db")
