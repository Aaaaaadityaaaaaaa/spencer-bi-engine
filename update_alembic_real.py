import sys
import re

with open('backend/migrations/env.py', 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace("url = 'sqlite:///temp.db'", "url = config.APP_DB_URL")
content = content.replace('configuration["sqlalchemy.url"] = "sqlite:///temp.db"', 'configuration["sqlalchemy.url"] = config.APP_DB_URL')

with open('backend/migrations/env.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("Pointed env.py back to real db")
