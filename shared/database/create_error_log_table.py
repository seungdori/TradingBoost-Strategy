"""
Create Error Log Table

Script to create error_logs table in database.
Run this once to initialize the error logging database.
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import text
from shared.database.session import DatabaseConfig
from shared.database.models import Base, ErrorLog
from shared.logging import get_logger

logger = get_logger(__name__)


async def create_error_log_table():
    """Create error_logs table in database"""
    try:
        engine = DatabaseConfig.get_engine()

        logger.info("Creating error_logs table...")

        # Create all tables defined in Base
        async with engine.begin() as conn:
            # Drop table if exists (for development)
            # await conn.execute(text("DROP TABLE IF EXISTS error_logs CASCADE"))

            # Create table
            await conn.run_sync(Base.metadata.create_all)

        logger.info("✅ error_logs table created successfully")

        # Verify table was created
        async with engine.begin() as conn:
            result = await conn.execute(
                text("""
                    SELECT column_name, data_type, is_nullable
                    FROM information_schema.columns
                    WHERE table_name = 'error_logs'
                    ORDER BY ordinal_position
                """)
            )
            columns = result.fetchall()

            if columns:
                logger.info(f"Table structure verified ({len(columns)} columns):")
                for col in columns:
                    logger.info(f"  - {col[0]}: {col[1]} (nullable: {col[2]})")
            else:
                logger.warning("Could not verify table structure (table might not exist)")

        return True

    except Exception as e:
        logger.error(f"❌ Failed to create error_logs table: {e}", exc_info=True)
        return False
    finally:
        await DatabaseConfig.close_engine()


async def test_error_log_insert():
    """Test inserting a sample error log"""
    try:
        from shared.database.session import get_transactional_session
        from shared.database.error_log_service import ErrorLogService
        from datetime import datetime

        logger.info("Testing error log insertion...")

        async with get_transactional_session() as db:
            error_log = await ErrorLogService.create_error_log(
                db=db,
                error_type="TestError",
                error_message="This is a test error message",
                severity="INFO",
                user_id="test_user_123",
                telegram_id=1234567890,
                strategy_type="HYPERRSI",
                module="test_module",
                function="test_function",
                error_details={"test_key": "test_value"},
                metadata={"source": "create_error_log_table.py"}
            )

            logger.info(f"✅ Test error log inserted: ID={error_log.id}")

            # Query it back
            errors = await ErrorLogService.get_error_logs(db, limit=1)
            if errors:
                logger.info(f"✅ Test error log retrieved: {errors[0].to_dict()}")
            else:
                logger.warning("Could not retrieve test error log")

        return True

    except Exception as e:
        logger.error(f"❌ Failed to test error log insertion: {e}", exc_info=True)
        return False


async def main():
    """Main function"""
    print("="*60)
    print("Error Log Table Creation Script")
    print("="*60)

    # Step 1: Create table
    print("\n[1/2] Creating error_logs table...")
    success = await create_error_log_table()

    if not success:
        print("\n❌ Table creation failed. See logs for details.")
        return 1

    # Step 2: Test insertion
    print("\n[2/2] Testing error log insertion...")
    success = await test_error_log_insert()

    if not success:
        print("\n⚠️  Table created but test insertion failed. See logs for details.")
        return 1

    print("\n" + "="*60)
    print("✅ Error logging database setup completed successfully!")
    print("="*60)

    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
