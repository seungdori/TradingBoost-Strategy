"""
Redis client helper module for unified Redis access across the application.

This module provides a singleton Redis client instance to avoid repeated
imports and ensure consistent Redis access patterns throughout the codebase.
"""

from functools import lru_cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import redis.asyncio as redis


@lru_cache(maxsize=1)
def get_redis_client() -> "redis.Redis":
    """
    Get singleton Redis client instance.

    Uses lazy import to avoid circular dependencies and import-time errors.
    The lru_cache decorator ensures only one instance is created and reused.

    Returns:
        redis.Redis: Configured Redis client for the HYPERRSI application

    Raises:
        ImportError: If database module cannot be imported
        AttributeError: If redis_client is not available in database module

    Example:
        >>> from shared.database.redis_helper import get_redis_client
        >>> redis = get_redis_client()
        >>> await redis.ping()
        True

    Note:
        This function uses dynamic import to avoid import-time circular dependencies.
        The Redis client is configured in HYPERRSI.src.core.database module.
    """
    from HYPERRSI.src.core import database as db_module
    return db_module.redis_client
