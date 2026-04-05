"""Alembic environment configuration."""

from __future__ import annotations

import logging
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from bank_agent_llm.storage.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata
logger = logging.getLogger("alembic.env")


def _get_db_url() -> str:
    """Return the database URL from config.yaml if available, else alembic.ini."""
    try:
        from bank_agent_llm.config import get_settings
        return get_settings().database.url
    except Exception:
        url = config.get_main_option("sqlalchemy.url")
        if url is None:
            raise RuntimeError("No database URL found in config.yaml or alembic.ini")
        return url


def run_migrations_offline() -> None:
    context.configure(
        url=_get_db_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        {"sqlalchemy.url": _get_db_url()},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
