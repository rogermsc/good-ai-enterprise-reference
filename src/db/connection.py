"""
Database connection management.

Provides async connection pooling for PostgreSQL using asyncpg.

This module uses a singleton pattern for the global pool but provides
proper accessor functions to make testing easier. In tests, use
`reset_pool()` to clear state between tests.
"""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

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

    async def execute(self, query: str, *args: object) -> str:
        """Execute a query without returning results."""
        async with self.connection() as conn:
            result: str = await conn.execute(query, *args)
            return result

    async def fetch(self, query: str, *args: object) -> list[asyncpg.Record]:
        """Execute a query and return all results."""
        async with self.connection() as conn:
            result: list[asyncpg.Record] = await conn.fetch(query, *args)
            return result

    async def fetchrow(self, query: str, *args: object) -> asyncpg.Record | None:
        """Execute a query and return first result."""
        async with self.connection() as conn:
            return await conn.fetchrow(query, *args)


# Global pool instance with lock for thread safety
_pool: DatabasePool | None = None
_pool_lock: asyncio.Lock | None = None


def _get_lock() -> asyncio.Lock:
    """Get or create the pool lock."""
    global _pool_lock
    if _pool_lock is None:
        _pool_lock = asyncio.Lock()
    return _pool_lock


async def create_pool(database_url: str | None = None) -> DatabasePool:
    """
    Create and initialize global database pool.

    Args:
        database_url: Optional custom database URL. If not provided,
                     uses the URL from settings.

    Returns:
        Initialized DatabasePool instance
    """
    global _pool
    async with _get_lock():
        if _pool is None:
            _pool = DatabasePool(database_url)
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
    async with _get_lock():
        if _pool:
            await _pool.close()
            _pool = None


async def reset_pool() -> None:
    """
    Reset the global pool (for testing).

    This closes any existing pool and clears the global state,
    allowing tests to start with a fresh pool.
    """
    await close_pool()


def set_pool(pool: DatabasePool | None) -> None:
    """
    Set the global pool directly (for testing).

    Args:
        pool: DatabasePool instance or None to clear
    """
    global _pool
    _pool = pool
