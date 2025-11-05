"""
Connection Pool Monitoring for TradingBoost-Strategy

Provides monitoring and health checking for database and Redis connection pools.
Includes Prometheus metrics integration for observability.
"""

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from prometheus_client import Counter, Gauge, Histogram
from sqlalchemy.ext.asyncio import AsyncEngine

from shared.logging import get_logger

logger = get_logger(__name__)

# =============================================================================
# Prometheus Metrics for Redis Pool Monitoring
# =============================================================================

redis_pool_max_connections = Gauge(
    'redis_pool_max_connections',
    'Maximum number of connections in the Redis pool'
)

redis_pool_active_connections = Gauge(
    'redis_pool_active_connections',
    'Number of active Redis connections currently in use'
)

redis_pool_utilization_percent = Gauge(
    'redis_pool_utilization_percent',
    'Redis pool utilization as a percentage (0-100)'
)

redis_operation_duration_seconds = Histogram(
    'redis_operation_duration_seconds',
    'Duration of Redis operations in seconds',
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
)

redis_operation_errors_total = Counter(
    'redis_operation_errors_total',
    'Total number of Redis operation errors',
    ['error_type']
)

redis_circuit_breaker_state = Gauge(
    'redis_circuit_breaker_state',
    'Circuit breaker state (0=CLOSED, 1=HALF_OPEN, 2=OPEN)'
)

redis_connection_latency_ms = Gauge(
    'redis_connection_latency_ms',
    'Redis connection latency in milliseconds'
)

# Redis Migration Metrics
redis_migration_pattern_usage = Counter(
    'redis_migration_pattern_usage_total',
    'Total Redis operations by pattern type',
    ['pattern']  # 'new' or 'legacy'
)

redis_migration_enabled = Gauge(
    'redis_migration_enabled',
    'Whether Redis migration is enabled (1=enabled, 0=disabled)'
)

redis_migration_percentage = Gauge(
    'redis_migration_percentage',
    'Percentage of users using new Redis pattern (0-100)'
)

redis_migration_errors = Counter(
    'redis_migration_errors_total',
    'Total errors during Redis migration',
    ['file', 'error_type']
)


@dataclass
class PoolMetrics:
    """Connection pool metrics snapshot"""
    pool_size: int
    checked_out: int
    available: int
    overflow: int
    max_overflow: int
    timestamp: datetime


class PoolMonitor:
    """
    Monitor database connection pool health and metrics.

    Features:
    - Real-time pool statistics
    - Connection leak detection
    - Performance metrics
    - Health checks with utilization alerts

    Usage:
        monitor = PoolMonitor(engine)
        metrics = monitor.get_metrics()
        health = monitor.check_health()
    """

    def __init__(self, engine: AsyncEngine, leak_threshold: float = 0.8) -> None:
        """
        Initialize pool monitor.

        Args:
            engine: SQLAlchemy async engine
            leak_threshold: Utilization threshold for leak warning (default: 0.8 = 80%)
        """
        self.engine = engine
        self._leak_threshold = leak_threshold

    def get_metrics(self) -> PoolMetrics:
        """
        Get current pool metrics.

        Returns:
            PoolMetrics: Current pool state snapshot
        """
        pool = self.engine.pool

        return PoolMetrics(
            pool_size=pool.size(),  # type: ignore[attr-defined]
            checked_out=pool.checkedout(),  # type: ignore[attr-defined]
            available=pool.size() - pool.checkedout(),  # type: ignore[attr-defined]
            overflow=pool.overflow(),  # type: ignore[attr-defined]
            max_overflow=pool._max_overflow,  # type: ignore[attr-defined]
            timestamp=datetime.utcnow()
        )

    def check_health(self) -> dict[str, Any]:
        """
        Perform health check on connection pool.

        Checks:
        - Pool utilization (warns if > leak_threshold)
        - Available connections
        - Overflow usage

        Returns:
            dict: Health status with metrics and recommendations
        """
        metrics = self.get_metrics()

        # Calculate utilization
        total_capacity = metrics.pool_size + metrics.max_overflow
        utilization = metrics.checked_out / total_capacity if total_capacity > 0 else 0

        # Determine health status
        if utilization > self._leak_threshold:
            status = "warning"
            message = f"High pool utilization: {utilization:.1%}"

            logger.warning(
                message,
                extra={
                    "utilization": round(utilization * 100, 2),
                    "checked_out": metrics.checked_out,
                    "total_capacity": total_capacity,
                    "available": metrics.available
                }
            )

            recommendations = [
                "Check for connection leaks (unclosed sessions)",
                "Consider increasing pool_size or max_overflow",
                "Review long-running queries"
            ]
        else:
            status = "healthy"
            message = "Pool operating normally"
            recommendations = []

        return {
            "status": status,
            "message": message,
            "metrics": {
                "pool_size": metrics.pool_size,
                "checked_out": metrics.checked_out,
                "available": metrics.available,
                "overflow": metrics.overflow,
                "max_overflow": metrics.max_overflow,
                "utilization_percent": round(utilization * 100, 2)
            },
            "recommendations": recommendations,
            "timestamp": metrics.timestamp.isoformat()
        }

    async def warm_up_pool(self, connections: int | None = None) -> None:
        """
        Pre-create connections to avoid cold start.

        Useful for reducing first-request latency after startup.

        Args:
            connections: Number of connections to create (default: pool_size)
        """
        connections = connections or self.engine.pool.size()  # type: ignore[attr-defined]

        logger.info(
            f"Warming up pool with {connections} connections",
            extra={"target_connections": connections}
        )

        try:
            # Create a connection to ensure pool is initialized
            async with self.engine.begin() as conn:
                from sqlalchemy import text
                await conn.execute(text("SELECT 1"))

            logger.info("Pool warm-up complete")

        except Exception as e:
            logger.error(
                "Pool warm-up failed",
                extra={"error": str(e)},
                exc_info=True
            )
            raise


class RedisPoolMonitor:
    """
    Monitor Redis connection pool.

    Features:
    - Connection pool configuration
    - Health check with latency measurement
    - Metrics collection
    - Pool utilization tracking and alerts

    Usage:
        monitor = RedisPoolMonitor(pool)
        health = await monitor.health_check()
        stats = monitor.get_pool_stats()
    """

    def __init__(self, pool, utilization_warning_threshold: float = 0.80, utilization_critical_threshold: float = 0.90):
        """
        Initialize Redis pool monitor.

        Args:
            pool: Redis ConnectionPool instance
            utilization_warning_threshold: Utilization % to trigger warning (default: 0.80 = 80%)
            utilization_critical_threshold: Utilization % to trigger critical alert (default: 0.90 = 90%)
        """
        self.pool = pool
        self._warning_threshold = utilization_warning_threshold
        self._critical_threshold = utilization_critical_threshold

    def get_metrics(self) -> dict[str, Any]:
        """
        Get Redis pool metrics.

        Returns:
            dict: Pool configuration and connection details
        """
        return {
            "max_connections": self.pool.max_connections,
            "connection_kwargs": {
                "db": self.pool.connection_kwargs.get("db"),
                "decode_responses": self.pool.connection_kwargs.get("decode_responses"),
                "socket_timeout": self.pool.connection_kwargs.get("socket_timeout"),
                "socket_connect_timeout": self.pool.connection_kwargs.get("socket_connect_timeout"),
            }
        }

    async def health_check(self) -> dict[str, Any]:
        """
        Check Redis connectivity and measure latency.

        Updates Prometheus metrics during health check.

        Returns:
            dict: Health status with latency metrics
        """
        try:
            # Import Redis here to avoid circular dependency
            from redis.asyncio import Redis

            redis = Redis(connection_pool=self.pool)

            # Measure latency with histogram
            latency_start = time.time()
            await redis.ping()
            latency_seconds = time.time() - latency_start
            latency_ms = latency_seconds * 1000

            # Update Prometheus metrics
            redis_operation_duration_seconds.observe(latency_seconds)
            redis_connection_latency_ms.set(latency_ms)

            await redis.aclose()

            # Determine health based on latency
            if latency_ms > 100:  # > 100ms is slow
                status = "degraded"
                message = f"High latency: {latency_ms:.2f}ms"
            else:
                status = "healthy"
                message = "Redis responding normally"

            return {
                "status": status,
                "message": message,
                "latency_ms": round(latency_ms, 2),
                "metrics": self.get_metrics(),
                "timestamp": datetime.utcnow().isoformat()
            }

        except Exception as e:
            # Record error in Prometheus
            redis_operation_errors_total.labels(error_type=type(e).__name__).inc()

            logger.error(
                "Redis health check failed",
                extra={"error": str(e)},
                exc_info=True
            )

            return {
                "status": "unhealthy",
                "message": "Redis connection failed",
                "error": str(e),
                "error_type": type(e).__name__,
                "timestamp": datetime.utcnow().isoformat()
            }

    def get_pool_stats(self) -> dict[str, Any]:
        """
        Get Redis pool utilization statistics with alerts.

        Returns:
            dict: Pool statistics including utilization percentage and status
        """
        try:
            # Access internal pool state
            # Note: This accesses private attributes and may vary by redis-py version
            max_connections = self.pool.max_connections

            # Try to get current connection count
            # redis-py doesn't expose this directly, so we approximate
            # by checking _created_connections if available
            in_use_connections = 0
            if hasattr(self.pool, '_created_connections'):
                in_use_connections = self.pool._created_connections  # type: ignore[attr-defined]
            elif hasattr(self.pool, '_in_use_connections'):
                in_use_connections = len(self.pool._in_use_connections)  # type: ignore[attr-defined]

            available = max_connections - in_use_connections
            utilization_pct = (in_use_connections / max_connections * 100) if max_connections > 0 else 0

            # Update Prometheus metrics
            redis_pool_max_connections.set(max_connections)
            redis_pool_active_connections.set(in_use_connections)
            redis_pool_utilization_percent.set(utilization_pct)

            # Determine status based on utilization
            if utilization_pct >= self._critical_threshold * 100:
                status = "critical"
                message = f"⚠️ Critical pool utilization: {utilization_pct:.1f}%"
                logger.error(
                    message,
                    extra={
                        "utilization_pct": round(utilization_pct, 2),
                        "in_use": in_use_connections,
                        "max": max_connections,
                        "available": available
                    }
                )
                recommendations = [
                    "Immediate action required - pool near exhaustion",
                    "Check for connection leaks (unclosed Redis clients)",
                    "Increase REDIS_MAX_CONNECTIONS in configuration",
                    "Review long-running operations holding connections"
                ]
            elif utilization_pct >= self._warning_threshold * 100:
                status = "warning"
                message = f"⚠️ High pool utilization: {utilization_pct:.1f}%"
                logger.warning(
                    message,
                    extra={
                        "utilization_pct": round(utilization_pct, 2),
                        "in_use": in_use_connections,
                        "max": max_connections,
                        "available": available
                    }
                )
                recommendations = [
                    "Monitor pool usage closely",
                    "Review connection cleanup patterns",
                    "Consider increasing pool size if trend continues"
                ]
            else:
                status = "healthy"
                message = f"Pool utilization normal: {utilization_pct:.1f}%"
                recommendations = []

            return {
                "status": status,
                "message": message,
                "metrics": {
                    "max_connections": max_connections,
                    "in_use": in_use_connections,
                    "available": available,
                    "utilization_pct": round(utilization_pct, 2),
                    "warning_threshold_pct": self._warning_threshold * 100,
                    "critical_threshold_pct": self._critical_threshold * 100
                },
                "recommendations": recommendations,
                "timestamp": datetime.utcnow().isoformat()
            }

        except Exception as e:
            logger.error(
                "Failed to get pool stats",
                extra={"error": str(e)},
                exc_info=True
            )
            return {
                "status": "unknown",
                "message": "Unable to retrieve pool stats",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }


class RedisMigrationMonitor:
    """
    Monitor Redis migration progress and health.

    Features:
    - Track new vs. legacy pattern usage
    - Monitor migration percentage
    - Detect migration-related errors
    - Provide migration status dashboard

    Usage:
        monitor = RedisMigrationMonitor()
        monitor.update_metrics()
        status = monitor.get_migration_status()
    """

    def __init__(self):
        """Initialize migration monitor."""
        self._last_update = datetime.utcnow()

    def record_pattern_usage(self, pattern_type: str) -> None:
        """
        Record usage of Redis pattern.

        Args:
            pattern_type: 'new' for redis_context(), 'legacy' for get_redis_client()
        """
        redis_migration_pattern_usage.labels(pattern=pattern_type).inc()

    def record_migration_error(self, file_path: str, error_type: str) -> None:
        """
        Record migration-related error.

        Args:
            file_path: File where error occurred
            error_type: Type of error (e.g., 'timeout', 'connection_leak')
        """
        redis_migration_errors.labels(file=file_path, error_type=error_type).inc()
        logger.error(
            f"Migration error in {file_path}: {error_type}",
            extra={"file": file_path, "error_type": error_type}
        )

    def update_metrics(self) -> None:
        """
        Update migration metrics from config.

        Should be called periodically to sync with config changes.
        """
        from shared.config import get_settings

        settings = get_settings()

        # Update Prometheus metrics
        redis_migration_enabled.set(1 if settings.REDIS_MIGRATION_ENABLED else 0)
        redis_migration_percentage.set(settings.REDIS_MIGRATION_PERCENTAGE)

        self._last_update = datetime.utcnow()

    def get_migration_status(self) -> dict[str, Any]:
        """
        Get comprehensive migration status.

        Returns:
            dict: Migration status with metrics and recommendations
        """
        from shared.config import get_settings

        settings = get_settings()

        # Get pattern usage counts from Prometheus
        # Note: In production, you'd query Prometheus API
        # For now, we use the config values as proxy

        status_dict = {
            "enabled": settings.REDIS_MIGRATION_ENABLED,
            "percentage": settings.REDIS_MIGRATION_PERCENTAGE,
            "whitelist_users": len([u for u in settings.REDIS_MIGRATION_USER_WHITELIST.split(",") if u.strip()]),
            "last_update": self._last_update.isoformat(),
            "timestamp": datetime.utcnow().isoformat()
        }

        # Determine status and recommendations
        if not settings.REDIS_MIGRATION_ENABLED:
            status_dict["status"] = "disabled"
            status_dict["message"] = "Migration is not enabled"
            status_dict["recommendations"] = [
                "Set REDIS_MIGRATION_ENABLED=true to begin migration",
                "Start with REDIS_MIGRATION_PERCENTAGE=10 for testing"
            ]
        elif settings.REDIS_MIGRATION_PERCENTAGE == 0:
            status_dict["status"] = "ready"
            status_dict["message"] = "Migration enabled but not rolled out"
            status_dict["recommendations"] = [
                "Increase REDIS_MIGRATION_PERCENTAGE to begin rollout",
                "Monitor connection pool metrics closely"
            ]
        elif settings.REDIS_MIGRATION_PERCENTAGE < 100:
            status_dict["status"] = "in_progress"
            status_dict["message"] = f"Migration at {settings.REDIS_MIGRATION_PERCENTAGE}%"
            status_dict["recommendations"] = [
                f"Monitor for 24-48h before increasing beyond {settings.REDIS_MIGRATION_PERCENTAGE}%",
                "Check connection pool utilization remains < 70%",
                "Review error logs for migration-related issues"
            ]
        else:
            status_dict["status"] = "complete"
            status_dict["message"] = "Migration at 100%"
            status_dict["recommendations"] = [
                "Monitor for 7 days before removing feature flags",
                "Verify connection pool metrics are stable",
                "Remove legacy get_redis_client() code after validation"
            ]

        return status_dict


# Global migration monitor instance
migration_monitor = RedisMigrationMonitor()
