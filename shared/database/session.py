"""
Database Session Management with Transaction Support

Provides async session management with proper transaction boundaries,
connection pooling, and error handling.
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool, QueuePool

from shared.config.settings import settings
from shared.database.pool_monitor import PoolMonitor
from shared.logging import get_logger

logger = get_logger(__name__)


class DatabaseConfig:
    """Database configuration and engine management"""

    _engine: AsyncEngine | None = None
    _session_factory: async_sessionmaker[AsyncSession] | None = None
    _monitor: PoolMonitor | None = None

    @classmethod
    def get_engine(cls) -> AsyncEngine:
        """
        Get or create database engine with optimized connection pooling.

        Features:
        - Environment-specific pool configuration
        - Connection health checks (pre-ping)
        - Automatic connection recycling
        - Application identification
        - Logging and monitoring

        Returns:
            AsyncEngine: Configured database engine
        """
        if cls._engine is None:
            # Determine pool class based on environment
            pool_class = NullPool if settings.ENVIRONMENT == "test" else QueuePool  # type: ignore[comparison-overlap]

            # Use db_url property for proper URL construction
            db_url = settings.db_url

            # Debug logging
            logger.info(f"Database URL: {db_url[:50]}..." if db_url else "Database URL: EMPTY")
            if not db_url:
                raise ValueError("PostgreSQL configuration required. DATABASE_URL is empty!")

            # Build connect_args and isolation_level based on database type
            connect_args = {}
            isolation_level = None
            if "postgresql" in db_url:
                connect_args = {
                    "server_settings": {
                        "application_name": f"TradingBoost-{settings.ENVIRONMENT}",
                        "jit": "off",  # Disable JIT for consistent performance
                    },
                    "command_timeout": settings.DB_POOL_TIMEOUT,
                }
                isolation_level = "READ COMMITTED"  # PostgreSQL default

            cls._engine = create_async_engine(
                db_url,
                echo=settings.DEBUG,

                # Pool configuration
                poolclass=pool_class,
                pool_size=settings.DB_POOL_SIZE,
                max_overflow=settings.DB_MAX_OVERFLOW,
                pool_timeout=settings.DB_POOL_TIMEOUT,
                pool_recycle=settings.DB_POOL_RECYCLE,
                pool_pre_ping=settings.DB_POOL_PRE_PING,

                # Connection arguments
                connect_args=connect_args,

                # Logging
                echo_pool=settings.DEBUG,

                # Performance (only for PostgreSQL)
                **({"isolation_level": isolation_level} if isolation_level else {}),
            )

            logger.info(
                "Database engine created",
                extra={
                    "pool_size": settings.DB_POOL_SIZE,
                    "max_overflow": settings.DB_MAX_OVERFLOW,
                    "pool_timeout": settings.DB_POOL_TIMEOUT,
                    "environment": settings.ENVIRONMENT,
                    "database_type": "postgresql" if "postgresql" in db_url else "sqlite"
                }
            )

            # Initialize pool monitor
            cls._monitor = PoolMonitor(cls._engine, leak_threshold=0.8)
            logger.info("Database pool monitor initialized")

        return cls._engine

    @classmethod
    def get_session_factory(cls) -> async_sessionmaker[AsyncSession]:
        """
        Get or create session factory.

        Returns:
            async_sessionmaker: Session factory
        """
        if cls._session_factory is None:
            engine = cls.get_engine()
            cls._session_factory = async_sessionmaker(
                engine,
                class_=AsyncSession,
                expire_on_commit=False,
                autoflush=False,
                autocommit=False,
            )

        return cls._session_factory

    @classmethod
    def get_monitor(cls) -> PoolMonitor:
        """
        Get connection pool monitor.

        Returns:
            PoolMonitor: Pool monitoring instance
        """
        if cls._monitor is None:
            # Ensure engine is created first
            cls.get_engine()

        assert cls._monitor is not None, "Monitor should be initialized after get_engine()"
        return cls._monitor

    @classmethod
    def health_check(cls) -> dict:
        """
        Perform health check on database connection pool.

        Returns:
            dict: Health status with metrics and recommendations

        Example:
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
        monitor = cls.get_monitor()
        return monitor.check_health()

    @classmethod
    async def warm_up_pool(cls, connections: int | None = None) -> None:
        """
        Pre-create database connections to avoid cold start.

        Useful for reducing first-request latency after startup.

        Args:
            connections: Number of connections to create (default: pool_size)
        """
        monitor = cls.get_monitor()
        await monitor.warm_up_pool(connections)

    @classmethod
    async def close_engine(cls):
        """Close database engine and cleanup connections"""
        if cls._engine is not None:
            await cls._engine.dispose()
            cls._engine = None
            cls._session_factory = None
            cls._monitor = None


@asynccontextmanager
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency for database sessions (without auto-commit).

    Provides a database session with manual transaction control.
    Use transactional() context manager for explicit commits.

    This is the recommended pattern for service-layer operations
    where you need explicit control over transaction boundaries.

    Usage in FastAPI:
        @router.post("/orders")
        async def create_order(
            order_data: OrderCreate,
            db: AsyncSession = Depends(get_db)
        ):
            from shared.database.transactions import transactional

            async with transactional(db) as tx:
                order = await create_order_in_db(tx, order_data)
                await update_balance(tx, order.user_id, -order.amount)
                # Commits automatically on success
            return order

    Yields:
        AsyncSession: Database session (manual commit required)
    """
    session_factory = DatabaseConfig.get_session_factory()
    async with session_factory() as session:
        try:
            yield session
            # Don't auto-commit - let transactional() handle it
        except Exception as e:
            logger.error("Session error", exc_info=True)
            await session.rollback()
            raise
        finally:
            await session.close()


@asynccontextmanager
async def get_transactional_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency for database sessions (with auto-commit).

    Provides a database session that automatically commits on success.
    Use this for simple, single-operation endpoints.

    For complex operations requiring multiple steps, use get_db()
    with explicit transactional() context manager instead.

    Usage in FastAPI:
        @router.post("/simple")
        async def simple_create(
            data: CreateDto,
            db: AsyncSession = Depends(get_transactional_db)
        ):
            # Auto-commits on success
            return await repository.create(db, data)

    Yields:
        AsyncSession: Database session (auto-commits)
    """
    session_factory = DatabaseConfig.get_session_factory()
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


@asynccontextmanager
async def transactional_session(
    session: AsyncSession,
) -> AsyncGenerator[AsyncSession, None]:
    """
    Context manager for explicit transactional operations.

    Use this when you need explicit control over transaction boundaries,
    such as in service layers where multiple repository calls must be atomic.

    Usage:
        async def create_order(self, order_data: OrderDto):
            async with transactional_session(self.session) as session:
                # All operations within this block are atomic
                order = await self.order_repo.create(session, order_data)
                await self.balance_repo.update(session, order.user_id, -order.amount)
                await self.notification_repo.send(session, order.id)
                # Commits automatically on success, rolls back on error

    Args:
        session: Existing database session

    Yields:
        AsyncSession: Same session with transaction management
    """
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise


@asynccontextmanager
async def get_transactional_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Get a new database session with automatic transaction management.

    This is a convenience function that combines session creation and
    transaction management in one step.

    Usage:
        async with get_transactional_session() as session:
            user = await create_user(session, user_data)
            await create_profile(session, user.id, profile_data)
            # Automatically commits on success

    Yields:
        AsyncSession: New session with transaction management
    """
    session_factory = DatabaseConfig.get_session_factory()
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# FastAPI dependency for read-only operations (no auto-commit)
@asynccontextmanager
async def get_db_readonly() -> AsyncGenerator[AsyncSession, None]:
    """
    Get database session for read-only operations.

    This session doesn't auto-commit, suitable for queries that don't
    modify data.

    Usage:
        @router.get("/users/{user_id}")
        async def get_user(
            user_id: int,
            db: AsyncSession = Depends(get_db_readonly)
        ):
            user = await get_user_by_id(db, user_id)
            return user

    Yields:
        AsyncSession: Database session (read-only mode)
    """
    session_factory = DatabaseConfig.get_session_factory()
    async with session_factory() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db():
    """
    Initialize database engine and create tables.

    Call this during application startup.
    """
    from sqlalchemy import text

    engine = DatabaseConfig.get_engine()

    # Test connection
    async with engine.begin() as conn:
        await conn.execute(text("SELECT 1"))

    db_url = settings.db_url
    db_display = db_url.split('@')[1] if '@' in db_url else 'local'

    logger.info(f"Database connected: {db_display}")
    print(f"✅ Database connected: {db_display}")


async def close_db():
    """
    Close database connections.

    Call this during application shutdown.
    """
    await DatabaseConfig.close_engine()
    logger.info("Database connections closed")
    print("✅ Database connections closed")
