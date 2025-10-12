# type: ignore
"""
GRID Database Integration Test

"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent.resolve()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from GRID.infra.database_pg import get_grid_db
from GRID.repositories.job_repository_pg import JobRepositoryPG
from GRID.repositories.symbol_list_repository_pg import SymbolListRepositoryPG
from GRID.repositories.user_repository_pg import UserRepositoryPG
from shared.logging import get_logger

logger = get_logger(__name__)


async def test_user_operations():
    """Test user CRUD operations"""
    logger.info("Testing user operations...")

    async with get_grid_db() as session:
        user_repo = UserRepositoryPG(session)

        # Create user
        user = await user_repo.create({
            "user_id": 1,
            "exchange_name": "okx",
            "api_key": "test_key",
            "api_secret": "test_secret",
            "password": "test_pass",
            "initial_capital": 100.0,
            "direction": "long",
            "leverage": 10.0,
            "grid_num": 20
        })
        logger.info(f"✅ Created user: {user.user_id}")

        # Get user
        user = await user_repo.get_by_id(1, "okx")
        logger.info(f"✅ Retrieved user: {user.user_id}, capital: {user.initial_capital}")

        # Update user
        await user_repo.update_running_status(1, "okx", True)
        user = await user_repo.get_by_id(1, "okx")
        logger.info(f"✅ Updated user running status: {user.is_running}")

        # Add task
        await user_repo.add_task(1, "okx", "BTC-USDT-SWAP")
        user = await user_repo.get_by_id(1, "okx")
        logger.info(f"✅ Added task: {user.tasks}")

        # Add running symbol
        await user_repo.add_running_symbol(1, "okx", ["BTC-USDT-SWAP", "ETH-USDT-SWAP"])
        user = await user_repo.get_by_id(1, "okx")
        logger.info(f"✅ Added running symbols: {user.running_symbols}")

        # Get running users
        running_users = await user_repo.get_running_users("okx")
        logger.info(f"✅ Found {len(running_users)} running users")


async def test_job_operations():
    """Test job CRUD operations"""
    logger.info("Testing job operations...")

    async with get_grid_db() as session:
        job_repo = JobRepositoryPG(session)

        # Save job
        job = await job_repo.save_job(
            user_id=1,
            exchange_name="okx",
            job_id="celery-task-123",
            status="running"
        )
        logger.info(f"✅ Created job: {job.job_id}, status: {job.status}")

        # Get job status
        status, job_id = await job_repo.get_job_status(1, "okx")
        logger.info(f"✅ Retrieved job: {job_id}, status: {status}")

        # Update job status
        await job_repo.update_job_status(1, "okx", "stopped")
        status, job_id = await job_repo.get_job_status(1, "okx")
        logger.info(f"✅ Updated job status: {status}")


async def test_symbol_list_operations():
    """Test blacklist/whitelist operations"""
    logger.info("Testing symbol list operations...")

    async with get_grid_db() as session:
        symbol_repo = SymbolListRepositoryPG(session)

        # Add to blacklist
        await symbol_repo.add_to_blacklist(1, "okx", "DOGE-USDT-SWAP")
        blacklist = await symbol_repo.get_blacklist(1, "okx")
        logger.info(f"✅ Added to blacklist: {blacklist}")

        # Add to whitelist
        await symbol_repo.add_to_whitelist(1, "okx", "BTC-USDT-SWAP")
        await symbol_repo.add_to_whitelist(1, "okx", "ETH-USDT-SWAP")
        whitelist = await symbol_repo.get_whitelist(1, "okx")
        logger.info(f"✅ Added to whitelist: {whitelist}")

        # Remove from blacklist
        await symbol_repo.remove_from_blacklist(1, "okx", "DOGE-USDT-SWAP")
        blacklist = await symbol_repo.get_blacklist(1, "okx")
        logger.info(f"✅ Removed from blacklist, remaining: {blacklist}")


async def test_telegram_operations():
    """Test Telegram ID operations"""
    logger.info("Testing Telegram operations...")

    async with get_grid_db() as session:
        user_repo = UserRepositoryPG(session)

        # Update Telegram ID
        await user_repo.update_telegram_id(1, "okx", "123456789")
        telegram_id = await user_repo.get_telegram_id(1, "okx")
        logger.info(f"✅ Set Telegram ID: {telegram_id}")


async def main():
    """Run all tests"""
    try:
        logger.info("Starting GRID database integration tests...")

        await test_user_operations()
        await test_job_operations()
        await test_symbol_list_operations()
        await test_telegram_operations()

        logger.info("✅ All tests passed successfully!")

    except Exception as e:
        logger.error(
            "❌ Tests failed",
            exc_info=True
        )
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
