"""
Error Database Session Management (Separate Pool)

에러 로깅 전용 DB connection pool.
메인 tradeDB pool과 완전히 분리되어 pool 고갈 문제를 방지합니다.
"""

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import QueuePool

from shared.config.settings import settings
from shared.logging import get_logger

logger = get_logger(__name__)


class ErrorDatabaseConfig:
    """
    에러 DB 전용 설정 (tradeDB와 완전히 독립적)

    Pool 설정:
    - pool_size: 3 (에러 로깅은 많은 연결 필요 없음)
    - max_overflow: 5
    - Total: 8 connections (tradeDB와 별도)
    """

    _engine: AsyncEngine | None = None
    _session_factory: async_sessionmaker[AsyncSession] | None = None

    @classmethod
    def get_engine(cls) -> AsyncEngine:
        """
        에러 DB 전용 엔진 생성 (tradeDB와 완전히 분리)

        Returns:
            AsyncEngine: 에러 DB 전용 엔진
        """
        if cls._engine is None:
            # 에러 DB URL (없으면 메인 DB 사용)
            error_db_url = getattr(settings, 'ERROR_DB_URL', None) or settings.db_url

            # errorDB를 명시적으로 지정 (URL에 errorDB/errordb 포함 확인)
            if 'errordb' not in error_db_url.lower() and error_db_url:
                # postgresql+asyncpg://user:pass@host:port/tradeDB
                # → postgresql+asyncpg://user:pass@host:port/errordb
                error_db_url = error_db_url.rsplit('/', 1)[0] + '/errordb'

            logger.info(f"Creating Error DB engine (separate pool): {error_db_url[:50]}...")

            # 에러 로깅용은 작은 pool로 충분
            cls._engine = create_async_engine(
                error_db_url,
                echo=settings.DEBUG,

                # 작은 pool 설정 (에러 로깅은 동시성 낮음)
                poolclass=QueuePool,
                pool_size=3,  # 메인 DB보다 작게
                max_overflow=5,
                pool_timeout=10,  # 짧은 타임아웃
                pool_recycle=1800,  # 30분마다 재활용
                pool_pre_ping=True,

                # PostgreSQL 설정
                connect_args={
                    "server_settings": {
                        "application_name": f"ErrorDB-{settings.ENVIRONMENT}",
                    },
                    "command_timeout": 10,
                },

                echo_pool=settings.DEBUG,
                isolation_level="READ COMMITTED",
            )

            logger.info(
                "Error DB engine created (SEPARATE POOL)",
                extra={
                    "pool_size": 3,
                    "max_overflow": 5,
                    "total_connections": 8,
                    "separate_from_tradeDB": True
                }
            )

        return cls._engine

    @classmethod
    def get_session_factory(cls) -> async_sessionmaker[AsyncSession]:
        """에러 DB 세션 팩토리"""
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
    async def close_engine(cls):
        """에러 DB 엔진 종료"""
        if cls._engine is not None:
            try:
                await asyncio.wait_for(cls._engine.dispose(), timeout=3.0)
                logger.info("Error DB engine closed")
            except asyncio.TimeoutError:
                logger.warning("Error DB engine disposal timed out")
            except Exception as e:
                logger.error(f"Error closing Error DB engine: {e}", exc_info=True)
            finally:
                cls._engine = None
                cls._session_factory = None


@asynccontextmanager
async def get_error_db() -> AsyncGenerator[AsyncSession, None]:
    """
    에러 DB 세션 (읽기/쓰기)

    Usage:
        async with get_error_db() as db:
            await ErrorLogService.create_error_log(db, ...)
    """
    session_factory = ErrorDatabaseConfig.get_session_factory()
    async with session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


@asynccontextmanager
async def get_error_db_transactional() -> AsyncGenerator[AsyncSession, None]:
    """
    에러 DB 세션 (자동 커밋)

    Usage:
        async with get_error_db_transactional() as db:
            await ErrorLogService.create_error_log(db, ...)
            # 자동 commit
    """
    session_factory = ErrorDatabaseConfig.get_session_factory()
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_error_db():
    """에러 DB 초기화"""
    from sqlalchemy import text

    engine = ErrorDatabaseConfig.get_engine()

    # 연결 테스트
    async with engine.begin() as conn:
        await conn.execute(text("SELECT 1"))

    logger.info("Error DB connected (separate pool)")
    print("✅ Error DB connected (separate pool from tradeDB)")


async def close_error_db():
    """에러 DB 연결 종료"""
    await ErrorDatabaseConfig.close_engine()
    logger.info("Error DB connections closed")
    print("✅ Error DB connections closed")
