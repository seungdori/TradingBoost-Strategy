"""
Redis Helper Functions - Standardized timeout-protected operations

This module provides convenient wrapper functions for common Redis operations
with standardized timeout protection and error handling.

All functions use timeout constants from redis_patterns.RedisTimeout to ensure
consistency across the codebase.

Usage:
    from shared.database.redis_helpers import safe_get, safe_hgetall, safe_set

    # Get with automatic timeout
    value = await safe_get(redis, "my:key")

    # Hash operations
    data = await safe_hgetall(redis, "user:123")

    # Set with TTL
    await safe_set(redis, "cache:key", "value", ttl=300)
"""

import asyncio
from typing import Any, Dict, List, Optional, Union

from redis.asyncio import Redis

from shared.database.redis_patterns import RedisTimeout
from shared.logging import get_logger

logger = get_logger(__name__)


# ==================== Basic Operations ====================

async def safe_get(
    redis: Redis,
    key: str,
    default: Any = None,
    timeout: float = RedisTimeout.FAST_OPERATION
) -> Optional[str]:
    """
    Get a key with timeout protection.

    Args:
        redis: Redis client instance
        key: Redis key
        default: Default value if key doesn't exist
        timeout: Operation timeout in seconds

    Returns:
        Value from Redis or default
    """
    try:
        value = await asyncio.wait_for(redis.get(key), timeout=timeout)
        return value if value is not None else default
    except asyncio.TimeoutError:
        logger.warning(f"Timeout getting key: {key} (timeout={timeout}s)")
        return default
    except Exception as e:
        logger.error(f"Error getting key {key}: {e}")
        return default


async def safe_set(
    redis: Redis,
    key: str,
    value: Union[str, bytes],
    ttl: Optional[int] = None,
    timeout: float = RedisTimeout.FAST_OPERATION
) -> bool:
    """
    Set a key with timeout protection and optional TTL.

    Args:
        redis: Redis client instance
        key: Redis key
        value: Value to set
        ttl: Time to live in seconds (optional)
        timeout: Operation timeout in seconds

    Returns:
        True if successful, False otherwise
    """
    try:
        if ttl:
            await asyncio.wait_for(redis.setex(key, ttl, value), timeout=timeout)
        else:
            await asyncio.wait_for(redis.set(key, value), timeout=timeout)
        return True
    except asyncio.TimeoutError:
        logger.warning(f"Timeout setting key: {key} (timeout={timeout}s)")
        return False
    except Exception as e:
        logger.error(f"Error setting key {key}: {e}")
        return False


async def safe_delete(
    redis: Redis,
    *keys: str,
    timeout: float = RedisTimeout.FAST_OPERATION
) -> int:
    """
    Delete one or more keys with timeout protection.

    Args:
        redis: Redis client instance
        *keys: Keys to delete
        timeout: Operation timeout in seconds

    Returns:
        Number of keys deleted
    """
    try:
        count = await asyncio.wait_for(redis.delete(*keys), timeout=timeout)
        return int(count)
    except asyncio.TimeoutError:
        logger.warning(f"Timeout deleting keys: {keys} (timeout={timeout}s)")
        return 0
    except Exception as e:
        logger.error(f"Error deleting keys {keys}: {e}")
        return 0


async def safe_exists(
    redis: Redis,
    *keys: str,
    timeout: float = RedisTimeout.FAST_OPERATION
) -> int:
    """
    Check if keys exist with timeout protection.

    Args:
        redis: Redis client instance
        *keys: Keys to check
        timeout: Operation timeout in seconds

    Returns:
        Number of existing keys
    """
    try:
        count = await asyncio.wait_for(redis.exists(*keys), timeout=timeout)
        return int(count)
    except asyncio.TimeoutError:
        logger.warning(f"Timeout checking existence of keys: {keys} (timeout={timeout}s)")
        return 0
    except Exception as e:
        logger.error(f"Error checking keys {keys}: {e}")
        return 0


# ==================== Hash Operations ====================

async def safe_hget(
    redis: Redis,
    key: str,
    field: str,
    default: Any = None,
    timeout: float = RedisTimeout.NORMAL_OPERATION
) -> Optional[str]:
    """
    Get hash field with timeout protection.

    Args:
        redis: Redis client instance
        key: Hash key
        field: Field name
        default: Default value if field doesn't exist
        timeout: Operation timeout in seconds

    Returns:
        Field value or default
    """
    try:
        value = await asyncio.wait_for(redis.hget(key, field), timeout=timeout)
        return value if value is not None else default
    except asyncio.TimeoutError:
        logger.warning(f"Timeout getting hash field: {key}:{field} (timeout={timeout}s)")
        return default
    except Exception as e:
        logger.error(f"Error getting hash field {key}:{field}: {e}")
        return default


async def safe_hgetall(
    redis: Redis,
    key: str,
    default: Optional[Dict] = None,
    timeout: float = RedisTimeout.NORMAL_OPERATION
) -> Dict[str, str]:
    """
    Get all hash fields with timeout protection.

    Args:
        redis: Redis client instance
        key: Hash key
        default: Default value if hash doesn't exist
        timeout: Operation timeout in seconds

    Returns:
        Hash contents or default
    """
    try:
        data = await asyncio.wait_for(redis.hgetall(key), timeout=timeout)
        return dict(data) if data else (default or {})
    except asyncio.TimeoutError:
        logger.warning(f"Timeout getting hash: {key} (timeout={timeout}s)")
        return default or {}
    except Exception as e:
        logger.error(f"Error getting hash {key}: {e}")
        return default or {}


async def safe_hset(
    redis: Redis,
    key: str,
    field: str,
    value: Union[str, bytes],
    timeout: float = RedisTimeout.NORMAL_OPERATION
) -> bool:
    """
    Set hash field with timeout protection.

    Args:
        redis: Redis client instance
        key: Hash key
        field: Field name
        value: Field value
        timeout: Operation timeout in seconds

    Returns:
        True if successful, False otherwise
    """
    try:
        await asyncio.wait_for(redis.hset(key, field, value), timeout=timeout)
        return True
    except asyncio.TimeoutError:
        logger.warning(f"Timeout setting hash field: {key}:{field} (timeout={timeout}s)")
        return False
    except Exception as e:
        logger.error(f"Error setting hash field {key}:{field}: {e}")
        return False


async def safe_hmset(
    redis: Redis,
    key: str,
    mapping: Dict[str, Union[str, bytes]],
    ttl: Optional[int] = None,
    timeout: float = RedisTimeout.NORMAL_OPERATION
) -> bool:
    """
    Set multiple hash fields with timeout protection and optional TTL.

    Uses pipeline for atomic operation when TTL is specified.

    Args:
        redis: Redis client instance
        key: Hash key
        mapping: Field-value mapping
        ttl: Time to live in seconds (optional)
        timeout: Operation timeout in seconds

    Returns:
        True if successful, False otherwise
    """
    try:
        if ttl:
            # Use pipeline for atomic TTL setting
            async with redis.pipeline(transaction=True) as pipe:
                pipe.hset(key, mapping=mapping)
                pipe.expire(key, ttl)
                await asyncio.wait_for(pipe.execute(), timeout=timeout)
        else:
            await asyncio.wait_for(redis.hset(key, mapping=mapping), timeout=timeout)
        return True
    except asyncio.TimeoutError:
        logger.warning(f"Timeout setting hash: {key} (timeout={timeout}s)")
        return False
    except Exception as e:
        logger.error(f"Error setting hash {key}: {e}")
        return False


# ==================== List Operations ====================

async def safe_lpush(
    redis: Redis,
    key: str,
    *values: Union[str, bytes],
    timeout: float = RedisTimeout.FAST_OPERATION
) -> int:
    """
    Push values to list head with timeout protection.

    Args:
        redis: Redis client instance
        key: List key
        *values: Values to push
        timeout: Operation timeout in seconds

    Returns:
        Length of list after push, or 0 on error
    """
    try:
        length = await asyncio.wait_for(redis.lpush(key, *values), timeout=timeout)
        return int(length)
    except asyncio.TimeoutError:
        logger.warning(f"Timeout pushing to list: {key} (timeout={timeout}s)")
        return 0
    except Exception as e:
        logger.error(f"Error pushing to list {key}: {e}")
        return 0


async def safe_lrange(
    redis: Redis,
    key: str,
    start: int = 0,
    end: int = -1,
    timeout: float = RedisTimeout.NORMAL_OPERATION
) -> List[str]:
    """
    Get list range with timeout protection.

    Args:
        redis: Redis client instance
        key: List key
        start: Start index
        end: End index (-1 for all)
        timeout: Operation timeout in seconds

    Returns:
        List elements or empty list
    """
    try:
        items = await asyncio.wait_for(redis.lrange(key, start, end), timeout=timeout)
        return list(items)
    except asyncio.TimeoutError:
        logger.warning(f"Timeout getting list range: {key} (timeout={timeout}s)")
        return []
    except Exception as e:
        logger.error(f"Error getting list range {key}: {e}")
        return []


# ==================== Advanced Operations ====================

async def safe_ping(
    redis: Redis,
    timeout: float = RedisTimeout.FAST_OPERATION
) -> bool:
    """
    Ping Redis with timeout protection.

    Args:
        redis: Redis client instance
        timeout: Operation timeout in seconds

    Returns:
        True if ping successful, False otherwise
    """
    try:
        result = await asyncio.wait_for(redis.ping(), timeout=timeout)
        return bool(result)
    except asyncio.TimeoutError:
        logger.warning(f"Redis ping timeout (timeout={timeout}s)")
        return False
    except Exception as e:
        logger.error(f"Redis ping error: {e}")
        return False


async def safe_incr(
    redis: Redis,
    key: str,
    amount: int = 1,
    timeout: float = RedisTimeout.FAST_OPERATION
) -> Optional[int]:
    """
    Increment key with timeout protection.

    Args:
        redis: Redis client instance
        key: Key to increment
        amount: Amount to increment by
        timeout: Operation timeout in seconds

    Returns:
        New value after increment, or None on error
    """
    try:
        if amount == 1:
            value = await asyncio.wait_for(redis.incr(key), timeout=timeout)
        else:
            value = await asyncio.wait_for(redis.incrby(key, amount), timeout=timeout)
        return int(value)
    except asyncio.TimeoutError:
        logger.warning(f"Timeout incrementing key: {key} (timeout={timeout}s)")
        return None
    except Exception as e:
        logger.error(f"Error incrementing key {key}: {e}")
        return None


async def safe_expire(
    redis: Redis,
    key: str,
    ttl: int,
    timeout: float = RedisTimeout.FAST_OPERATION
) -> bool:
    """
    Set key expiration with timeout protection.

    Args:
        redis: Redis client instance
        key: Key to set expiration on
        ttl: Time to live in seconds
        timeout: Operation timeout in seconds

    Returns:
        True if successful, False otherwise
    """
    try:
        result = await asyncio.wait_for(redis.expire(key, ttl), timeout=timeout)
        return bool(result)
    except asyncio.TimeoutError:
        logger.warning(f"Timeout setting expiration on key: {key} (timeout={timeout}s)")
        return False
    except Exception as e:
        logger.error(f"Error setting expiration on key {key}: {e}")
        return False
