import sys
import re

with open('backend/migrations/env.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Add imports for config and models
imports = """
import os
import sys
# Ensure backend directory is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from logging.config import fileConfig
from sqlalchemy import engine_from_config
from sqlalchemy import pool
from alembic import context

import config
from services.app_db import Base

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config_alembic = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config_alembic.config_file_name is not None:
    fileConfig(config_alembic.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
target_metadata = Base.metadata
"""

content = re.sub(r'from logging\.config import fileConfig[\s\S]*?target_metadata = None', imports, content, flags=re.MULTILINE)

# Overwrite sqlalchemy.url with config.APP_DB_URL
run_offline = """def run_migrations_offline() -> None:
    url = config.APP_DB_URL
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()"""

run_online = """def run_migrations_online() -> None:
    configuration = config_alembic.get_section(config_alembic.config_ini_section, {})
    configuration["sqlalchemy.url"] = config.APP_DB_URL
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )
        with context.begin_transaction():
            context.run_migrations()"""

content = re.sub(r'def run_migrations_offline\(\) -> None:.*?context\.run_migrations\(\)', run_offline, content, flags=re.DOTALL)
content = re.sub(r'def run_migrations_online\(\) -> None:.*?context\.run_migrations\(\)', run_online, content, flags=re.DOTALL)

with open('backend/migrations/env.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("Configured migrations/env.py")
