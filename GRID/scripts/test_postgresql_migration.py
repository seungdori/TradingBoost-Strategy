"""
PostgreSQL Migration Verification Test

Tests all user_service_pg functions to ensure PostgreSQL migration is working correctly.
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent.resolve()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from GRID.services import user_service_pg as user_database
from shared.logging import get_logger

logger = get_logger(__name__)

# Test data
TEST_USER_ID = 99999
TEST_EXCHANGE = "test_exchange"
TEST_API_KEY = "test_api_key_12345"
TEST_API_SECRET = "test_api_secret_67890"
TEST_PASSWORD = "test_password"
TEST_TELEGRAM_ID = "test_telegram_123"


async def cleanup_test_data():
    """Remove test data if exists"""
    try:
        logger.info("Cleaning up any existing test data...")
        await user_database.delete_user(exchange_name=TEST_EXCHANGE, user_id=TEST_USER_ID)
        logger.info("✅ Cleanup successful")
    except Exception as e:
        # Silently ignore if user doesn't exist
        logger.debug(f"Cleanup note: {e}")


async def test_insert_user():
    """Test: Insert new user"""
    logger.info("Testing: insert_user()")

    await user_database.insert_user(
        user_id=TEST_USER_ID,
        exchange_name=TEST_EXCHANGE,
        api_key=TEST_API_KEY,
        api_secret=TEST_API_SECRET,
        password=TEST_PASSWORD,
    )

    logger.info("✅ insert_user() successful")


async def test_get_user_keys():
    """Test: Get user keys"""
    logger.info("Testing: get_user_keys()")

    users = await user_database.get_user_keys(TEST_EXCHANGE)

    assert TEST_USER_ID in users, f"User {TEST_USER_ID} not found in database"
    assert users[TEST_USER_ID]["api_key"] == TEST_API_KEY
    assert users[TEST_USER_ID]["api_secret"] == TEST_API_SECRET

    logger.info(f"✅ get_user_keys() successful - Found {len(users)} users")


async def test_update_telegram_id():
    """Test: Update Telegram ID"""
    logger.info("Testing: update_telegram_id()")

    await user_database.update_telegram_id(
        exchange_name=TEST_EXCHANGE, user_id=TEST_USER_ID, telegram_id=TEST_TELEGRAM_ID
    )

    logger.info("✅ update_telegram_id() successful")


async def test_get_telegram_id():
    """Test: Get Telegram ID"""
    logger.info("Testing: get_telegram_id()")

    telegram_id = await user_database.get_telegram_id(
        exchange_name=TEST_EXCHANGE, user_id=TEST_USER_ID
    )

    assert telegram_id == TEST_TELEGRAM_ID, f"Expected {TEST_TELEGRAM_ID}, got {telegram_id}"

    logger.info("✅ get_telegram_id() successful")


async def test_update_user_running_status():
    """Test: Update user running status"""
    logger.info("Testing: update_user_running_status()")

    # Set to True
    await user_database.update_user_running_status(
        exchange_name=TEST_EXCHANGE, user_id=TEST_USER_ID, is_running=True
    )

    users = await user_database.get_user_keys(TEST_EXCHANGE)
    assert users[TEST_USER_ID]["is_running"] is True

    # Set to False
    await user_database.update_user_running_status(
        exchange_name=TEST_EXCHANGE, user_id=TEST_USER_ID, is_running=False
    )

    users = await user_database.get_user_keys(TEST_EXCHANGE)
    assert users[TEST_USER_ID]["is_running"] is False

    logger.info("✅ update_user_running_status() successful")


async def test_save_and_get_job_id():
    """Test: Save and get job ID"""
    logger.info("Testing: save_job_id() and get_job_id()")

    test_job_id = "test_job_12345"

    await user_database.save_job_id(
        exchange_name=TEST_EXCHANGE, user_id=TEST_USER_ID, job_id=test_job_id
    )

    retrieved_job_id = await user_database.get_job_id(
        exchange_name=TEST_EXCHANGE, user_id=TEST_USER_ID
    )

    assert retrieved_job_id == test_job_id, f"Expected {test_job_id}, got {retrieved_job_id}"

    logger.info("✅ save_job_id() and get_job_id() successful")


async def test_blacklist_whitelist():
    """Test: Blacklist and whitelist operations"""
    logger.info("Testing: add_to_blacklist(), get_blacklist(), add_to_whitelist(), get_whitelist()")

    test_symbol = "BTC-USDT"

    # Test blacklist
    await user_database.add_to_blacklist(
        exchange_name=TEST_EXCHANGE, user_id=TEST_USER_ID, symbol=test_symbol
    )

    blacklist = await user_database.get_blacklist(exchange_name=TEST_EXCHANGE, user_id=TEST_USER_ID)
    assert test_symbol in blacklist, f"{test_symbol} not found in blacklist"

    # Test whitelist
    await user_database.add_to_whitelist(
        exchange_name=TEST_EXCHANGE, user_id=TEST_USER_ID, symbol=test_symbol
    )

    whitelist = await user_database.get_whitelist(exchange_name=TEST_EXCHANGE, user_id=TEST_USER_ID)
    assert test_symbol in whitelist, f"{test_symbol} not found in whitelist"

    logger.info("✅ Blacklist and whitelist operations successful")


async def test_delete_user():
    """Test: Delete user"""
    logger.info("Testing: delete_user()")

    await user_database.delete_user(exchange_name=TEST_EXCHANGE, user_id=TEST_USER_ID)

    users = await user_database.get_user_keys(TEST_EXCHANGE)
    assert TEST_USER_ID not in users, f"User {TEST_USER_ID} still exists after deletion"

    logger.info("✅ delete_user() successful")


async def main():
    """Run all tests"""
    print("\n" + "=" * 80)
    print("PostgreSQL Migration Verification Test")
    print("=" * 80 + "\n")

    try:
        # Cleanup any existing test data
        await cleanup_test_data()

        # Run tests in order
        await test_insert_user()
        await test_get_user_keys()
        await test_update_telegram_id()
        await test_get_telegram_id()
        await test_update_user_running_status()
        await test_save_and_get_job_id()
        await test_blacklist_whitelist()
        await test_delete_user()

        print("\n" + "=" * 80)
        print("✅ ALL TESTS PASSED - PostgreSQL migration verified successfully!")
        print("=" * 80 + "\n")

    except Exception as e:
        print("\n" + "=" * 80)
        print(f"❌ TEST FAILED: {e}")
        print("=" * 80 + "\n")
        logger.error("Test failed", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
