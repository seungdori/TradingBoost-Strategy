#!/usr/bin/env python3
"""
HYPERRSI PostgreSQL Migration Test

Tests database operations with PostgreSQL backend.
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent.resolve()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from HYPERRSI.src.core.database import get_async_session, engine
from HYPERRSI.src.core.models.database import (
    UserModel, ExchangeKeysModel, UserPreferencesModel, UserStateModel
)
from sqlalchemy import select, delete
from shared.logging import get_logger

logger = get_logger(__name__)


async def test_user_operations():
    """Test user CRUD operations"""
    test_user_id = "test_user_123"

    async with get_async_session() as session:
        # Clean up any existing test data
        await session.execute(delete(UserModel).where(UserModel.id == test_user_id))
        await session.commit()

        # Create test user
        user = UserModel(
            id=test_user_id,
            telegram_id=123456789,
            username="test_user",
            is_admin=False
        )
        session.add(user)
        await session.commit()
        logger.info(f"✅ Created test user: {test_user_id}")

        # Read user
        result = await session.execute(
            select(UserModel).where(UserModel.id == test_user_id)
        )
        fetched_user = result.scalar_one_or_none()
        assert fetched_user is not None, "User should exist"
        assert fetched_user.telegram_id == 123456789
        logger.info(f"✅ Read test user: {fetched_user.username}")

        # Update user
        fetched_user.is_admin = True
        await session.commit()
        logger.info("✅ Updated test user")

        # Verify update
        result = await session.execute(
            select(UserModel).where(UserModel.id == test_user_id)
        )
        updated_user = result.scalar_one_or_none()
        assert updated_user.is_admin is True
        logger.info("✅ Verified update")

        # Delete test user
        await session.execute(delete(UserModel).where(UserModel.id == test_user_id))
        await session.commit()
        logger.info("✅ Deleted test user")


async def test_exchange_keys_operations():
    """Test exchange keys operations"""
    test_user_id = "test_user_keys"

    async with get_async_session() as session:
        # Clean up
        await session.execute(delete(UserModel).where(UserModel.id == test_user_id))
        await session.commit()

        # Create user
        user = UserModel(
            id=test_user_id,
            telegram_id=987654321,
            username="keys_test"
        )
        session.add(user)
        await session.commit()

        # Create exchange keys
        keys = ExchangeKeysModel(
            user_id=test_user_id,
            api_key="test_api_key",
            api_secret="test_api_secret",
            passphrase="test_passphrase",
            exchange="okx"
        )
        session.add(keys)
        await session.commit()
        logger.info("✅ Created exchange keys")

        # Read keys
        result = await session.execute(
            select(ExchangeKeysModel).where(ExchangeKeysModel.user_id == test_user_id)
        )
        fetched_keys = result.scalar_one_or_none()
        assert fetched_keys is not None
        assert fetched_keys.api_key == "test_api_key"
        logger.info("✅ Read exchange keys")

        # Clean up
        await session.execute(delete(UserModel).where(UserModel.id == test_user_id))
        await session.commit()
        logger.info("✅ Cleanup completed")


async def test_preferences_and_state():
    """Test user preferences and state operations"""
    test_user_id = "test_user_prefs"

    async with get_async_session() as session:
        # Clean up
        await session.execute(delete(UserModel).where(UserModel.id == test_user_id))
        await session.commit()

        # Create user
        user = UserModel(
            id=test_user_id,
            telegram_id=111222333,
            username="prefs_test"
        )
        session.add(user)
        await session.commit()

        # Create preferences
        prefs = UserPreferencesModel(
            user_id=test_user_id,
            leverage=5,
            risk_per_trade=2.0,
            max_positions=3,
            allowed_symbols=["BTC-USDT", "ETH-USDT", "SOL-USDT"],
            auto_trading=True
        )
        session.add(prefs)

        # Create state
        state = UserStateModel(
            user_id=test_user_id,
            is_active=True,
            pnl_today=150.50,
            total_trades=10,
            entry_trade=5
        )
        session.add(state)
        await session.commit()
        logger.info("✅ Created preferences and state")

        # Read preferences
        result = await session.execute(
            select(UserPreferencesModel).where(
                UserPreferencesModel.user_id == test_user_id
            )
        )
        fetched_prefs = result.scalar_one_or_none()
        assert fetched_prefs.leverage == 5
        assert fetched_prefs.auto_trading is True
        logger.info("✅ Read preferences")

        # Read state
        result = await session.execute(
            select(UserStateModel).where(UserStateModel.user_id == test_user_id)
        )
        fetched_state = result.scalar_one_or_none()
        assert fetched_state.pnl_today == 150.50
        assert fetched_state.total_trades == 10
        logger.info("✅ Read state")

        # Clean up
        await session.execute(delete(UserModel).where(UserModel.id == test_user_id))
        await session.commit()
        logger.info("✅ Cleanup completed")


async def main():
    """Run all tests"""
    try:
        logger.info("=" * 60)
        logger.info("HYPERRSI PostgreSQL Migration Test")
        logger.info("=" * 60)

        # Check database type
        from shared.config import get_settings
        settings = get_settings()
        db_url = settings.db_url

        logger.info(f"Database URL: {db_url.split('@')[0]}@***")

        if "postgresql" not in db_url:
            logger.warning("⚠️  Not using PostgreSQL!")
        else:
            logger.info("✅ Using PostgreSQL")

        # Run tests
        logger.info("\n1. Testing User Operations...")
        await test_user_operations()

        logger.info("\n2. Testing Exchange Keys Operations...")
        await test_exchange_keys_operations()

        logger.info("\n3. Testing Preferences and State Operations...")
        await test_preferences_and_state()

        logger.info("\n" + "=" * 60)
        logger.info("✅ All tests passed!")
        logger.info("=" * 60)

    except Exception as e:
        logger.error(f"❌ Test failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
