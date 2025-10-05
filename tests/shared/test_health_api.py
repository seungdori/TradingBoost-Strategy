"""
Health Check API Tests

Tests for shared/api/health.py endpoints
"""

import pytest
from unittest.mock import patch, AsyncMock
from fastapi import FastAPI
from fastapi.testclient import TestClient
from shared.api import health_router


@pytest.fixture
def app():
    """Create FastAPI app with health router"""
    app = FastAPI()
    app.include_router(health_router, prefix="/health", tags=["health"])
    return app


@pytest.fixture
def client(app):
    """Create test client"""
    return TestClient(app)


class TestHealthEndpoint:
    """Test /health/ endpoint"""

    def test_health_check_all_healthy(self, client):
        """Test health check when all components healthy"""
        with patch("shared.database.session.DatabaseConfig.health_check") as mock_db, \
             patch("shared.database.redis.RedisConnectionPool.health_check") as mock_redis:

            mock_db.return_value = {
                "status": "healthy",
                "metrics": {"pool_size": 5},
            }
            mock_redis.return_value = AsyncMock(return_value={
                "status": "healthy",
                "latency_ms": 1.5,
            })()

            response = client.get("/health/")

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "healthy"
            assert "components" in data
            assert data["components"]["database"] == "healthy"
            assert data["components"]["redis"] == "healthy"

    def test_health_check_degraded(self, client):
        """Test health check when component degraded"""
        with patch("shared.database.session.DatabaseConfig.health_check") as mock_db, \
             patch("shared.database.redis.RedisConnectionPool.health_check") as mock_redis:

            mock_db.return_value = {
                "status": "healthy",
                "metrics": {},
            }
            mock_redis.return_value = AsyncMock(return_value={
                "status": "degraded",
                "message": "High latency",
            })()

            response = client.get("/health/")

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "degraded"

    def test_health_check_unhealthy(self, client):
        """Test health check when component unhealthy"""
        with patch("shared.database.session.DatabaseConfig.health_check") as mock_db, \
             patch("shared.database.redis.RedisConnectionPool.health_check") as mock_redis:

            mock_db.return_value = {
                "status": "unhealthy",
                "error": "Connection failed",
            }
            mock_redis.return_value = AsyncMock(return_value={
                "status": "healthy",
            })()

            response = client.get("/health/")

            assert response.status_code == 503
            data = response.json()
            assert data["status"] == "unhealthy"

    def test_health_check_error_handling(self, client):
        """Test health check handles exceptions"""
        with patch("shared.database.session.DatabaseConfig.health_check") as mock_db:
            mock_db.side_effect = Exception("Database error")

            response = client.get("/health/")

            assert response.status_code == 503
            data = response.json()
            assert data["status"] == "unhealthy"
            assert "error" in data


class TestDatabaseHealthEndpoint:
    """Test /health/db endpoint"""

    def test_db_health_healthy(self, client):
        """Test database health when healthy"""
        with patch("shared.database.session.DatabaseConfig.health_check") as mock_db:
            mock_db.return_value = {
                "status": "healthy",
                "message": "Pool operating normally",
                "metrics": {
                    "pool_size": 5,
                    "checked_out": 2,
                    "available": 3,
                    "utilization_percent": 40.0,
                },
            }

            response = client.get("/health/db")

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "healthy"
            assert data["metrics"]["pool_size"] == 5
            assert data["metrics"]["utilization_percent"] == 40.0

    def test_db_health_warning(self, client):
        """Test database health warning status"""
        with patch("shared.database.session.DatabaseConfig.health_check") as mock_db:
            mock_db.return_value = {
                "status": "warning",
                "message": "High pool utilization: 85%",
                "metrics": {"utilization_percent": 85.0},
                "recommendations": ["Check for connection leaks"],
            }

            response = client.get("/health/db")

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "warning"
            assert len(data["recommendations"]) > 0

    def test_db_health_error(self, client):
        """Test database health error handling"""
        with patch("shared.database.session.DatabaseConfig.health_check") as mock_db:
            mock_db.side_effect = Exception("Pool error")

            response = client.get("/health/db")

            assert response.status_code == 503
            data = response.json()
            assert data["status"] == "unhealthy"


class TestRedisHealthEndpoint:
    """Test /health/redis endpoint"""

    def test_redis_health_healthy(self, client):
        """Test Redis health when healthy"""
        with patch("shared.database.redis.RedisConnectionPool.health_check") as mock_redis:
            mock_redis.return_value = AsyncMock(return_value={
                "status": "healthy",
                "message": "Redis responding normally",
                "latency_ms": 1.5,
                "metrics": {"max_connections": 200},
            })()

            response = client.get("/health/redis")

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "healthy"
            assert data["latency_ms"] == 1.5

    def test_redis_health_degraded(self, client):
        """Test Redis health degraded status"""
        with patch("shared.database.redis.RedisConnectionPool.health_check") as mock_redis:
            mock_redis.return_value = AsyncMock(return_value={
                "status": "degraded",
                "message": "High latency: 150ms",
                "latency_ms": 150.0,
            })()

            response = client.get("/health/redis")

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "degraded"
            assert data["latency_ms"] > 100

    def test_redis_health_unhealthy(self, client):
        """Test Redis health unhealthy status"""
        with patch("shared.database.redis.RedisConnectionPool.health_check") as mock_redis:
            mock_redis.return_value = AsyncMock(return_value={
                "status": "unhealthy",
                "message": "Redis connection failed",
                "error": "Connection refused",
            })()

            response = client.get("/health/redis")

            assert response.status_code == 503
            data = response.json()
            assert data["status"] == "unhealthy"


class TestKubernetesProbes:
    """Test Kubernetes probe endpoints"""

    def test_readiness_probe_ready(self, client):
        """Test readiness probe when ready"""
        with patch("shared.database.session.DatabaseConfig.health_check") as mock_db, \
             patch("shared.database.redis.RedisConnectionPool.health_check") as mock_redis:

            mock_db.return_value = {"status": "healthy"}
            mock_redis.return_value = AsyncMock(return_value={"status": "healthy"})()

            response = client.get("/health/ready")

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ready"

    def test_readiness_probe_not_ready(self, client):
        """Test readiness probe when not ready"""
        with patch("shared.database.session.DatabaseConfig.health_check") as mock_db, \
             patch("shared.database.redis.RedisConnectionPool.health_check") as mock_redis:

            mock_db.return_value = {"status": "unhealthy"}
            mock_redis.return_value = AsyncMock(return_value={"status": "healthy"})()

            response = client.get("/health/ready")

            assert response.status_code == 503
            data = response.json()
            assert data["status"] == "not_ready"

    def test_liveness_probe(self, client):
        """Test liveness probe always returns alive"""
        response = client.get("/health/live")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "alive"


class TestHealthAPIIntegration:
    """Integration tests for health API"""

    @pytest.mark.integration
    def test_full_health_check_integration(self, client):
        """Test full health check with real connections"""
        pytest.skip("Requires database and Redis connections")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
