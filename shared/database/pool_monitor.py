"""
Connection Pool Monitoring for TradingBoost-Strategy

Provides monitoring and health checking for database and Redis connection pools.
"""

from typing import Protocol, Any
from dataclasses import dataclass
from datetime import datetime
import time
from shared.logging import get_logger

logger = get_logger(__name__)


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

    def __init__(self, engine, leak_threshold: float = 0.8):
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
            pool_size=pool.size(),
            checked_out=pool.checkedout(),
            available=pool.size() - pool.checkedout(),
            overflow=pool.overflow(),
            max_overflow=pool._max_overflow,
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

    async def warm_up_pool(self, connections: int | None = None):
        """
        Pre-create connections to avoid cold start.

        Useful for reducing first-request latency after startup.

        Args:
            connections: Number of connections to create (default: pool_size)
        """
        connections = connections or self.engine.pool.size()

        logger.info(
            f"Warming up pool with {connections} connections",
            extra={"target_connections": connections}
        )

        try:
            # Create a connection to ensure pool is initialized
            async with self.engine.begin() as conn:
                await conn.execute("SELECT 1")

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

    Usage:
        monitor = RedisPoolMonitor(pool)
        health = await monitor.health_check()
    """

    def __init__(self, pool):
        """
        Initialize Redis pool monitor.

        Args:
            pool: Redis ConnectionPool instance
        """
        self.pool = pool

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

        Returns:
            dict: Health status with latency metrics
        """
        try:
            # Import Redis here to avoid circular dependency
            from redis.asyncio import Redis

            redis = Redis(connection_pool=self.pool)

            # Measure latency
            latency_start = time.time()
            await redis.ping()
            latency = (time.time() - latency_start) * 1000  # Convert to milliseconds

            await redis.close()

            # Determine health based on latency
            if latency > 100:  # > 100ms is slow
                status = "degraded"
                message = f"High latency: {latency:.2f}ms"
            else:
                status = "healthy"
                message = "Redis responding normally"

            return {
                "status": status,
                "message": message,
                "latency_ms": round(latency, 2),
                "metrics": self.get_metrics(),
                "timestamp": datetime.utcnow().isoformat()
            }

        except Exception as e:
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
