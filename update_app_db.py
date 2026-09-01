import sys

with open('backend/services/app_db.py', 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace("Base.metadata.create_all(engine)", "# Base.metadata.create_all(engine) # Replaced by Alembic migrations")

with open('backend/services/app_db.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("Commented out create_all in app_db.py")
