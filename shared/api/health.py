"""
Health Check API Endpoints

Provides comprehensive health monitoring for infrastructure components:
- Overall system health
- Database connection pool metrics
- Redis connection pool metrics
- Service availability checks

Usage:
    from shared.api import health_router

    app = FastAPI()
    app.include_router(health_router, prefix="/health", tags=["health"])
"""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from shared.database.redis import RedisConnectionPool, get_pool_metrics, get_circuit_breaker
from shared.database.session import DatabaseConfig
from shared.logging import get_logger

logger = get_logger(__name__)

router = APIRouter()


@router.get("/", summary="Overall system health check")
async def health_check() -> JSONResponse:
    """
    Comprehensive system health check.

    Checks all critical infrastructure components and returns
    aggregated health status.

    Returns:
        dict: Overall health status with component details

    Example Response:
        {
            "status": "healthy",
            "timestamp": "2025-10-05T10:30:45.123456",
            "components": {
                "database": "healthy",
                "redis": "healthy"
            },
            "details": {
                "database": {...},
                "redis": {...}
            }
        }
    """
    try:
        # Get individual component health
        db_health = DatabaseConfig.health_check()
        redis_health = await RedisConnectionPool.health_check()

        # Determine overall status
        components_status = {
            "database": db_health["status"],
            "redis": redis_health["status"]
        }

        # Overall status is healthy if all components are healthy
        overall_status = "healthy" if all(
            s in ["healthy", "degraded"] for s in components_status.values()
        ) else "unhealthy"

        # If any component has warning, overall is degraded
        if any(s == "warning" for s in components_status.values()):
            overall_status = "degraded"

        response = {
            "status": overall_status,
            "timestamp": datetime.utcnow().isoformat(),
            "components": components_status,
            "details": {
                "database": db_health,
                "redis": redis_health
            }
        }

        # Return appropriate HTTP status code
        if overall_status == "healthy":
            return JSONResponse(status_code=status.HTTP_200_OK, content=response)
        elif overall_status == "degraded":
            return JSONResponse(status_code=status.HTTP_200_OK, content=response)
        else:
            return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content=response)

    except Exception as e:
        logger.error(
            "Health check failed",
            extra={"error": str(e)},
            exc_info=True
        )

        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "unhealthy",
                "timestamp": datetime.utcnow().isoformat(),
                "error": str(e),
                "error_type": type(e).__name__
            }
        )


@router.get("/db", summary="Database pool health check")
def database_health() -> JSONResponse:
    """
    Database connection pool health check.

    Provides detailed metrics about database connection pool utilization,
    performance, and potential issues.

    Returns:
        dict: Database pool health status with metrics

    Example Response:
        {
            "status": "healthy",
            "message": "Pool operating normally",
            "metrics": {
                "pool_size": 5,
                "checked_out": 2,
                "available": 3,
                "overflow": 0,
                "max_overflow": 10,
                "utilization_percent": 20.0
            },
            "recommendations": [],
            "timestamp": "2025-10-05T10:30:45.123456"
        }
    """
    try:
        health_data = DatabaseConfig.health_check()

        # Return appropriate status code based on health
        if health_data["status"] == "healthy":
            return JSONResponse(status_code=status.HTTP_200_OK, content=health_data)
        elif health_data["status"] == "warning":
            return JSONResponse(status_code=status.HTTP_200_OK, content=health_data)
        else:
            return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content=health_data)

    except Exception as e:
        logger.error(
            "Database health check failed",
            extra={"error": str(e)},
            exc_info=True
        )

        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "unhealthy",
                "error": str(e),
                "error_type": type(e).__name__,
                "timestamp": datetime.utcnow().isoformat()
            }
        )


@router.get("/redis", summary="Redis pool health check")
async def redis_health() -> JSONResponse:
    """
    Redis connection pool health check.

    Checks Redis connectivity, measures latency, and provides
    pool configuration details.

    Returns:
        dict: Redis pool health status with latency metrics

    Example Response:
        {
            "status": "healthy",
            "message": "Redis responding normally",
            "latency_ms": 1.23,
            "metrics": {
                "max_connections": 200,
                "connection_kwargs": {
                    "db": 0,
                    "decode_responses": true,
                    "socket_timeout": null,
                    "socket_connect_timeout": 5
                }
            },
            "timestamp": "2025-10-05T10:30:45.123456"
        }
    """
    try:
        health_data = await RedisConnectionPool.health_check()

        # Return appropriate status code based on health
        if health_data["status"] == "healthy":
            return JSONResponse(status_code=status.HTTP_200_OK, content=health_data)
        elif health_data["status"] == "degraded":
            return JSONResponse(status_code=status.HTTP_200_OK, content=health_data)
        else:
            return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content=health_data)

    except Exception as e:
        logger.error(
            "Redis health check failed",
            extra={"error": str(e)},
            exc_info=True
        )

        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "unhealthy",
                "error": str(e),
                "error_type": type(e).__name__,
                "timestamp": datetime.utcnow().isoformat()
            }
        )


@router.get("/ready", summary="Readiness probe")
async def readiness_check() -> JSONResponse:
    """
    Kubernetes-style readiness probe.

    Checks if the application is ready to accept traffic.
    Returns 200 if ready, 503 if not ready.

    Returns:
        dict: Simple ready/not ready status
    """
    try:
        # Quick health checks
        db_health = DatabaseConfig.health_check()
        redis_health = await RedisConnectionPool.health_check()

        # Ready if both are not unhealthy
        is_ready = (
            db_health["status"] != "unhealthy" and
            redis_health["status"] != "unhealthy"
        )

        if is_ready:
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content={"status": "ready"}
            )
        else:
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={"status": "not_ready"}
            )

    except Exception as e:
        logger.error("Readiness check failed", exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "not_ready", "error": str(e)}
        )


@router.get("/live", summary="Liveness probe")
def liveness_check() -> JSONResponse:
    """
    Kubernetes-style liveness probe.

    Simple check to verify the application process is alive.
    Always returns 200 if the process is running.

    Returns:
        JSONResponse: Simple alive status
    """
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"status": "alive"}
    )


@router.get("/redis/pool", summary="Redis pool metrics")
async def redis_pool_metrics() -> JSONResponse:
    """
    Get detailed Redis connection pool metrics.

    Returns:
        dict: Pool configuration and current metrics

    Example Response:
        {
            "max_connections": 200,
            "pool_class": "ConnectionPool",
            "connection_kwargs": {
                "db": 0,
                "decode_responses": true,
                "socket_keepalive": true,
                "socket_connect_timeout": 5,
                "retry_on_timeout": true,
                "health_check_interval": 15
            }
        }
    """
    try:
        metrics = get_pool_metrics()
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=metrics
        )
    except Exception as e:
        logger.error(f"Error getting pool metrics: {e}", exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": str(e),
                "error_type": type(e).__name__
            }
        )


@router.get("/redis/circuit-breaker", summary="Redis circuit breaker status")
async def redis_circuit_breaker() -> JSONResponse:
    """
    Get Redis circuit breaker state.

    The circuit breaker prevents cascading failures by failing fast
    when Redis is unavailable.

    Returns:
        dict: Circuit breaker state

    Example Response:
        {
            "state": "CLOSED",  # CLOSED, OPEN, or HALF_OPEN
            "failure_count": 0,
            "last_failure_time": 0.0,
            "is_open": false
        }

    States:
        - CLOSED: Normal operation, requests pass through
        - OPEN: Too many failures, requests fail immediately
        - HALF_OPEN: Testing if Redis has recovered
    """
    try:
        breaker = get_circuit_breaker()
        state = breaker.get_state()
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=state
        )
    except Exception as e:
        logger.error(f"Error getting circuit breaker state: {e}", exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": str(e),
                "error_type": type(e).__name__
            }
        )
