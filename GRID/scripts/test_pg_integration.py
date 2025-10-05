"""
PostgreSQL Integration Test for GRID Services

Tests the new PostgreSQL service layer integration with existing GRID code.
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent.resolve()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from GRID.services import user_service_pg
from GRID.infra.database_pg import init_grid_db
from shared.logging import get_logger

logger = get_logger(__name__)


async def test_user_operations():
    """Test user CRUD operations through service layer"""
    logger.info("Testing user operations...")

    # Create user
    user = await user_service_pg.insert_user(
        user_id=1001,
        exchange_name="okx",
        api_key="test_key_001",
        api_secret="test_secret_001",
        password="test_pass"
    )
    logger.info(f"✅ Created user: {user['user_id']}")

    # Get user keys
    user_keys = await user_service_pg.get_user_keys("okx")
    assert 1001 in user_keys, "User 1001 should be in user_keys"
    logger.info(f"✅ Retrieved user keys: {len(user_keys)} users found")

    # Update running status
    await user_service_pg.update_user_running_status("okx", 1001, True)
    logger.info(f"✅ Updated running status to True")

    # Get running users
    running_ids = await user_service_pg.get_running_user_ids("okx")
    assert 1001 in running_ids, "User 1001 should be running"
    logger.info(f"✅ Found {len(running_ids)} running users")


async def test_job_operations():
    """Test job operations through service layer"""
    logger.info("Testing job operations...")

    # Save job
    await user_service_pg.save_job_id("okx", 1001, "celery-task-abc123")
    logger.info(f"✅ Saved job ID")

    # Get job status
    status = await user_service_pg.get_job_status("okx", 1001)
    assert status[0] == "running", "Job status should be running"
    assert status[1] == "celery-task-abc123", "Job ID should match"
    logger.info(f"✅ Retrieved job status: {status[0]}, ID: {status[1]}")

    # Update job status
    await user_service_pg.update_job_status("okx", 1001, "stopped")
    status = await user_service_pg.get_job_status("okx", 1001)
    assert status[0] == "stopped", "Job status should be stopped"
    logger.info(f"✅ Updated job status to: {status[0]}")


async def test_telegram_operations():
    """Test Telegram ID operations"""
    logger.info("Testing Telegram operations...")

    # Update Telegram ID
    await user_service_pg.update_telegram_id("okx", 1001, "123456789")
    logger.info(f"✅ Set Telegram ID")

    # Get Telegram ID
    telegram_id = await user_service_pg.get_telegram_id("okx", 1001)
    assert telegram_id == "123456789", "Telegram ID should match"
    logger.info(f"✅ Retrieved Telegram ID: {telegram_id}")


async def test_symbol_operations():
    """Test running symbols operations"""
    logger.info("Testing symbol operations...")

    # Add running symbols
    await user_service_pg.add_running_symbol(1001, ["BTC-USDT-SWAP", "ETH-USDT-SWAP"], "okx")
    logger.info(f"✅ Added running symbols")

    # Get running symbols
    symbols = await user_service_pg.get_running_symbols(1001, "okx")
    assert "BTC-USDT-SWAP" in symbols, "BTC should be in running symbols"
    assert "ETH-USDT-SWAP" in symbols, "ETH should be in running symbols"
    logger.info(f"✅ Retrieved running symbols: {symbols}")


async def test_backward_compatibility():
    """Test backward compatibility with old interface"""
    logger.info("Testing backward compatibility...")

    # Initialize database (should be no-op but not error)
    await user_service_pg.initialize_database("okx")
    logger.info(f"✅ Initialize database called (backward compatible)")

    # Global user_keys cache should work
    user_keys = await user_service_pg.get_user_keys("okx")
    assert user_service_pg.user_keys == user_keys, "Global cache should match"
    logger.info(f"✅ Global user_keys cache working")


async def main():
    """Run all integration tests"""
    try:
        logger.info("Starting GRID PostgreSQL integration tests...")

        # Initialize database
        await init_grid_db()
        logger.info("✅ Database initialized")

        # Run tests
        await test_user_operations()
        await test_job_operations()
        await test_telegram_operations()
        await test_symbol_operations()
        await test_backward_compatibility()

        logger.info("✅ All integration tests passed successfully!")

    except Exception as e:
        logger.error(
            "❌ Integration tests failed",
            exc_info=True
        )
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
