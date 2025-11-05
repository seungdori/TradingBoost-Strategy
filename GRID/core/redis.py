"""Redis Connection Management for GRID Strategy

This module provides Redis connection management for the GRID trading strategy,
using the shared connection pool from shared.database.redis.

**MIGRATION STATUS (2025-10-22)**:
    Global client pattern removal completed! All critical files migrated to redis_context().

**REQUIRED PATTERN** - Use redis_context() for ALL Redis operations:

    ✅ CORRECT (Context Manager - Auto cleanup):
        from shared.database.redis_patterns import redis_context

        async with redis_context() as redis:
            await redis.get("key")
            await redis.set("key", "value")
        # Connection automatically returned to pool, timeout protected

    ❌ DEPRECATED (Direct connection - Connection leak risk):
        from GRID.core.redis import get_redis_connection

        client = await get_redis_connection()
        await client.get("key")
        # ⚠️ No automatic cleanup! Connection may leak!

**Benefits of redis_context()**:
    1. Automatic connection cleanup (prevents leaks)
    2. Timeout protection (prevents hanging operations)
    3. Circuit breaker integration (prevents cascading failures)
    4. Consistent error handling and logging
    5. Production-ready reliability

**Completed Migrations**:
    ✅ routes/connection_manager.py - All methods migrated
    ✅ trading/instance_manager.py - Removed self.redis instance variable
    ✅ trading/grid_core.py - Context manager pattern applied

**Backward Compatibility**:
    - get_redis_connection() still available but deprecated (will be removed)
    - Emits DeprecationWarning on every call
    - New code MUST use redis_context()

See Also:
    - shared/database/redis_patterns.py: redis_context() implementation
    - shared/database/redis.py: Connection pool configuration
    - REDIS_FIXES_GUIDE.md: Complete migration guide
"""

import warnings
from shared.database.redis_patterns import redis_context, RedisTTL
from shared.database.redis import get_redis, RedisConnectionPool

# shared 모듈 재사용
from shared.utils.redis_utils import (
    delete_redis_data,
    exists_redis_key,
    get_redis_data,
    set_redis_data,
)

__all__ = [
    'get_redis_connection',  # Deprecated - use redis_context() instead
    'redis_context',  # Recommended
    'RedisTTL',
    'set_redis_data',
    'get_redis_data',
    'delete_redis_data',
    'exists_redis_key',
]


async def get_redis_connection():
    """
    Redis 연결을 반환합니다 (shared pool 사용).

    .. deprecated:: 2025-10-22
        **DEPRECATED**: This function is deprecated and will be removed in a future version.
        Use :func:`redis_context` context manager instead for proper connection management.

        **Migration Required**: All GRID code should migrate to redis_context() pattern.

        ❌ Old pattern (DEPRECATED - DO NOT USE):
            from GRID.core.redis import get_redis_connection
            redis = await get_redis_connection()
            await redis.get("key")
            # ⚠️ Connection leak risk! No automatic cleanup!

        ✅ New pattern (REQUIRED):
            from shared.database.redis_patterns import redis_context
            async with redis_context() as redis:
                await redis.get("key")
            # ✅ Automatic cleanup, timeout protection, circuit breaker!

    **Why migrate?**
        1. Prevents connection leaks (automatic cleanup)
        2. Timeout protection (prevents hanging operations)
        3. Circuit breaker integration (prevents cascading failures)
        4. Better error handling and logging
        5. Consistent with HYPERRSI strategy

    **Migration Status (2025-10-22)**:
        ✅ connection_manager.py - Migrated
        ✅ instance_manager.py - Migrated
        ✅ grid_core.py - Migrated
        ⚠️ Other files - Import cleanup in progress

    Returns:
        AsyncRedis: Redis 클라이언트 인스턴스

    Raises:
        DeprecationWarning: Always raised when this function is called
    """
    warnings.warn(
        "\n"
        "=" * 80 + "\n"
        "DEPRECATED: get_redis_connection() is deprecated!\n"
        "Please use redis_context() context manager instead.\n"
        "\n"
        "Migration guide:\n"
        "  OLD: redis = await get_redis_connection()\n"
        "  NEW: async with redis_context() as redis:\n"
        "\n"
        "Benefits: Auto cleanup, timeout protection, circuit breaker\n"
        "=" * 80,
        DeprecationWarning,
        stacklevel=2
    )
    return await get_redis()
