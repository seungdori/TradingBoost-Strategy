#!/usr/bin/env python
"""
Error Database Setup Verification Script

에러 DB 설정이 올바르게 되었는지 확인하는 스크립트입니다.

Usage:
    python verify_error_db_setup.py
"""

import asyncio
import sys
from typing import List, Tuple

from shared.config.settings import settings
from shared.logging import get_logger

logger = get_logger(__name__)


class SetupVerifier:
    """에러 DB 설정 검증 클래스"""

    def __init__(self):
        self.checks_passed = 0
        self.checks_failed = 0
        self.warnings = 0

    def print_header(self):
        """헤더 출력"""
        print("\n" + "=" * 70)
        print("🔍 Error Database Setup Verification")
        print("=" * 70 + "\n")

    def print_check(self, name: str, passed: bool, message: str = "", warning: bool = False):
        """체크 결과 출력"""
        if passed:
            icon = "✅"
            self.checks_passed += 1
        elif warning:
            icon = "⚠️"
            self.warnings += 1
        else:
            icon = "❌"
            self.checks_failed += 1

        print(f"{icon} {name}")
        if message:
            print(f"   → {message}")
        print()

    def print_summary(self):
        """요약 출력"""
        print("=" * 70)
        print(f"📊 Summary: {self.checks_passed} passed, {self.checks_failed} failed, {self.warnings} warnings")
        print("=" * 70 + "\n")

        if self.checks_failed == 0 and self.warnings == 0:
            print("🎉 All checks passed! Error database is ready to use.")
            return True
        elif self.checks_failed == 0:
            print("⚠️  Setup is functional but has warnings. Review above messages.")
            return True
        else:
            print("❌ Setup has errors. Please fix the issues above.")
            return False

    async def check_env_variables(self) -> bool:
        """환경 변수 확인"""
        print("📋 Checking environment variables...")
        print()

        # DATABASE_URL
        has_db_url = bool(settings.DATABASE_URL or (settings.DB_USER and settings.DB_HOST and settings.DB_NAME))
        self.print_check(
            "Main DATABASE_URL configured",
            has_db_url,
            settings.DATABASE_URL[:50] + "..." if settings.DATABASE_URL else "Constructed from DB_* variables"
        )

        # ERROR_DB_URL
        has_error_db = bool(settings.ERROR_DB_URL)
        if has_error_db:
            self.print_check(
                "ERROR_DB_URL configured",
                True,
                settings.ERROR_DB_URL[:50] + "..."
            )
        else:
            self.print_check(
                "ERROR_DB_URL not set",
                True,
                "Will use main DATABASE_URL (pool still separate)",
                warning=True
            )

        return has_db_url

    async def check_database_connection(self) -> bool:
        """데이터베이스 연결 확인"""
        print("🔌 Checking database connections...")
        print()

        # Main DB
        try:
            from shared.database.session import DatabaseConfig
            from sqlalchemy import text

            engine = DatabaseConfig.get_engine()
            async with engine.begin() as conn:
                result = await conn.execute(text("SELECT 1"))
                result.fetchone()

            self.print_check("Main database connection", True, "Successfully connected to tradeDB")
        except Exception as e:
            self.print_check("Main database connection", False, f"Failed: {e}")
            return False

        # Error DB
        try:
            from shared.database.error_db_session import ErrorDatabaseConfig

            error_engine = ErrorDatabaseConfig.get_engine()
            async with error_engine.begin() as conn:
                result = await conn.execute(text("SELECT 1"))
                result.fetchone()

            # Check database name
            async with error_engine.begin() as conn:
                result = await conn.execute(text("SELECT current_database()"))
                db_name = result.fetchone()[0]

            self.print_check(
                "Error database connection",
                True,
                f"Successfully connected to {db_name}"
            )

            if db_name != "errorDB":
                self.print_check(
                    "Error database name",
                    True,
                    f"Using '{db_name}' instead of 'errorDB'",
                    warning=True
                )

        except Exception as e:
            self.print_check("Error database connection", False, f"Failed: {e}")
            return False

        return True

    async def check_error_logs_table(self) -> bool:
        """error_logs 테이블 확인"""
        print("📊 Checking error_logs table...")
        print()

        try:
            from shared.database.error_db_session import ErrorDatabaseConfig
            from sqlalchemy import text

            engine = ErrorDatabaseConfig.get_engine()

            # 테이블 존재 확인
            async with engine.begin() as conn:
                result = await conn.execute(text("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables
                        WHERE table_name = 'error_logs'
                    )
                """))
                table_exists = result.fetchone()[0]

            if table_exists:
                self.print_check("error_logs table exists", True)

                # 컬럼 확인
                async with engine.begin() as conn:
                    result = await conn.execute(text("""
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_name = 'error_logs'
                        ORDER BY ordinal_position
                    """))
                    columns = [row[0] for row in result.fetchall()]

                expected_columns = [
                    'id', 'timestamp', 'user_id', 'telegram_id',
                    'error_type', 'severity', 'strategy_type',
                    'error_message', 'error_details', 'module',
                    'function', 'traceback', 'metadata',
                    'resolved', 'resolved_at'
                ]

                missing_columns = set(expected_columns) - set(columns)
                if missing_columns:
                    self.print_check(
                        "error_logs table schema",
                        False,
                        f"Missing columns: {', '.join(missing_columns)}"
                    )
                else:
                    self.print_check("error_logs table schema", True, f"{len(columns)} columns found")

                # 인덱스 확인
                async with engine.begin() as conn:
                    result = await conn.execute(text("""
                        SELECT indexname
                        FROM pg_indexes
                        WHERE tablename = 'error_logs'
                    """))
                    indexes = [row[0] for row in result.fetchall()]

                self.print_check(
                    "error_logs indexes",
                    len(indexes) > 0,
                    f"{len(indexes)} indexes found"
                )

                return True
            else:
                self.print_check(
                    "error_logs table exists",
                    False,
                    "Table not found. Run: python shared/database/init_error_db.py"
                )
                return False

        except Exception as e:
            self.print_check("error_logs table check", False, f"Failed: {e}")
            return False

    async def check_connection_pools(self) -> bool:
        """Connection pool 설정 확인"""
        print("🏊 Checking connection pools...")
        print()

        try:
            from shared.database.session import DatabaseConfig
            from shared.database.error_db_session import ErrorDatabaseConfig

            # Main pool
            main_engine = DatabaseConfig.get_engine()
            main_pool = main_engine.pool

            self.print_check(
                "Main database pool",
                True,
                f"Size: {main_pool.size()} / Overflow: {main_pool._max_overflow}"
            )

            # Error pool
            error_engine = ErrorDatabaseConfig.get_engine()
            error_pool = error_engine.pool

            self.print_check(
                "Error database pool",
                True,
                f"Size: {error_pool.size()} / Overflow: {error_pool._max_overflow}"
            )

            # Check if they're separate
            pools_separate = main_engine is not error_engine
            self.print_check(
                "Pools are independent",
                pools_separate,
                "Main and Error pools use separate engines" if pools_separate else "Pools share the same engine"
            )

            return True

        except Exception as e:
            self.print_check("Connection pool check", False, f"Failed: {e}")
            return False

    async def check_redis_connection(self) -> bool:
        """Redis 연결 확인 (중복 제거용)"""
        print("🔴 Checking Redis connection (for deduplication)...")
        print()

        try:
            from shared.database.redis import get_redis

            redis = get_redis()
            await redis.ping()

            self.print_check("Redis connection", True, "Successfully connected")
            return True

        except Exception as e:
            self.print_check("Redis connection", False, f"Failed: {e}")
            return False

    async def test_error_logging(self) -> bool:
        """에러 로깅 테스트"""
        print("🧪 Testing error logging functionality...")
        print()

        try:
            from shared.database.error_db_session import get_error_db_transactional
            from shared.database.error_log_service import ErrorLogService
            from sqlalchemy import delete
            from shared.database.models import ErrorLog

            # 테스트 에러 로그 생성
            async with get_error_db_transactional() as db:
                test_log = await ErrorLogService.create_error_log(
                    db=db,
                    error_type="VERIFICATION_TEST",
                    error_message="This is a test error log from verification script",
                    severity="INFO",
                    strategy_type="SYSTEM",
                    metadata={"test": True, "script": "verify_error_db_setup.py"}
                )

                log_id = test_log.id

            self.print_check(
                "Error log creation",
                True,
                f"Test log created with ID: {log_id}"
            )

            # 테스트 로그 조회
            async with get_error_db_transactional() as db:
                logs = await ErrorLogService.get_error_logs(
                    db=db,
                    error_type="VERIFICATION_TEST",
                    limit=1
                )

                found = len(logs) > 0

            self.print_check(
                "Error log retrieval",
                found,
                "Test log successfully retrieved"
            )

            # 테스트 로그 삭제
            async with get_error_db_transactional() as db:
                await db.execute(delete(ErrorLog).where(ErrorLog.id == log_id))
                await db.commit()

            self.print_check(
                "Error log cleanup",
                True,
                "Test log deleted"
            )

            return True

        except Exception as e:
            self.print_check("Error logging test", False, f"Failed: {e}")
            return False

    async def run_all_checks(self) -> bool:
        """모든 체크 실행"""
        self.print_header()

        checks = [
            self.check_env_variables(),
            self.check_database_connection(),
            self.check_error_logs_table(),
            self.check_connection_pools(),
            self.check_redis_connection(),
            self.test_error_logging()
        ]

        for check in checks:
            await check

        print()
        return self.print_summary()


async def main():
    """메인 함수"""
    verifier = SetupVerifier()

    try:
        success = await verifier.run_all_checks()

        # Cleanup
        from shared.database.session import close_db
        from shared.database.error_db_session import close_error_db
        from shared.database.redis import close_redis

        await close_db()
        await close_error_db()
        await close_redis()

        sys.exit(0 if success else 1)

    except KeyboardInterrupt:
        print("\n\n⚠️  Verification cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Verification failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
