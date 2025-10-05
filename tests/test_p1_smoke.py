"""
Priority 1 Smoke Tests

Quick validation tests to verify basic functionality of P1 improvements.
These tests focus on critical paths and integration points.
"""

import pytest
from shared.config import settings


class TestConfigurationSmoke:
    """Smoke tests for configuration management"""

    def test_settings_can_load(self):
        """Test that settings can be loaded"""
        assert settings is not None
        assert settings.ENVIRONMENT in ["development", "production", "test"]

    def test_database_url_construction(self):
        """Test database URL is constructed"""
        db_url = settings.db_url
        assert db_url is not None
        assert "://" in db_url  # Has protocol

    def test_redis_url_construction(self):
        """Test Redis URL is constructed"""
        redis_url = settings.redis_url
        assert redis_url is not None
        assert "redis://" in redis_url

    def test_pool_settings_have_defaults(self):
        """Test pool settings have sensible defaults"""
        assert settings.DB_POOL_SIZE >= 1
        assert settings.DB_POOL_SIZE <= 20
        assert settings.DB_MAX_OVERFLOW >= 0
        assert settings.REDIS_MAX_CONNECTIONS > 0


class TestTransactionSmoke:
    """Smoke tests for transaction management"""

    def test_transactional_import(self):
        """Test transactional can be imported"""
        from shared.database.transactions import transactional
        assert transactional is not None

    def test_isolation_levels_defined(self):
        """Test isolation levels are defined"""
        from shared.database.transactions import IsolationLevel

        assert IsolationLevel.READ_COMMITTED is not None
        assert IsolationLevel.REPEATABLE_READ is not None
        assert IsolationLevel.SERIALIZABLE is not None


class TestErrorHandlingSmoke:
    """Smoke tests for error handling"""

    def test_middleware_import(self):
        """Test middleware can be imported"""
        from shared.errors.middleware import RequestIDMiddleware
        assert RequestIDMiddleware is not None

    def test_exception_classes_defined(self):
        """Test custom exception classes exist"""
        from shared.errors import TradingException, ErrorCode, DatabaseException

        assert TradingException is not None
        assert ErrorCode is not None
        assert DatabaseException is not None

    def test_error_codes_defined(self):
        """Test error codes are defined"""
        from shared.errors import ErrorCode

        assert hasattr(ErrorCode, "ORDER_FAILED")
        assert hasattr(ErrorCode, "DATABASE_ERROR")
        assert hasattr(ErrorCode, "VALIDATION_ERROR")


class TestPoolMonitoringSmoke:
    """Smoke tests for connection pool monitoring"""

    def test_pool_monitor_import(self):
        """Test pool monitor can be imported"""
        from shared.database.pool_monitor import PoolMonitor, RedisPoolMonitor
        assert PoolMonitor is not None
        assert RedisPoolMonitor is not None

    def test_pool_metrics_import(self):
        """Test pool metrics can be imported"""
        from shared.database.pool_monitor import PoolMetrics
        assert PoolMetrics is not None

    def test_database_config_has_monitoring(self):
        """Test DatabaseConfig has monitoring methods"""
        from shared.database.session import DatabaseConfig

        assert hasattr(DatabaseConfig, "health_check")
        assert hasattr(DatabaseConfig, "get_monitor")
        assert hasattr(DatabaseConfig, "warm_up_pool")

    def test_redis_pool_has_monitoring(self):
        """Test RedisConnectionPool has monitoring"""
        from shared.database.redis import RedisConnectionPool

        assert hasattr(RedisConnectionPool, "health_check")
        assert hasattr(RedisConnectionPool, "get_monitor")


class TestHealthAPISmoke:
    """Smoke tests for health check API"""

    def test_health_router_import(self):
        """Test health router can be imported"""
        from shared.api import health_router
        assert health_router is not None

    def test_health_module_import(self):
        """Test health module can be imported"""
        from shared.api import health
        assert health is not None

    def test_health_router_has_routes(self):
        """Test health router has expected routes"""
        from shared.api import health_router

        # Get all route paths
        paths = [route.path for route in health_router.routes]

        # Check expected endpoints exist
        assert "/" in paths  # Overall health
        assert "/db" in paths  # Database health
        assert "/redis" in paths  # Redis health
        assert "/ready" in paths  # Readiness probe
        assert "/live" in paths  # Liveness probe


class TestIntegrationSmoke:
    """Smoke tests for overall integration"""

    def test_all_modules_can_import_together(self):
        """Test all P1 modules can be imported together"""
        from shared.config import settings
        from shared.database.transactions import transactional
        from shared.database.session import DatabaseConfig
        from shared.database.redis import RedisConnectionPool
        from shared.database.pool_monitor import PoolMonitor, RedisPoolMonitor
        from shared.errors import TradingException, ErrorCode
        from shared.errors.middleware import RequestIDMiddleware
        from shared.errors.handlers import register_exception_handlers
        from shared.api import health_router

        # All imports should succeed
        assert all([
            settings,
            transactional,
            DatabaseConfig,
            RedisConnectionPool,
            PoolMonitor,
            RedisPoolMonitor,
            TradingException,
            ErrorCode,
            RequestIDMiddleware,
            register_exception_handlers,
            health_router,
        ])

    def test_fastapi_app_can_be_created_with_all_features(self):
        """Test FastAPI app can be created with all P1 features"""
        from fastapi import FastAPI
        from shared.errors.middleware import RequestIDMiddleware
        from shared.errors.handlers import register_exception_handlers
        from shared.api import health_router

        app = FastAPI()

        # Register all P1 features
        app.add_middleware(RequestIDMiddleware)
        register_exception_handlers(app)
        app.include_router(health_router, prefix="/health")

        # App should be created successfully
        assert app is not None
        assert len(app.routes) > 0  # Should have health routes


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
