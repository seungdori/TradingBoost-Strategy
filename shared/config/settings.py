"""
Unified Configuration Management for TradingBoost-Strategy

Single source of truth for all configuration across GRID and HYPERRSI modules.
Uses Pydantic Settings for type-safe configuration from environment variables.
"""

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Find project root (where .env file is located)
_current_file = Path(__file__).resolve()
_project_root = _current_file.parent.parent.parent  # shared/config/settings.py -> TradingBoost-Strategy/
_env_file = _project_root / ".env"


class Settings(BaseSettings):
    """
    Unified settings for TradingBoost-Strategy platform.

    All configuration is loaded from environment variables or .env file.
    No hardcoded secrets or credentials allowed.
    """

    model_config = SettingsConfigDict(
        env_file=str(_env_file),
        env_file_encoding="utf-8",
        case_sensitive=True,
        validate_assignment=True,
        extra="forbid",  # Catch typos in environment variables
        frozen=False,  # Allow runtime updates for testing
    )

    # ============================================================================
    # Application Settings
    # ============================================================================

    ENVIRONMENT: Literal["development", "staging", "production"] = Field(
        default="development",
        description="Runtime environment"
    )
    DEBUG: bool = Field(
        default=True,
        description="Enable debug mode (auto-disabled in production)"
    )

    # ============================================================================
    # Database Configuration
    # ============================================================================

    # Database connection details
    DB_USER: str = Field(default="", description="Database username")
    DB_PASSWORD: str = Field(default="", description="Database password")
    DB_HOST: str = Field(default="", description="Database host")
    DB_PORT: int = Field(default=5432, ge=1, le=65535, description="Database port")
    DB_NAME: str = Field(default="", description="Database name")

    # TimescaleDB connection (used for production data store)
    TIMESCALE_HOST: str = Field(default="", description="TimescaleDB host")
    TIMESCALE_PORT: int = Field(default=5432, ge=1, le=65535, description="TimescaleDB port")
    TIMESCALE_DATABASE: str = Field(default="", description="TimescaleDB database name")
    TIMESCALE_USER: str = Field(default="", description="TimescaleDB username")
    TIMESCALE_PASSWORD: str = Field(default="", description="TimescaleDB password")

    DATABASE_URL: str = Field(default="", description="Complete database URL")

    # Error Database (separate pool for error logging)
    ERROR_DB_URL: str = Field(
        default="",
        description="Error logging database URL (separate pool)"
    )

    @property
    def db_url(self) -> str:
        """
        Construct database URL from components or use explicit URL.

        Priority:
        1. Explicit DATABASE_URL if set
        2. Construct from DB_* components
        """
        if self.DATABASE_URL:
            return self.DATABASE_URL

        # Check if we have minimum required DB components (password is optional for local)
        if self.DB_USER and self.DB_HOST and self.DB_NAME:
            if self.DB_PASSWORD:
                return f"postgresql+asyncpg://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
            else:
                # No password (for local PostgreSQL with trust authentication)
                return f"postgresql+asyncpg://{self.DB_USER}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

        # PostgreSQL is required - no fallback
        raise ValueError(
            "PostgreSQL configuration required. Set DATABASE_URL or all DB_* variables (DB_USER, DB_HOST, DB_NAME). "
            "SQLite is no longer supported."
        )

    @property
    def CONSTRUCTED_DATABASE_URL(self) -> str:
        """Legacy property for backward compatibility"""
        return self.db_url

    @property
    def TIMESCALE_DSN(self) -> Optional[str]:
        """Build a DSN for TimescaleDB if credentials are available"""
        if not (self.TIMESCALE_HOST and self.TIMESCALE_DATABASE and self.TIMESCALE_USER):
            return None

        password = self.TIMESCALE_PASSWORD or ""
        return (
            f"postgresql://{self.TIMESCALE_USER}:{password}"
            f"@{self.TIMESCALE_HOST}:{self.TIMESCALE_PORT}/{self.TIMESCALE_DATABASE}"
        )

    # Connection pool settings
    DB_POOL_SIZE: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Database connection pool size"
    )
    DB_MAX_OVERFLOW: int = Field(
        default=10,
        ge=0,
        le=50,
        description="Maximum overflow connections"
    )
    DB_POOL_RECYCLE: int = Field(
        default=3600,
        ge=300,
        description="Recycle connections after N seconds"
    )
    DB_POOL_PRE_PING: bool = Field(
        default=True,
        description="Verify connections before use"
    )
    DB_POOL_TIMEOUT: int = Field(
        default=30,
        ge=5,
        le=120,
        description="Connection pool timeout in seconds"
    )

    # ============================================================================
    # Redis Configuration
    # ============================================================================

    REDIS_HOST: str = Field(default="localhost", description="Redis host")
    REDIS_PORT: int = Field(default=6379, ge=1, le=65535, description="Redis port")
    REDIS_DB: int = Field(default=0, ge=0, le=15, description="Redis database number")
    REDIS_PASSWORD: str | None = Field(default=None, description="Redis password")
    REDIS_MAX_CONNECTIONS: int = Field(
        default=50,
        ge=10,
        le=500,
        description="Maximum Redis connections"
    )
    REDIS_SOCKET_TIMEOUT: int = Field(
        default=5,
        ge=1,
        description="Redis socket read/write timeout"
    )
    REDIS_SOCKET_CONNECT_TIMEOUT: int = Field(
        default=5,
        ge=1,
        description="Redis socket connection timeout"
    )
    REDIS_HEALTH_CHECK_INTERVAL: int = Field(
        default=30,
        ge=10,
        description="Redis health check interval in seconds"
    )

    # Celery-specific Redis (optional override)
    CELERY_BROKER_URL_OVERRIDE: str | None = Field(
        default=None,
        description="Celery broker URL (override default Redis)"
    )
    CELERY_RESULT_BACKEND_OVERRIDE: str | None = Field(
        default=None,
        description="Celery result backend URL (override default Redis)"
    )

    @property
    def redis_url(self) -> str:
        """Construct Redis URL from components"""
        auth = f":{self.REDIS_PASSWORD}@" if self.REDIS_PASSWORD else ""
        return f"redis://{auth}{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    @property
    def REDIS_URL(self) -> str:
        """Legacy property for backward compatibility"""
        return self.redis_url

    @property
    def celery_broker_url(self) -> str:
        """
        Celery broker URL.

        Uses CELERY_BROKER_URL_OVERRIDE env var if set, otherwise defaults to Redis DB 1.
        This allows local development to use localhost Redis for Celery
        while keeping application data in remote Redis.
        """
        if self.CELERY_BROKER_URL_OVERRIDE:
            return self.CELERY_BROKER_URL_OVERRIDE
        auth = f":{self.REDIS_PASSWORD}@" if self.REDIS_PASSWORD else ""
        return f"redis://{auth}{self.REDIS_HOST}:{self.REDIS_PORT}/1"

    @property
    def CELERY_BROKER_URL(self) -> str:
        """Legacy property for backward compatibility"""
        return self.celery_broker_url

    @property
    def CELERY_RESULT_BACKEND(self) -> str:
        """
        Celery result backend URL.

        Uses CELERY_RESULT_BACKEND_OVERRIDE env var if set, otherwise uses broker URL.
        """
        if self.CELERY_RESULT_BACKEND_OVERRIDE:
            return self.CELERY_RESULT_BACKEND_OVERRIDE
        return self.celery_broker_url

    # ============================================================================
    # Exchange API Configuration (from environment only!)
    # ============================================================================

    OKX_API_KEY: str = ""
    OKX_SECRET_KEY: str = ""
    OKX_PASSPHRASE: str = ""

    # Main account credentials (for multi-account support)
    MAIN_OKX_KEY: str = Field(default="", description="Main OKX account API key")
    MAIN_OKX_SECRET_KEY: str = Field(default="", description="Main OKX account secret key")
    MAIN_OKX_PASSPHRASE: str = Field(default="", description="Main OKX account passphrase")

    BINANCE_API_KEY: str = ""
    BINANCE_SECRET_KEY: str = ""

    BYBIT_API_KEY: str = ""
    BYBIT_SECRET_KEY: str = ""

    UPBIT_ACCESS_KEY: str = ""
    UPBIT_SECRET_KEY: str = ""

    # ============================================================================
    # Telegram Bot Configuration
    # ============================================================================

    TELEGRAM_BOT_TOKEN: str = ""
    OWNER_ID: int = 0
    DEBUG_TELEGRAM_ID: int = Field(
        default=0,
        description="Debug telegram ID for development/testing"
    )

    # ============================================================================
    # Logging Configuration
    # ============================================================================

    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    LOG_JSON: bool = False  # Enable JSON structured logging

    # ============================================================================
    # WebSocket Configuration
    # ============================================================================

    WEBSOCKET_PING_INTERVAL: int = 30
    WEBSOCKET_PING_TIMEOUT: int = 10
    WEBSOCKET_MAX_RECONNECT_ATTEMPTS: int = 5
    WEBSOCKET_RECONNECT_DELAY: int = 5

    # ============================================================================
    # API Configuration
    # ============================================================================

    API_REQUEST_TIMEOUT: int = 30
    API_RETRY_COUNT: int = 5
    API_RATE_LIMIT: int = 100  # requests per minute

    # Internal API endpoints (for microservice communication)
    HYPERRSI_API_HOST: str = Field(
        default="localhost",
        description="HYPERRSI API host for internal service calls"
    )
    HYPERRSI_API_PORT: int = Field(
        default=8000,
        ge=1,
        le=65535,
        description="HYPERRSI API port"
    )

    @property
    def hyperrsi_api_url(self) -> str:
        """HYPERRSI API base URL for internal service communication"""
        return f"http://{self.HYPERRSI_API_HOST}:{self.HYPERRSI_API_PORT}/api"

    # ============================================================================
    # Order Backend Configuration (Optional)
    # ============================================================================

    ORDER_BACKEND: str = ""  # Remote order processing backend

    # ============================================================================
    # Security Configuration
    # ============================================================================

    SECRET_KEY: str = ""  # For JWT token signing
    ENCRYPTION_KEY: Optional[str] = None  # For API key encryption (Fernet)
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # ============================================================================
    # Performance Configuration
    # ============================================================================

    CACHE_TTL: int = 300  # 5 minutes default cache TTL
    ENABLE_QUERY_CACHE: bool = True

    # ============================================================================
    # Feature Flags
    # ============================================================================

    ENABLE_METRICS: bool = Field(default=False, description="Enable metrics collection")
    ENABLE_AUDIT_LOG: bool = Field(default=False, description="Enable audit logging")

    # Redis Migration Feature Flags (for safe phased rollout)
    REDIS_MIGRATION_ENABLED: bool = Field(
        default=False,
        description="Enable Redis pattern migration from get_redis_client() to redis_context()"
    )
    REDIS_MIGRATION_PERCENTAGE: int = Field(
        default=0,
        ge=0,
        le=100,
        description="Percentage of users using new Redis pattern (0-100)"
    )
    REDIS_MIGRATION_USER_WHITELIST: str = Field(
        default="",
        description="Comma-separated user IDs for targeted migration testing"
    )

    # ============================================================================
    # Validation
    # ============================================================================

    @model_validator(mode='after')
    def validate_production_requirements(self) -> 'Settings':
        """
        Ensure production environment has required configuration.

        Validates:
        - Database configuration (URL or components)
        - Exchange API credentials (at least OKX)
        - Telegram bot configuration

        Raises:
            ValueError: If required production configuration is missing
        """
        if self.ENVIRONMENT == "production":
            errors = []

            # Check database configuration
            has_db_url = bool(self.DATABASE_URL)
            has_db_components = all([self.DB_USER, self.DB_PASSWORD, self.DB_HOST, self.DB_NAME])

            if not (has_db_url or has_db_components):
                errors.append("Database configuration (DATABASE_URL or DB_* variables)")

            # Check exchange credentials (OKX is primary)
            if not all([self.OKX_API_KEY, self.OKX_SECRET_KEY, self.OKX_PASSPHRASE]):
                errors.append("OKX API credentials (OKX_API_KEY, OKX_SECRET_KEY, OKX_PASSPHRASE)")

            # Check Telegram configuration
            if not self.TELEGRAM_BOT_TOKEN:
                errors.append("Telegram configuration (TELEGRAM_BOT_TOKEN)")

            if errors:
                raise ValueError(
                    f"Production environment requires: {', '.join(errors)}"
                )

        # Auto-disable DEBUG in production
        if self.ENVIRONMENT == "production":
            object.__setattr__(self, 'DEBUG', False)

        return self


@lru_cache()
def get_settings() -> Settings:
    """
    Get cached settings instance.

    Returns:
        Settings: Singleton settings instance
    """
    return Settings()


# Global settings instance
settings = get_settings()


# Backward compatibility exports
# These allow gradual migration from old config imports
OKX_API_KEY = settings.OKX_API_KEY
OKX_SECRET_KEY = settings.OKX_SECRET_KEY
OKX_PASSPHRASE = settings.OKX_PASSPHRASE
TELEGRAM_BOT_TOKEN = settings.TELEGRAM_BOT_TOKEN
OWNER_ID = settings.OWNER_ID
DEBUG_TELEGRAM_ID = settings.DEBUG_TELEGRAM_ID
DATABASE_URL = settings.DATABASE_URL
REDIS_URL = settings.REDIS_URL
REDIS_HOST = settings.REDIS_HOST
REDIS_PORT = settings.REDIS_PORT
REDIS_PASSWORD = settings.REDIS_PASSWORD
