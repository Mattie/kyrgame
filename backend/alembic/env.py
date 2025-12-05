import os
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool

from alembic import context

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from kyrgame import models  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

section = config.get_section(config.config_ini_section)
database_url = os.getenv("DATABASE_URL")
if database_url:
    section["sqlalchemy.url"] = database_url


target_metadata = models.Base.metadata


def run_migrations_offline():
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connection = config.attributes.get("connection")
    if connection is None:
        connectable = engine_from_config(
            section,
            prefix="sqlalchemy.",
            poolclass=pool.NullPool,
        )
        connection = connectable.connect()

    with connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
