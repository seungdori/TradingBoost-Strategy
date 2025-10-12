"""
GRID PostgreSQL Database Connection Module

Provides database session management and initialization using shared infrastructure.
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from GRID.models.base import Base
from shared.database.session import DatabaseConfig, get_db
from shared.errors import DatabaseException
from shared.logging import get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def get_grid_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Get database session for GRID operations.

    This is a wrapper around shared get_db() for GRID-specific usage.

    Usage:
        async with get_grid_db() as session:
            user = await user_repository.get_by_id(session, user_id)

    Yields:
        AsyncSession: Database session with auto-commit/rollback
    """
    async with get_db() as session:
        yield session


async def init_grid_db():
    """
    Initialize GRID database tables.

    Creates all GRID-specific tables if they don't exist.
    Includes both user models and trading models.

    Raises:
        DatabaseException: Database initialization failed
    """
    try:
        logger.info("Initializing GRID database tables...")

        # Import models to register them with SQLAlchemy
        from GRID.models import trading  # Entry, TakeProfit, StopLoss, WinRate
        from GRID.models import user  # User, TelegramID, Job, Blacklist, Whitelist

        engine = DatabaseConfig.get_engine()

        # Create all tables
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        # Test connection
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))

        logger.info("✅ GRID database tables initialized successfully")

    except Exception as e:
        logger.error(
            "Failed to initialize GRID database",
            exc_info=True
        )
        raise DatabaseException(
            "Failed to initialize GRID database",
            details={"error": str(e)}
        )


async def close_grid_db():
    """
    Close GRID database connections.

    Call this during application shutdown.
    """
    try:
        logger.info("Closing GRID database connections...")
        await DatabaseConfig.close_engine()
        logger.info("✅ GRID database connections closed")
    except Exception as e:
        logger.error(
            "Error closing GRID database connections",
            exc_info=True
        )
        # Don't raise - allow shutdown to continue
