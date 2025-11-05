"""
Redis Migration Utilities
Provides feature flag system for gradual rollout of redis_context() pattern
"""

import asyncio
import hashlib
from contextlib import asynccontextmanager
from typing import Optional

from shared.config import get_settings
from shared.database.redis_patterns import redis_context, RedisTimeout
from shared.database.redis_helper import get_redis_client
from shared.logging import get_logger

logger = get_logger(__name__)


def should_use_new_pattern(user_id: str) -> bool:
    """
    Determine if a user should use the new redis_context() pattern
    based on feature flags and percentage rollout.

    Args:
        user_id: User identifier for consistent hash-based selection

    Returns:
        True if user should use new pattern, False for legacy pattern
    """
    settings = get_settings()

    # If migration is disabled, use legacy pattern
    if not settings.REDIS_MIGRATION_ENABLED:
        return False

    # If migration is at 100%, use new pattern for everyone
    if settings.REDIS_MIGRATION_PERCENTAGE >= 100:
        return True

    # Check if user is in whitelist
    if settings.REDIS_MIGRATION_USER_WHITELIST:
        whitelist = [uid.strip() for uid in settings.REDIS_MIGRATION_USER_WHITELIST.split(",")]
        if user_id in whitelist:
            return True

    # Use consistent hashing for percentage-based rollout
    # This ensures same user always gets same decision
    if settings.REDIS_MIGRATION_PERCENTAGE > 0:
        user_hash = int(hashlib.md5(user_id.encode()).hexdigest(), 16)
        user_percentage = user_hash % 100
        return user_percentage < settings.REDIS_MIGRATION_PERCENTAGE

    return False


@asynccontextmanager
async def get_redis_context(
    user_id: Optional[str] = None,
    timeout: RedisTimeout = RedisTimeout.NORMAL_OPERATION,
    force_new: bool = False,
    force_legacy: bool = False
):
    """
    Get Redis context manager with automatic connection cleanup.

    This is the standard way to interact with Redis in the application.
    Supports gradual migration via feature flags.

    Args:
        user_id: Optional user ID for percentage-based rollout
        timeout: Timeout for operations (default: NORMAL_OPERATION)
        force_new: Force new pattern regardless of feature flags (for testing)
        force_legacy: Force legacy pattern regardless of feature flags (for rollback)

    Yields:
        Redis client with automatic connection cleanup

    Example:
        async with get_redis_context(user_id="user123") as redis:
            await redis.set("key", "value")
    """
    settings = get_settings()

    # Determine which pattern to use
    use_new_pattern = False

    if force_legacy:
        use_new_pattern = False
    elif force_new:
        use_new_pattern = True
    elif user_id:
        use_new_pattern = should_use_new_pattern(user_id)
    else:
        # No user_id provided, use global setting
        use_new_pattern = settings.REDIS_MIGRATION_ENABLED and settings.REDIS_MIGRATION_PERCENTAGE >= 100

    # Use appropriate pattern
    if use_new_pattern:
        async with redis_context(timeout=timeout) as redis:
            yield redis
    else:
        # Legacy pattern - get client and yield it
        # FIXED: Added proper cleanup to prevent connection leaks
        redis = await get_redis_client()
        try:
            yield redis
        finally:
            # CRITICAL: Return connection to pool to prevent leaks
            try:
                await asyncio.wait_for(redis.aclose(), timeout=2.0)
            except asyncio.TimeoutError:
                logger.warning("Legacy pattern: Redis close timed out after 2s")
            except Exception as e:
                logger.error(f"Legacy pattern: Error closing Redis connection: {e}")


class MigrationMetrics:
    """
    Track migration metrics for monitoring
    """

    def __init__(self):
        self.new_pattern_calls = 0
        self.legacy_pattern_calls = 0
        self.errors = 0

    def record_new_pattern(self):
        self.new_pattern_calls += 1

    def record_legacy_pattern(self):
        self.legacy_pattern_calls += 1

    def record_error(self):
        self.errors += 1

    def get_metrics(self) -> dict:
        total = self.new_pattern_calls + self.legacy_pattern_calls
        if total == 0:
            new_percentage = 0
        else:
            new_percentage = (self.new_pattern_calls / total) * 100

        return {
            "new_pattern_calls": self.new_pattern_calls,
            "legacy_pattern_calls": self.legacy_pattern_calls,
            "total_calls": total,
            "new_pattern_percentage": new_percentage,
            "errors": self.errors
        }

    def reset(self):
        self.new_pattern_calls = 0
        self.legacy_pattern_calls = 0
        self.errors = 0


# Global metrics instance
migration_metrics = MigrationMetrics()


def get_migration_status() -> dict:
    """
    Get current migration status including feature flags and metrics

    Returns:
        Dictionary with migration status information
    """
    settings = get_settings()

    return {
        "migration_enabled": settings.REDIS_MIGRATION_ENABLED,
        "migration_percentage": settings.REDIS_MIGRATION_PERCENTAGE,
        "whitelist_count": len([uid for uid in settings.REDIS_MIGRATION_USER_WHITELIST.split(",") if uid.strip()]),
        "metrics": migration_metrics.get_metrics()
    }
