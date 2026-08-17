"""Drop-in replacement for letta.server.db that supports SQLite when no LETTA_PG_URI is set.

Letta 0.16.x ships a Postgres-only server/db.py (always uses letta_pg_uri default).
This patch restores the historical SQLite path for local/dev installs.

Installed by start_letta.sh into the Letta venv site-packages.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy import NullPool
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from letta.database_utils import get_database_uri_for_context
from letta.log import get_logger
from letta.settings import DatabaseChoice, settings

logger = get_logger(__name__)


def _build_sqlite_uri() -> str:
    letta_dir = settings.letta_dir or os.path.expanduser("~/.letta")
    os.makedirs(letta_dir, exist_ok=True)
    db_path = os.path.join(str(letta_dir), "sqlite.db")
    # aiosqlite + check_same_thread for SQLAlchemy
    return f"sqlite+aiosqlite:///{db_path}"


def _build_engine() -> AsyncEngine:
    if settings.database_engine is DatabaseChoice.POSTGRES:
        async_uri = get_database_uri_for_context(settings.letta_pg_uri, "async")
        engine_args = {
            "echo": settings.pg_echo,
            "pool_pre_ping": settings.pool_pre_ping,
        }
        if settings.disable_sqlalchemy_pooling:
            engine_args["poolclass"] = NullPool
        else:
            engine_args.update(
                {
                    "pool_size": settings.pg_pool_size,
                    "max_overflow": settings.pg_max_overflow,
                    "pool_timeout": settings.pg_pool_timeout,
                    "pool_recycle": settings.pg_pool_recycle,
                }
            )
            connect_args = {
                "timeout": settings.pg_pool_timeout,
                "prepared_statement_name_func": lambda: f"__asyncpg_{uuid.uuid4()}__",
                "statement_cache_size": 0,
                "prepared_statement_cache_size": 0,
            }
            if "sslmode" not in async_uri and "ssl" not in async_uri:
                connect_args["ssl"] = "require"
            engine_args["connect_args"] = connect_args
        logger.info("Creating postgres async engine")
        return create_async_engine(async_uri, **engine_args)

    sqlite_uri = _build_sqlite_uri()
    logger.info("Creating sqlite async engine %s", sqlite_uri)
    engine = create_async_engine(
        sqlite_uri,
        echo=settings.pg_echo,
        poolclass=NullPool,
        connect_args={"check_same_thread": False},
    )

    # Ensure sqlite_functions event listeners are registered (Engine.connect)
    try:
        from letta.orm import sqlite_functions as _sqlite_functions  # noqa: F401
    except Exception as exc:
        logger.warning("sqlite_functions import skipped: %s", exc)

    return engine


engine: AsyncEngine = _build_engine()

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

_sqlite_schema_ready = False


async def ensure_sqlite_schema() -> None:
    """Create tables for a fresh SQLite install (no alembic for SQLite)."""
    global _sqlite_schema_ready
    if _sqlite_schema_ready:
        return
    if settings.database_engine is not DatabaseChoice.SQLITE:
        _sqlite_schema_ready = True
        return
    # Import models so metadata is populated
    import letta.orm  # noqa: F401
    from letta.orm.base import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    _sqlite_schema_ready = True
    logger.info("SQLite schema ensured via create_all")


class DatabaseRegistry:
    """Dummy registry to maintain the existing interface."""

    @asynccontextmanager
    async def async_session(self) -> AsyncGenerator[AsyncSession, None]:
        max_retries = 3
        retry_delay = 0.1

        if settings.database_engine is DatabaseChoice.SQLITE:
            await ensure_sqlite_schema()

        for attempt in range(max_retries):
            try:
                async with async_session_factory() as session:
                    try:
                        yield session
                        await session.commit()
                    except asyncio.CancelledError:
                        await session.rollback()
                        raise
                    except Exception:
                        await session.rollback()
                        raise
                    finally:
                        session.expunge_all()
                        await session.close()
                return
            except ConnectionError as e:
                if attempt < max_retries - 1:
                    logger.warning(
                        "Database connection error (attempt %s/%s): %s. Retrying in %ss...",
                        attempt + 1,
                        max_retries,
                        e,
                        retry_delay,
                    )
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2
                else:
                    logger.error("Database connection failed after %s attempts: %s", max_retries, e)
                    from letta.errors import LettaServiceUnavailableError

                    raise LettaServiceUnavailableError(
                        "Database connection temporarily unavailable. Please retry your request.",
                        service_name="database",
                    ) from e


db_registry = DatabaseRegistry()


def get_db_registry() -> DatabaseRegistry:
    return db_registry


async def get_db_async() -> AsyncGenerator[AsyncSession, None]:
    async with db_registry.async_session() as session:
        yield session


async def close_db() -> None:
    await engine.dispose()
