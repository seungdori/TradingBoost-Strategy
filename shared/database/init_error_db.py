"""
Error Database Initialization Helper

에러 DB를 초기화하고 테이블을 생성하는 유틸리티입니다.
"""

import asyncio
from sqlalchemy import text

from shared.config.settings import settings
from shared.database.error_db_session import ErrorDatabaseConfig, init_error_db, close_error_db
from shared.logging import get_logger

logger = get_logger(__name__)


async def create_error_logs_table():
    """
    error_logs 테이블을 생성합니다.
    이미 존재하면 건너뜁니다.
    """
    engine = ErrorDatabaseConfig.get_engine()

    create_table_sql = """
    CREATE TABLE IF NOT EXISTS error_logs (
        id SERIAL PRIMARY KEY,
        timestamp TIMESTAMP NOT NULL DEFAULT NOW(),
        user_id VARCHAR(255),
        telegram_id INTEGER,
        error_type VARCHAR(100) NOT NULL,
        severity VARCHAR(20) NOT NULL DEFAULT 'ERROR',
        strategy_type VARCHAR(50),
        error_message TEXT NOT NULL,
        error_details JSONB,
        module VARCHAR(255),
        function VARCHAR(255),
        traceback TEXT,
        metadata JSONB,
        resolved INTEGER NOT NULL DEFAULT 0,
        resolved_at TIMESTAMP
    );
    """

    # 각 인덱스를 개별적으로 생성 (asyncpg는 multiple statements를 지원하지 않음)
    create_indexes_sqls = [
        "CREATE INDEX IF NOT EXISTS idx_error_logs_timestamp ON error_logs(timestamp)",
        "CREATE INDEX IF NOT EXISTS idx_error_logs_user_id ON error_logs(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_error_logs_telegram_id ON error_logs(telegram_id)",
        "CREATE INDEX IF NOT EXISTS idx_error_logs_error_type ON error_logs(error_type)",
        "CREATE INDEX IF NOT EXISTS idx_error_logs_strategy_type ON error_logs(strategy_type)",
        "CREATE INDEX IF NOT EXISTS idx_error_logs_severity ON error_logs(severity)",
        "CREATE INDEX IF NOT EXISTS idx_error_logs_resolved ON error_logs(resolved)",
        "CREATE INDEX IF NOT EXISTS idx_error_logs_timestamp_user ON error_logs(timestamp, user_id)",
        "CREATE INDEX IF NOT EXISTS idx_error_logs_timestamp_strategy ON error_logs(timestamp, strategy_type)",
    ]

    try:
        async with engine.begin() as conn:
            # 테이블 생성
            await conn.execute(text(create_table_sql))
            logger.info("✅ error_logs table created (or already exists)")

            # 인덱스 생성 (각각 개별 실행)
            for idx_sql in create_indexes_sqls:
                await conn.execute(text(idx_sql))
            logger.info(f"✅ error_logs indexes created ({len(create_indexes_sqls)} indexes)")

        print("✅ Error database initialized successfully")
        return True

    except Exception as e:
        logger.error(f"Failed to create error_logs table: {e}")
        print(f"❌ Failed to initialize error database: {e}")
        return False


async def initialize_error_database():
    """
    에러 DB를 완전히 초기화합니다 (연결 테스트 + 테이블 생성).
    """
    try:
        # 1. 연결 테스트
        await init_error_db()

        # 2. 테이블 생성
        success = await create_error_logs_table()

        if success:
            logger.info("Error database initialization completed")
            print("\n" + "="*60)
            print("✅ Error Database Initialization Complete")
            print("="*60)
            print(f"Database: errorDB (separate pool)")
            print(f"Pool Size: 3 + 5 overflow = 8 connections")
            print(f"Independent from main tradeDB pool")
            print("="*60 + "\n")
        else:
            raise Exception("Failed to create error_logs table")

    except Exception as e:
        logger.error(f"Error database initialization failed: {e}")
        print(f"\n❌ Error Database Initialization Failed: {e}")
        print("Please check:")
        print("1. errorDB database exists in PostgreSQL")
        print("2. ERROR_DB_URL is set in .env")
        print("3. Database connection settings are correct\n")
        raise


async def verify_error_database():
    """
    에러 DB가 정상 작동하는지 확인합니다.
    """
    from shared.database.error_log_service import ErrorLogService
    from shared.database.error_db_session import get_error_db_transactional

    try:
        async with get_error_db_transactional() as db:
            # 테스트 에러 로그 생성
            test_log = await ErrorLogService.create_error_log(
                db=db,
                error_type="TEST_ERROR",
                error_message="Database verification test",
                severity="INFO",
                strategy_type="SYSTEM",
                metadata={"test": True}
            )

            logger.info(f"Test error log created: {test_log.id}")

            # 테스트 로그 삭제
            from sqlalchemy import delete
            from shared.database.models import ErrorLog
            await db.execute(delete(ErrorLog).where(ErrorLog.id == test_log.id))
            await db.commit()

            logger.info("Error database verification successful")
            print("✅ Error database verification passed")
            return True

    except Exception as e:
        logger.error(f"Error database verification failed: {e}")
        print(f"❌ Error database verification failed: {e}")
        return False


if __name__ == "__main__":
    """
    스크립트로 직접 실행 시 에러 DB를 초기화합니다.

    Usage:
        python shared/database/init_error_db.py
    """
    async def main():
        try:
            await initialize_error_database()
            await verify_error_database()
            await close_error_db()
        except Exception as e:
            print(f"Initialization failed: {e}")
            await close_error_db()

    asyncio.run(main())
