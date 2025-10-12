"""Database Connection Management

Handles PostgreSQL connection pooling and session management.
"""

import asyncio
from typing import Optional, AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    create_async_engine,
    AsyncSession,
    AsyncEngine,
    async_sessionmaker
)
from sqlalchemy.pool import NullPool, QueuePool

from shared.logging import get_logger
from shared.config import get_settings

logger = get_logger(__name__)
settings = get_settings()


class DatabaseManager:
    """
    Async PostgreSQL database manager with connection pooling.

    Features:
    - Async SQLAlchemy engine
    - Connection pooling
    - Health monitoring
    - Auto-reconnection
    """

    def __init__(self, database_url: Optional[str] = None):
        """
        Args:
            database_url: PostgreSQL connection URL
                         Format: postgresql+asyncpg://user:pass@host:port/dbname
        """
        self.database_url = database_url or getattr(settings, 'DATABASE_URL', None)

        if not self.database_url:
            logger.warning("No DATABASE_URL configured - PostgreSQL persistence disabled")
            self.enabled = False
            return

        self.enabled = True
        self.engine: Optional[AsyncEngine] = None
        self.session_maker: Optional[async_sessionmaker] = None

        # Pool settings
        self.pool_size = 5
        self.max_overflow = 10
        self.pool_timeout = 30.0
        self.pool_recycle = 3600  # 1 hour

    async def initialize(self):
        """Initialize database engine and session maker"""
        if not self.enabled:
            logger.info("PostgreSQL disabled - using Redis only")
            return

        try:
            logger.info(f"Initializing PostgreSQL connection...")

            # Create async engine with pooling
            self.engine = create_async_engine(
                self.database_url,
                poolclass=QueuePool,
                pool_size=self.pool_size,
                max_overflow=self.max_overflow,
                pool_timeout=self.pool_timeout,
                pool_recycle=self.pool_recycle,
                pool_pre_ping=True,  # Test connections before using
                echo=False,  # Set to True for SQL debugging
            )

            # Create session maker
            self.session_maker = async_sessionmaker(
                self.engine,
                class_=AsyncSession,
                expire_on_commit=False
            )

            # Test connection
            await self.health_check()

            logger.info("✅ PostgreSQL connection initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize PostgreSQL: {e}", exc_info=True)
            self.enabled = False
            raise

    async def close(self):
        """Close database connections"""
        if self.engine:
            await self.engine.dispose()
            logger.info("PostgreSQL connections closed")

    @asynccontextmanager
    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        """
        Get database session with automatic cleanup.

        Usage:
            async with db_manager.get_session() as session:
                await session.execute(...)
                await session.commit()
        """
        if not self.enabled or not self.session_maker:
            raise RuntimeError("Database not initialized or disabled")

        session = self.session_maker()
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def health_check(self) -> bool:
        """
        Check database connection health.

        Returns:
            True if connection is healthy
        """
        if not self.enabled or not self.engine:
            return False

        try:
            async with self.engine.connect() as conn:
                await conn.execute("SELECT 1")
            return True
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            return False

    async def create_tables(self):
        """Create all tables defined in models"""
        if not self.enabled or not self.engine:
            logger.warning("Cannot create tables - database not enabled")
            return

        try:
            from .models import Base

            async with self.engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            logger.info("✅ Database tables created successfully")

        except Exception as e:
            logger.error(f"Failed to create tables: {e}", exc_info=True)
            raise


# Global database manager instance
_db_manager: Optional[DatabaseManager] = None


async def get_db_manager() -> DatabaseManager:
    """Get or create global database manager instance"""
    global _db_manager

    if _db_manager is None:
        _db_manager = DatabaseManager()
        await _db_manager.initialize()

    return _db_manager


async def init_database():
    """Initialize database and create tables"""
    db_manager = await get_db_manager()
    await db_manager.create_tables()
