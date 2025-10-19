# Redis Usage Patterns for TradingBoost-Strategy

**Last Updated**: 2025-10-19
**Version**: 2.0 (Post-Migration)

This document provides comprehensive guidance on Redis usage patterns across the TradingBoost-Strategy monorepo (HYPERRSI and GRID strategies).

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Connection Patterns](#connection-patterns)
4. [Common Operations](#common-operations)
5. [Best Practices](#best-practices)
6. [TTL Management](#ttl-management)
7. [Error Handling](#error-handling)
8. [Performance Optimization](#performance-optimization)
9. [Monitoring & Health Checks](#monitoring--health-checks)
10. [Migration Guide](#migration-guide)
11. [Troubleshooting](#troubleshooting)

---

## Overview

### Key Improvements (2025-10-19)

The Redis infrastructure has been significantly improved with the following changes:

✅ **Unified Connection Pool** - Single shared connection pool across both strategies
✅ **Context Manager Pattern** - Proper connection cleanup with `async with`
✅ **SCAN Instead of KEYS** - Non-blocking iteration over large key sets
✅ **Automatic TTL Management** - All keys expire to prevent unbounded growth
✅ **Circuit Breaker** - Fail-fast when Redis is unavailable
✅ **Health Monitoring** - Comprehensive health check endpoints
✅ **Stale Cache Cleanup** - Automatic cleanup of expired local cache entries

### Infrastructure Components

```
shared/database/
├── redis.py              # Connection pool & circuit breaker
├── redis_patterns.py     # Utility functions & patterns
└── pool_monitor.py       # Pool health monitoring

shared/api/
└── health.py             # Health check endpoints

HYPERRSI/src/services/
└── redis_service.py      # HYPERRSI-specific Redis service

GRID/database/
└── redis_database.py     # GRID-specific Redis operations
```

---

## Architecture

### Connection Pool Design

```
┌─────────────────────────────────────────────┐
│ FastAPI Application (HYPERRSI / GRID)      │
└────────────────┬────────────────────────────┘
                 │
      ┌──────────┴──────────┐
      │  get_redis()        │  ← Dependency Injection
      └──────────┬──────────┘
                 │
      ┌──────────▼──────────────────────────────┐
      │  RedisConnectionPool (Singleton)        │
      │  - Max connections: 200                 │
      │  - Health check interval: 15s           │
      │  - Socket keepalive: enabled            │
      │  - Retry on timeout: enabled            │
      └──────────┬──────────────────────────────┘
                 │
      ┌──────────▼──────────┐
      │  Redis Server       │
      │  (localhost:6379)   │
      └─────────────────────┘
```

**Key Features:**
- Single connection pool shared across all requests
- Automatic connection recycling
- Health monitoring with latency tracking
- Circuit breaker for failure protection

---

## Connection Patterns

### Pattern 1: FastAPI Dependency Injection (Recommended for Routes)

```python
from fastapi import APIRouter, Depends
from redis.asyncio import Redis
from shared.database.redis import get_redis

router = APIRouter()

@router.get("/user/{user_id}")
async def get_user(user_id: str, redis: Redis = Depends(get_redis)):
    """
    FastAPI automatically manages connection lifecycle.
    Connection is returned to pool after request completes.
    """
    user_data = await redis.hgetall(f"user:{user_id}")
    return user_data
```

**When to use:**
- FastAPI route handlers
- API endpoints that need Redis access
- Short-lived operations

**Pros:**
- Automatic cleanup
- Clean, testable code
- FastAPI handles connection lifecycle

**Cons:**
- Only works in FastAPI context

---

### Pattern 2: Context Manager (Recommended for Services/Utilities)

```python
from shared.database.redis_patterns import redis_context

async def process_user_data(user_id: str):
    """
    Explicit connection management with context manager.
    Connection is properly released even if exceptions occur.
    """
    async with redis_context() as redis:
        user_data = await redis.hgetall(f"user:{user_id}")
        processed = transform(user_data)
        await redis.hset(f"processed:{user_id}", mapping=processed)
        return processed
```

**When to use:**
- Service layer functions
- Background tasks
- Complex operations spanning multiple Redis calls
- Non-FastAPI contexts

**Pros:**
- Explicit resource management
- Works anywhere (not limited to FastAPI)
- Guaranteed cleanup via context manager

**Cons:**
- Slightly more verbose

---

### Pattern 3: Pipeline for Batch Operations

```python
from shared.database.redis_patterns import redis_context

async def batch_update_users(users: dict[str, dict]):
    """
    Use pipeline for atomic batch operations.
    All commands execute atomically.
    """
    async with redis_context() as redis:
        async with redis.pipeline(transaction=True) as pipe:
            for user_id, data in users.items():
                pipe.hset(f"user:{user_id}", mapping=data)
                pipe.expire(f"user:{user_id}", RedisTTL.USER_DATA)

            results = await pipe.execute()

    return len(results) // 2  # 2 commands per user (hset + expire)
```

**When to use:**
- Updating multiple keys
- Atomic operations
- Performance-critical batch updates

**Pros:**
- Atomic execution
- Significantly faster than individual commands
- Reduces network round-trips

**Cons:**
- All-or-nothing execution
- Memory usage for large batches

---

### Pattern 4: Transactions with WATCH (Optimistic Locking)

```python
from shared.database.redis_patterns import redis_transaction
from redis.exceptions import WatchError

async def increment_counter_safely(counter_key: str):
    """
    Use WATCH for optimistic locking.
    Automatically retries if key changes during transaction.
    """
    max_retries = 3
    for attempt in range(max_retries):
        try:
            async with redis_transaction(watch_keys=[counter_key]) as pipe:
                # Read current value (watched)
                current = await pipe.get(counter_key)
                new_value = int(current or 0) + 1

                # Start transaction
                pipe.multi()
                pipe.set(counter_key, new_value)
                await pipe.execute()

                return new_value

        except WatchError:
            if attempt == max_retries - 1:
                raise
            await asyncio.sleep(0.01 * (2 ** attempt))  # Exponential backoff
```

**When to use:**
- Incrementing counters
- Read-modify-write operations
- Preventing race conditions

**Pros:**
- Prevents concurrent modification issues
- Better than distributed locks for high-concurrency scenarios

**Cons:**
- May require retries under high contention
- More complex than simple operations

---

## Common Operations

### Storing User Data with TTL

```python
from shared.database.redis_patterns import RedisTTL, redis_context
import json

async def save_user(exchange: str, user_id: str, user_data: dict):
    """Save user data with automatic 30-day expiration."""
    key = f"{exchange}:user:{user_id}"

    async with redis_context() as redis:
        # Serialize complex data
        serialized = {
            k: json.dumps(v) if isinstance(v, (dict, list)) else str(v)
            for k, v in user_data.items()
        }

        # Save with TTL
        await redis.hset(key, mapping=serialized)
        await redis.expire(key, RedisTTL.USER_DATA)  # 30 days
```

### Retrieving Data with Caching

```python
from shared.database.redis_patterns import redis_cache, RedisTTL

@redis_cache(ttl=RedisTTL.CACHE_MEDIUM, key_prefix="expensive_calc")
async def expensive_calculation(param1: str, param2: int) -> dict:
    """
    Result is automatically cached for 30 minutes.
    Subsequent calls with same parameters return cached result.
    """
    result = await perform_complex_operation(param1, param2)
    return result
```

### Scanning Keys (Not KEYS!)

```python
from shared.database.redis_patterns import scan_keys_pattern

async def get_all_users(exchange: str) -> list[str]:
    """
    Use SCAN instead of KEYS to avoid blocking Redis.
    Safe for production use even with millions of keys.
    """
    pattern = f"{exchange}:user:*"
    all_keys = await scan_keys_pattern(pattern, count=100)

    # Extract user IDs from keys
    user_ids = [key.split(':')[-1] for key in all_keys]
    return user_ids
```

**❌ NEVER DO THIS:**
```python
# This BLOCKS the entire Redis server!
keys = await redis.keys("user:*")  # DON'T USE KEYS!
```

### Batch Operations

```python
from shared.database.redis_patterns import batch_set_with_ttl, batch_get, RedisTTL

async def bulk_save_users(users: dict[str, dict]):
    """Save multiple users efficiently with TTL."""
    key_values = {
        f"user:{user_id}": json.dumps(data)
        for user_id, data in users.items()
    }

    await batch_set_with_ttl(key_values, ttl=RedisTTL.USER_DATA)

async def bulk_fetch_users(user_ids: list[str]) -> dict:
    """Fetch multiple users in one operation."""
    keys = [f"user:{uid}" for uid in user_ids]
    return await batch_get(keys)
```

---

## Best Practices

### 1. Always Use Context Managers

✅ **Good:**
```python
async with redis_context() as redis:
    await redis.set("key", "value")
```

❌ **Bad:**
```python
redis = await get_redis()
await redis.set("key", "value")
# Connection may leak if exception occurs!
```

### 2. Always Set TTL

✅ **Good:**
```python
await redis.hset(user_key, mapping=data)
await redis.expire(user_key, RedisTTL.USER_DATA)
```

❌ **Bad:**
```python
await redis.hset(user_key, mapping=data)
# Key persists forever → memory leak!
```

### 3. Use SCAN, Not KEYS

✅ **Good:**
```python
keys = await scan_keys_pattern("user:*")
```

❌ **Bad:**
```python
keys = await redis.keys("user:*")  # Blocks Redis!
```

### 4. Use Pipelines for Batch Operations

✅ **Good:**
```python
async with redis.pipeline() as pipe:
    for item in items:
        pipe.set(f"key:{item.id}", item.value)
    await pipe.execute()
```

❌ **Bad:**
```python
for item in items:
    await redis.set(f"key:{item.id}", item.value)
# Each call = separate network round-trip!
```

### 5. Handle Errors Gracefully

✅ **Good:**
```python
from redis.exceptions import RedisError, ConnectionError

try:
    async with redis_context() as redis:
        return await redis.get("key")
except ConnectionError:
    logger.error("Redis unavailable")
    return None  # Fallback
except RedisError as e:
    logger.error(f"Redis error: {e}")
    raise
```

---

## TTL Management

### Standard TTL Constants

```python
from shared.database.redis_patterns import RedisTTL

# User data
RedisTTL.USER_DATA        # 30 days - user settings, API keys
RedisTTL.USER_SESSION     # 1 day - active sessions
RedisTTL.USER_SETTINGS    # 7 days - user preferences

# Trading data
RedisTTL.PRICE_DATA       # 1 hour - market prices
RedisTTL.ORDER_DATA       # 7 days - order history
RedisTTL.POSITION_DATA    # 30 days - position tracking

# Cache data
RedisTTL.CACHE_SHORT      # 5 minutes - volatile data
RedisTTL.CACHE_MEDIUM     # 30 minutes - moderate caching
RedisTTL.CACHE_LONG       # 2 hours - stable data

# Temporary data
RedisTTL.TEMP_DATA        # 15 minutes - temporary state
RedisTTL.LOCK_DATA        # 1 minute - distributed locks
```

### Setting TTL on Existing Keys

```python
from shared.database.redis_patterns import batch_set_ttl

# Set TTL on single key
await redis.expire("user:123", RedisTTL.USER_DATA)

# Set TTL on multiple keys (efficient)
user_keys = ["user:1", "user:2", "user:3"]
count = await batch_set_ttl(user_keys, RedisTTL.USER_DATA)
print(f"Set TTL on {count} keys")
```

### Monitoring Keys Without TTL

```bash
# Find keys without expiration
redis-cli --scan --pattern "user:*" | while read key; do
    ttl=$(redis-cli ttl "$key")
    if [ "$ttl" -eq "-1" ]; then
        echo "No TTL: $key"
    fi
done
```

---

## Error Handling

### Circuit Breaker Pattern

```python
from shared.database.redis import get_circuit_breaker
from shared.database.redis_patterns import redis_context

async def safe_redis_operation(key: str):
    """
    Check circuit breaker before attempting Redis operation.
    Fails fast if Redis is known to be down.
    """
    breaker = get_circuit_breaker()

    if breaker.is_open():
        logger.warning("Circuit breaker OPEN - Redis unavailable")
        return None  # Fallback immediately

    try:
        async with redis_context() as redis:
            result = await redis.get(key)
            breaker.record_success()
            return result
    except RedisError as e:
        breaker.record_failure()
        logger.error(f"Redis operation failed: {e}")
        raise
```

### Retry Logic

```python
from shared.database.redis_patterns import safe_redis_operation

result = await safe_redis_operation(
    redis.get,
    "my_key",
    default="fallback_value",
    log_errors=True,
    raise_on_error=False
)
```

---

## Performance Optimization

### 1. Connection Pool Sizing

Current configuration:
- **Max connections**: 200
- **Health check interval**: 15s
- **Socket keepalive**: Enabled

Monitor pool usage:
```python
from shared.database.redis import get_pool_metrics

metrics = get_pool_metrics()
print(f"Pool size: {metrics['max_connections']}")
```

### 2. Pipeline Usage

**Single operations:**
```python
# ~10ms per operation
for i in range(100):
    await redis.set(f"key:{i}", i)
# Total: ~1000ms
```

**Pipeline:**
```python
# ~50ms total
async with redis.pipeline() as pipe:
    for i in range(100):
        pipe.set(f"key:{i}", i)
    await pipe.execute()
# Total: ~50ms (20x faster!)
```

### 3. Caching Strategy

```python
# Local cache + Redis
class CachedDataService:
    def __init__(self):
        self._local_cache = {}
        self._cache_ttl = {}

    async def get_data(self, key: str):
        # Check local cache first
        if key in self._local_cache:
            if time.time() < self._cache_ttl[key]:
                return self._local_cache[key]

        # Fetch from Redis
        async with redis_context() as redis:
            data = await redis.get(key)

        # Update local cache
        self._local_cache[key] = data
        self._cache_ttl[key] = time.time() + 300  # 5 min
        return data
```

---

## Monitoring & Health Checks

### Health Check Endpoints

```bash
# Overall health
curl http://localhost:8000/health

# Redis-specific health
curl http://localhost:8000/health/redis

# Pool metrics
curl http://localhost:8000/health/redis/pool

# Circuit breaker status
curl http://localhost:8000/health/redis/circuit-breaker
```

### Prometheus Metrics

Available metrics:
- `redis_hits_total` - Cache hit count
- `redis_misses_total` - Cache miss count
- `redis_operation_seconds` - Operation duration histogram

### Logging

```python
from shared.logging import get_logger

logger = get_logger(__name__)

async with redis_context() as redis:
    logger.debug(f"Fetching key: {key}")
    result = await redis.get(key)
    logger.info(f"Retrieved {len(result)} bytes")
```

---

## Migration Guide

### From Legacy Pattern to New Pattern

**Before:**
```python
# Old way - potential connection leaks
redis = await get_redis_connection()
await redis.set("key", "value")
# No explicit cleanup!
```

**After:**
```python
# New way - guaranteed cleanup
async with redis_context() as redis:
    await redis.set("key", "value")
```

### Migration Checklist

- [ ] Replace `redis.keys()` with `scan_keys_pattern()`
- [ ] Add `async with redis_context()` around Redis operations
- [ ] Add TTL to all keys using `RedisTTL` constants
- [ ] Replace manual error handling with `safe_redis_operation()`
- [ ] Update imports from `GRID.database.redis_database` to `shared.database.redis_patterns`
- [ ] Remove deprecated `close_redis()` calls
- [ ] Test with connection pool monitoring

---

## Troubleshooting

### Connection Pool Exhaustion

**Symptoms:**
- Timeouts on Redis operations
- "Connection pool exhausted" errors

**Diagnosis:**
```python
metrics = get_pool_metrics()
print(f"Max connections: {metrics['max_connections']}")

# Check active connections
redis-cli CLIENT LIST | wc -l
```

**Solutions:**
1. Ensure all code uses context managers
2. Check for long-running operations
3. Increase pool size if needed (edit `settings.REDIS_MAX_CONNECTIONS`)

### Memory Leaks

**Symptoms:**
- Redis memory usage grows unbounded
- Keys without TTL

**Diagnosis:**
```bash
# Find keys without expiration
redis-cli --scan | while read key; do
    if [ "$(redis-cli ttl "$key")" -eq "-1" ]; then
        echo "No TTL: $key"
    fi
done
```

**Solutions:**
1. Audit all `hset`, `set`, `lpush` calls
2. Ensure `expire()` is called immediately after
3. Use `batch_set_with_ttl()` for safety

### Circuit Breaker Stuck Open

**Symptoms:**
- All Redis operations fail immediately
- Circuit breaker state is OPEN

**Diagnosis:**
```bash
curl http://localhost:8000/health/redis/circuit-breaker
```

**Solutions:**
1. Wait for recovery timeout (60s default)
2. Fix underlying Redis connectivity issue
3. Restart application to reset circuit breaker

---

## Additional Resources

- [Redis Best Practices](https://redis.io/docs/manual/patterns/)
- [redis-py Documentation](https://redis-py.readthedocs.io/)
- [FastAPI Dependency Injection](https://fastapi.tiangolo.com/tutorial/dependencies/)

---

**For questions or issues, please contact the infrastructure team.**
