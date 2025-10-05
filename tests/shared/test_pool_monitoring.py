"""
Connection Pool Monitoring Tests

Tests for:
- shared/database/pool_monitor.py (PoolMonitor, RedisPoolMonitor)
- Pool health checks and metrics
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime
from shared.database.pool_monitor import PoolMonitor, RedisPoolMonitor, PoolMetrics


class TestPoolMetrics:
    """Test PoolMetrics dataclass"""

    def test_pool_metrics_creation(self):
        """Test PoolMetrics can be created with valid data"""
        metrics = PoolMetrics(
            pool_size=5,
            checked_out=2,
            available=3,
            overflow=0,
            max_overflow=10,
            timestamp=datetime.utcnow()
        )

        assert metrics.pool_size == 5
        assert metrics.checked_out == 2
        assert metrics.available == 3
        assert metrics.overflow == 0
        assert metrics.max_overflow == 10
        assert isinstance(metrics.timestamp, datetime)


class TestPoolMonitor:
    """Test PoolMonitor for database connection pool"""

    @pytest.fixture
    def mock_engine(self):
        """Create mock database engine"""
        engine = Mock()
        pool = Mock()
        pool.size.return_value = 5
        pool.checkedout.return_value = 2
        pool.overflow.return_value = 0
        pool._max_overflow = 10
        engine.pool = pool
        return engine

    def test_get_metrics(self, mock_engine):
        """Test get_metrics returns correct snapshot"""
        monitor = PoolMonitor(mock_engine)
        metrics = monitor.get_metrics()

        assert isinstance(metrics, PoolMetrics)
        assert metrics.pool_size == 5
        assert metrics.checked_out == 2
        assert metrics.available == 3  # 5 - 2
        assert metrics.overflow == 0
        assert metrics.max_overflow == 10

    def test_check_health_healthy(self, mock_engine):
        """Test check_health returns healthy status"""
        monitor = PoolMonitor(mock_engine, leak_threshold=0.8)
        health = monitor.check_health()

        assert health["status"] == "healthy"
        assert health["message"] == "Pool operating normally"
        assert health["recommendations"] == []
        assert "metrics" in health
        assert "timestamp" in health

    def test_check_health_warning_high_utilization(self, mock_engine):
        """Test check_health warns on high utilization"""
        # Set high utilization (13 out of 15 = 86%)
        mock_engine.pool.checkedout.return_value = 13

        monitor = PoolMonitor(mock_engine, leak_threshold=0.8)
        health = monitor.check_health()

        assert health["status"] == "warning"
        assert "High pool utilization" in health["message"]
        assert len(health["recommendations"]) > 0
        assert any("leak" in rec.lower() for rec in health["recommendations"])

    def test_check_health_calculates_utilization(self, mock_engine):
        """Test utilization calculation"""
        # 7 checked out, capacity = 5 + 10 = 15 → 46.67%
        mock_engine.pool.checkedout.return_value = 7

        monitor = PoolMonitor(mock_engine)
        health = monitor.check_health()

        assert health["metrics"]["utilization_percent"] == pytest.approx(46.67, rel=0.01)

    @pytest.mark.asyncio
    async def test_warm_up_pool(self, mock_engine):
        """Test warm_up_pool creates connections"""
        monitor = PoolMonitor(mock_engine)

        # Mock the engine.begin context manager
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()
        mock_engine.begin = AsyncMock(return_value=mock_conn)
        mock_engine.begin.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_engine.begin.return_value.__aexit__ = AsyncMock()

        await monitor.warm_up_pool(connections=3)

        # Should have created connection
        mock_engine.begin.assert_called_once()

    def test_custom_leak_threshold(self, mock_engine):
        """Test custom leak threshold"""
        # 11 out of 15 = 73% (below 80% but above 70%)
        mock_engine.pool.checkedout.return_value = 11

        # With 80% threshold - should be healthy
        monitor_80 = PoolMonitor(mock_engine, leak_threshold=0.8)
        assert monitor_80.check_health()["status"] == "healthy"

        # With 70% threshold - should warn
        monitor_70 = PoolMonitor(mock_engine, leak_threshold=0.7)
        assert monitor_70.check_health()["status"] == "warning"


class TestRedisPoolMonitor:
    """Test RedisPoolMonitor for Redis connection pool"""

    @pytest.fixture
    def mock_pool(self):
        """Create mock Redis connection pool"""
        pool = Mock()
        pool.max_connections = 200
        pool.connection_kwargs = {
            "db": 0,
            "decode_responses": True,
            "socket_timeout": None,
            "socket_connect_timeout": 5,
        }
        return pool

    def test_get_metrics(self, mock_pool):
        """Test get_metrics returns pool configuration"""
        monitor = RedisPoolMonitor(mock_pool)
        metrics = monitor.get_metrics()

        assert metrics["max_connections"] == 200
        assert metrics["connection_kwargs"]["db"] == 0
        assert metrics["connection_kwargs"]["decode_responses"] is True

    @pytest.mark.asyncio
    async def test_health_check_healthy(self, mock_pool):
        """Test health_check returns healthy status"""
        monitor = RedisPoolMonitor(mock_pool)

        with patch("redis.asyncio.Redis") as mock_redis_class:
            mock_redis = AsyncMock()
            mock_redis.ping = AsyncMock(return_value=True)
            mock_redis.close = AsyncMock()
            mock_redis_class.return_value = mock_redis

            health = await monitor.health_check()

            assert health["status"] == "healthy"
            assert health["message"] == "Redis responding normally"
            assert "latency_ms" in health
            assert health["latency_ms"] < 100  # Should be very fast for mock
            assert "metrics" in health

    @pytest.mark.asyncio
    async def test_health_check_degraded_high_latency(self, mock_pool):
        """Test health_check detects high latency"""
        monitor = RedisPoolMonitor(mock_pool)

        with patch("redis.asyncio.Redis") as mock_redis_class:
            mock_redis = AsyncMock()

            # Simulate high latency
            async def slow_ping():
                import asyncio
                await asyncio.sleep(0.15)  # 150ms
                return True

            mock_redis.ping = slow_ping
            mock_redis.close = AsyncMock()
            mock_redis_class.return_value = mock_redis

            health = await monitor.health_check()

            assert health["status"] == "degraded"
            assert "High latency" in health["message"]
            assert health["latency_ms"] > 100

    @pytest.mark.asyncio
    async def test_health_check_unhealthy_on_error(self, mock_pool):
        """Test health_check returns unhealthy on connection error"""
        monitor = RedisPoolMonitor(mock_pool)

        with patch("redis.asyncio.Redis") as mock_redis_class:
            mock_redis = AsyncMock()
            mock_redis.ping = AsyncMock(side_effect=ConnectionError("Connection refused"))
            mock_redis.close = AsyncMock()
            mock_redis_class.return_value = mock_redis

            health = await monitor.health_check()

            assert health["status"] == "unhealthy"
            assert "failed" in health["message"].lower()
            assert "error" in health
            assert health["error_type"] == "ConnectionError"


class TestPoolMonitoringIntegration:
    """Integration tests for pool monitoring (requires real connections)"""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_real_database_pool_monitoring(self):
        """Test monitoring with real database pool"""
        pytest.skip("Requires database connection")

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_real_redis_pool_monitoring(self):
        """Test monitoring with real Redis pool"""
        pytest.skip("Requires Redis connection")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
