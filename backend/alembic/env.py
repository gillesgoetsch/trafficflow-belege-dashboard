"""Alembic environment — async-aware, picks DATABASE_URL from app settings."""
from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.config import settings
from app.db.base import Base
from app.db import models  # noqa: F401 -- register all models

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

# Alembic needs a sync-style URL for offline mode but we use async at runtime.
sync_url = settings.database_url.replace("+psycopg", "+psycopg").replace(
    "postgresql+asyncpg", "postgresql+psycopg"
)
config.set_main_option("sqlalchemy.url", sync_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=sync_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    async_url = sync_url.replace("postgresql+psycopg", "postgresql+asyncpg")
    connectable = async_engine_from_config(
        {"sqlalchemy.url": async_url},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
