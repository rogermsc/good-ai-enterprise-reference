"""
Database connection management.

Provides async connection pooling for PostgreSQL using asyncpg.
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

import asyncpg

from src.core.config import get_settings


class DatabasePool:
    """
    Manages PostgreSQL connection pool.

    Usage:
        pool = DatabasePool()
        await pool.initialize()

        async with pool.connection() as conn:
            await conn.execute("SELECT 1")

        await pool.close()
    """

    def __init__(self, database_url: str | None = None):
        """
        Initialize database pool.

        Args:
            database_url: PostgreSQL connection URL, defaults to settings
        """
        settings = get_settings()
        self._database_url = database_url or settings.database_url
        self._pool: asyncpg.Pool | None = None

    async def initialize(self) -> None:
        """Create connection pool."""
        if self._pool is not None:
            return

        settings = get_settings()
        self._pool = await asyncpg.create_pool(
            self._database_url,
            min_size=2,
            max_size=settings.database_pool_size,
        )

    async def close(self) -> None:
        """Close connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None

    @asynccontextmanager
    async def connection(self) -> AsyncGenerator[asyncpg.Connection, None]:
        """
        Get a connection from the pool.

        Yields:
            asyncpg.Connection
        """
        if self._pool is None:
            await self.initialize()

        assert self._pool is not None  # for type checker

        async with self._pool.acquire() as conn:
            yield conn

    async def execute(self, query: str, *args) -> str:
        """Execute a query without returning results."""
        async with self.connection() as conn:
            return await conn.execute(query, *args)

    async def fetch(self, query: str, *args) -> list[asyncpg.Record]:
        """Execute a query and return all results."""
        async with self.connection() as conn:
            return await conn.fetch(query, *args)

    async def fetchrow(self, query: str, *args) -> asyncpg.Record | None:
        """Execute a query and return first result."""
        async with self.connection() as conn:
            return await conn.fetchrow(query, *args)


# Global pool instance
_pool: DatabasePool | None = None


async def create_pool() -> DatabasePool:
    """Create and initialize global database pool."""
    global _pool
    if _pool is None:
        _pool = DatabasePool()
        await _pool.initialize()
    return _pool


async def get_pool() -> DatabasePool:
    """Get global database pool, creating if needed."""
    return await create_pool()


@asynccontextmanager
async def get_connection() -> AsyncGenerator[asyncpg.Connection, None]:
    """
    Get a database connection from the global pool.

    Usage:
        async with get_connection() as conn:
            await conn.execute("SELECT 1")
    """
    pool = await get_pool()
    async with pool.connection() as conn:
        yield conn


async def close_pool() -> None:
    """Close global database pool."""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
