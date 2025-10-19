"""
Unified Redis Pattern Utilities for TradingBoost-Strategy

This module provides standardized patterns for Redis operations across HYPERRSI and GRID strategies.
All patterns follow async/await conventions and proper resource management.

Author: Redis Architecture Improvement Initiative
Created: 2025-10-19
"""

import json
import time
import hashlib
from contextlib import asynccontextmanager
from functools import wraps
from typing import AsyncIterator, Any, Callable, Dict, List, Optional, Tuple, TypeVar, Union
from redis.asyncio import Redis as AsyncRedis
from redis.exceptions import RedisError, ConnectionError, TimeoutError, WatchError

from shared.logging import get_logger
from shared.database.redis import get_redis

logger = get_logger(__name__)

# =============================================================================
# TTL Constants - Centralized expiration times
# =============================================================================

class RedisTTL:
    """Centralized TTL constants for different data types"""
    # User data
    USER_DATA = 60 * 60 * 24 * 30  # 30 days
    USER_SESSION = 60 * 60 * 24  # 1 day
    USER_SETTINGS = 60 * 60 * 24 * 7  # 7 days

    # Trading data
    PRICE_DATA = 60 * 60  # 1 hour
    ORDER_DATA = 60 * 60 * 24 * 7  # 7 days
    POSITION_DATA = 60 * 60 * 24 * 30  # 30 days

    # Cache data
    CACHE_SHORT = 60 * 5  # 5 minutes
    CACHE_MEDIUM = 60 * 30  # 30 minutes
    CACHE_LONG = 60 * 60 * 2  # 2 hours

    # Temporary data
    TEMP_DATA = 60 * 15  # 15 minutes
    LOCK_DATA = 60  # 1 minute


# =============================================================================
# Context Manager Pattern - Recommended for all service/utility functions
# =============================================================================

@asynccontextmanager
async def redis_context() -> AsyncIterator[AsyncRedis]:
    """
    Context manager for Redis operations with proper cleanup.

    Usage:
        async with redis_context() as redis:
            await redis.set("key", "value")

    This ensures connections are properly returned to the pool.
    """
    redis = await get_redis()
    try:
        yield redis
    except ConnectionError as e:
        logger.error("Redis connection failed", exc_info=True)
        raise
    except TimeoutError as e:
        logger.warning("Redis operation timed out", exc_info=True)
        raise
    except RedisError as e:
        logger.error("Redis operation failed", exc_info=True)
        raise
    finally:
        # Close returns connection to pool
        await redis.close()


# =============================================================================
# Pipeline Pattern - For batch operations
# =============================================================================

@asynccontextmanager
async def redis_pipeline(transaction: bool = True) -> AsyncIterator:
    """
    Context manager for Redis pipeline operations.

    Args:
        transaction: If True, use MULTI/EXEC for atomic operations

    Usage:
        async with redis_pipeline() as pipe:
            pipe.set("key1", "value1")
            pipe.set("key2", "value2")
            results = await pipe.execute()
    """
    async with redis_context() as redis:
        pipe = redis.pipeline(transaction=transaction)
        try:
            yield pipe
        finally:
            # Pipeline cleanup handled by context manager
            pass


# =============================================================================
# Caching Decorator - Auto-caching for expensive operations
# =============================================================================

T = TypeVar('T')

def redis_cache(
    ttl: int = RedisTTL.CACHE_MEDIUM,
    key_prefix: str = "cache",
    skip_none: bool = True
) -> Callable:
    """
    Decorator for automatic Redis caching of function results.

    Args:
        ttl: Cache expiration time in seconds
        key_prefix: Prefix for cache keys
        skip_none: If True, don't cache None results

    Usage:
        @redis_cache(ttl=3600, key_prefix="user_data")
        async def get_expensive_data(user_id: str) -> dict:
            # Expensive operation
            return await fetch_from_db(user_id)
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            # Generate cache key from function name and arguments
            args_str = f"{args}:{sorted(kwargs.items())}"
            cache_key_hash = hashlib.md5(args_str.encode()).hexdigest()
            cache_key = f"{key_prefix}:{func.__name__}:{cache_key_hash}"

            async with redis_context() as redis:
                # Try to get from cache
                cached = await redis.get(cache_key)
                if cached:
                    logger.debug(f"Cache hit: {cache_key}")
                    try:
                        return json.loads(cached)
                    except json.JSONDecodeError:
                        logger.warning(f"Failed to decode cached value for {cache_key}")
                        # Fall through to execute function

                # Cache miss - execute function
                logger.debug(f"Cache miss: {cache_key}")
                result = await func(*args, **kwargs)

                # Store in cache (skip if None and skip_none=True)
                if result is not None or not skip_none:
                    try:
                        await redis.setex(cache_key, ttl, json.dumps(result))
                    except (TypeError, json.JSONEncodeError) as e:
                        logger.warning(f"Failed to cache result for {cache_key}: {e}")

                return result
        return wrapper
    return decorator


# =============================================================================
# Safe Operation Wrapper - Comprehensive error handling
# =============================================================================

async def safe_redis_operation(
    operation: Callable,
    *args,
    default: Any = None,
    log_errors: bool = True,
    raise_on_error: bool = False,
    **kwargs
) -> Any:
    """
    Safely execute a Redis operation with comprehensive error handling.

    Args:
        operation: Redis operation to execute (async function)
        *args: Arguments for the operation
        default: Default value to return on error
        log_errors: Whether to log errors
        raise_on_error: Whether to raise exceptions or return default
        **kwargs: Keyword arguments for the operation

    Returns:
        Operation result or default value on error

    Usage:
        result = await safe_redis_operation(
            redis.get,
            "key",
            default="",
            log_errors=True
        )
    """
    try:
        return await operation(*args, **kwargs)
    except ConnectionError as e:
        if log_errors:
            logger.error("Redis connection failed", exc_info=True)
        if raise_on_error:
            raise
        return default
    except TimeoutError as e:
        if log_errors:
            logger.warning(f"Redis operation timed out", exc_info=True)
        if raise_on_error:
            raise
        return default
    except RedisError as e:
        if log_errors:
            logger.error("Redis operation failed", exc_info=True)
        if raise_on_error:
            raise
        return default


# =============================================================================
# SCAN Iterator - Replaces blocking KEYS command
# =============================================================================

async def scan_keys_pattern(
    pattern: str,
    count: int = 100,
    redis: Optional[AsyncRedis] = None
) -> List[str]:
    """
    Iterate over keys matching a pattern using SCAN (non-blocking).

    This replaces the blocking KEYS command with SCAN for production safety.

    Args:
        pattern: Pattern to match (e.g., "user:*")
        count: Number of keys to return per SCAN iteration
        redis: Redis client (if None, creates new connection)

    Returns:
        List of matching keys

    Usage:
        keys = await scan_keys_pattern("user:*")

    Note: This is much safer than KEYS for production use as it doesn't
          block the Redis server.
    """
    all_keys = []
    cursor = 0

    # Use provided connection or create new one
    if redis is None:
        async with redis_context() as redis:
            return await scan_keys_pattern(pattern, count, redis)

    # SCAN iteration
    while True:
        try:
            cursor, keys = await redis.scan(
                cursor=cursor,
                match=pattern,
                count=count
            )
            all_keys.extend(keys)

            if cursor == 0:
                break
        except RedisError as e:
            logger.error(f"SCAN failed for pattern {pattern}", exc_info=True)
            break

    logger.debug(f"SCAN found {len(all_keys)} keys for pattern {pattern}")
    return all_keys


# =============================================================================
# Transaction Support - Atomic operations with WATCH
# =============================================================================

@asynccontextmanager
async def redis_transaction(watch_keys: Optional[List[str]] = None) -> AsyncIterator:
    """
    Context manager for Redis transactions with optimistic locking.

    Args:
        watch_keys: Keys to watch for changes (optimistic locking)

    Usage:
        async with redis_transaction(watch_keys=["user:123"]) as pipe:
            # Read current value
            current = await pipe.get("user:123")

            # Start transaction
            pipe.multi()
            pipe.set("user:123", new_value)
            pipe.incr("user:123:version")

            # Execute atomically
            await pipe.execute()

    Raises:
        WatchError: If watched keys were modified during transaction
    """
    async with redis_context() as redis:
        pipe = redis.pipeline(transaction=True)

        try:
            # Watch keys for changes
            if watch_keys:
                await pipe.watch(*watch_keys)

            yield pipe

        except WatchError:
            logger.warning(f"Transaction aborted - watched keys modified: {watch_keys}")
            raise
        finally:
            # Unwatch all keys
            await pipe.unwatch()


# =============================================================================
# Batch Operations - Efficient multi-key operations
# =============================================================================

async def batch_set_with_ttl(
    key_values: Dict[str, Any],
    ttl: int = RedisTTL.USER_DATA,
    redis: Optional[AsyncRedis] = None
) -> bool:
    """
    Efficiently set multiple keys with TTL using pipeline.

    Args:
        key_values: Dictionary of key-value pairs
        ttl: Expiration time in seconds
        redis: Redis client (if None, creates new connection)

    Returns:
        True if successful

    Usage:
        await batch_set_with_ttl({
            "user:1": json.dumps(user1_data),
            "user:2": json.dumps(user2_data)
        }, ttl=3600)
    """
    if not key_values:
        return True

    # Use provided connection or create new one
    if redis is None:
        async with redis_context() as redis:
            return await batch_set_with_ttl(key_values, ttl, redis)

    try:
        async with redis.pipeline(transaction=False) as pipe:
            for key, value in key_values.items():
                pipe.set(key, value)
                pipe.expire(key, ttl)

            await pipe.execute()
            logger.debug(f"Batch set {len(key_values)} keys with TTL {ttl}s")
            return True

    except RedisError as e:
        logger.error("Batch set operation failed", exc_info=True)
        return False


async def batch_get(
    keys: List[str],
    redis: Optional[AsyncRedis] = None
) -> Dict[str, Optional[str]]:
    """
    Efficiently get multiple keys using MGET.

    Args:
        keys: List of keys to retrieve
        redis: Redis client (if None, creates new connection)

    Returns:
        Dictionary mapping keys to values (None if key doesn't exist)

    Usage:
        results = await batch_get(["user:1", "user:2", "user:3"])
    """
    if not keys:
        return {}

    # Use provided connection or create new one
    if redis is None:
        async with redis_context() as redis:
            return await batch_get(keys, redis)

    try:
        values = await redis.mget(keys)
        return dict(zip(keys, values))
    except RedisError as e:
        logger.error("Batch get operation failed", exc_info=True)
        return {key: None for key in keys}


# =============================================================================
# Key Expiration Utilities
# =============================================================================

async def set_key_ttl(
    key: str,
    ttl: int,
    redis: Optional[AsyncRedis] = None
) -> bool:
    """
    Set TTL on an existing key.

    Args:
        key: Key to set TTL on
        ttl: Expiration time in seconds
        redis: Redis client (if None, creates new connection)

    Returns:
        True if TTL was set, False otherwise
    """
    if redis is None:
        async with redis_context() as redis:
            return await set_key_ttl(key, ttl, redis)

    try:
        return await redis.expire(key, ttl)
    except RedisError as e:
        logger.error(f"Failed to set TTL for key {key}", exc_info=True)
        return False


async def batch_set_ttl(
    keys: List[str],
    ttl: int,
    redis: Optional[AsyncRedis] = None
) -> int:
    """
    Set TTL on multiple existing keys using pipeline.

    Args:
        keys: List of keys to set TTL on
        ttl: Expiration time in seconds
        redis: Redis client (if None, creates new connection)

    Returns:
        Number of keys that had TTL set successfully
    """
    if not keys:
        return 0

    if redis is None:
        async with redis_context() as redis:
            return await batch_set_ttl(keys, ttl, redis)

    try:
        async with redis.pipeline(transaction=False) as pipe:
            for key in keys:
                pipe.expire(key, ttl)

            results = await pipe.execute()
            success_count = sum(1 for result in results if result)
            logger.debug(f"Set TTL on {success_count}/{len(keys)} keys")
            return success_count

    except RedisError as e:
        logger.error("Batch TTL operation failed", exc_info=True)
        return 0


# =============================================================================
# Health Check Utility
# =============================================================================

async def redis_health_check(redis: Optional[AsyncRedis] = None) -> Dict[str, Any]:
    """
    Perform Redis health check and return connection status.

    Args:
        redis: Redis client (if None, creates new connection)

    Returns:
        Dictionary with health check results

    Usage:
        health = await redis_health_check()
        if health["status"] == "healthy":
            print("Redis is operational")
    """
    if redis is None:
        async with redis_context() as redis:
            return await redis_health_check(redis)

    start_time = time.time()

    try:
        # Ping Redis
        await redis.ping()
        latency_ms = (time.time() - start_time) * 1000

        # Get server info
        info = await redis.info()

        return {
            "status": "healthy",
            "latency_ms": round(latency_ms, 2),
            "connected_clients": info.get("connected_clients", 0),
            "used_memory_human": info.get("used_memory_human", "unknown"),
            "uptime_seconds": info.get("uptime_in_seconds", 0),
            "redis_version": info.get("redis_version", "unknown")
        }

    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e),
            "error_type": type(e).__name__
        }


# =============================================================================
# Pattern Examples & Usage Documentation
# =============================================================================

"""
=== USAGE EXAMPLES ===

1. CONTEXT MANAGER (Recommended for services/utilities):

    async def my_service_function(user_id: str):
        async with redis_context() as redis:
            user_data = await redis.hgetall(f"user:{user_id}")
            return user_data

2. FASTAPI DEPENDENCY INJECTION (Recommended for API routes):

    from fastapi import Depends
    from shared.database.redis import get_redis

    @router.get("/user/{user_id}")
    async def get_user(user_id: str, redis: AsyncRedis = Depends(get_redis)):
        data = await redis.hgetall(f"user:{user_id}")
        return data

3. CACHING DECORATOR:

    @redis_cache(ttl=3600, key_prefix="expensive_calc")
    async def expensive_calculation(param1: str, param2: int) -> dict:
        # This result will be cached for 1 hour
        result = await complex_operation(param1, param2)
        return result

4. SCAN INSTEAD OF KEYS:

    # ❌ DON'T: This blocks Redis server
    keys = await redis.keys("user:*")

    # ✅ DO: This is non-blocking
    keys = await scan_keys_pattern("user:*")

5. BATCH OPERATIONS:

    # Set multiple keys with TTL
    await batch_set_with_ttl({
        "user:1": json.dumps(data1),
        "user:2": json.dumps(data2)
    }, ttl=RedisTTL.USER_DATA)

    # Get multiple keys
    results = await batch_get(["user:1", "user:2", "user:3"])

6. ATOMIC TRANSACTIONS:

    async with redis_transaction(watch_keys=["counter"]) as pipe:
        current = await pipe.get("counter")
        new_value = int(current) + 1

        pipe.multi()
        pipe.set("counter", new_value)
        await pipe.execute()

7. SAFE OPERATIONS WITH FALLBACK:

    user_data = await safe_redis_operation(
        redis.hgetall,
        "user:123",
        default={},
        log_errors=True
    )

=== ERROR HANDLING ===

All patterns include comprehensive error handling for:
- ConnectionError: Redis server unreachable
- TimeoutError: Operation took too long
- RedisError: General Redis errors
- WatchError: Transaction conflicts

Errors are logged with appropriate severity and context.

=== MIGRATION GUIDE ===

OLD PATTERN:
    redis = await get_redis_connection()
    await redis.set(key, value)

NEW PATTERN:
    async with redis_context() as redis:
        await redis.set(key, value)

Benefits:
- Explicit connection lifecycle management
- Automatic cleanup on exceptions
- Better error handling
- Connection pool efficiency
"""
