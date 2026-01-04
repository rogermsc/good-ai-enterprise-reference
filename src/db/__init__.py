"""
Database layer for the Enterprise AI Platform.

Provides connection management and schema definitions.
"""

from src.db.connection import get_connection, create_pool, DatabasePool

__all__ = [
    "get_connection",
    "create_pool",
    "DatabasePool",
]
