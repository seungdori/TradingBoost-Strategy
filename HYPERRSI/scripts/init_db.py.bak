#!/usr/bin/env python3
"""
HYPERRSI PostgreSQL Database Initialization Script

Initializes all tables for HYPERRSI strategy in PostgreSQL.
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent.resolve()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from HYPERRSI.src.core.database import init_db, engine
from HYPERRSI.src.core.models.database import (  # Import models to register them
    UserModel, ExchangeKeysModel, UserPreferencesModel, UserStateModel, TickSizeModel
)
from shared.logging import get_logger

logger = get_logger(__name__)


async def main():
    """Initialize HYPERRSI database tables"""
    try:
        logger.info("=" * 60)
        logger.info("HYPERRSI PostgreSQL Database Initialization")
        logger.info("=" * 60)

        # Check database URL
        from shared.config import get_settings
        settings = get_settings()
        db_url = settings.db_url

        logger.info(f"Database URL: {db_url.split('@')[0]}@***")  # Hide credentials

        if "sqlite" in db_url:
            logger.warning("⚠️  Using SQLite (development mode)")
        elif "postgresql" in db_url:
            logger.info("✅ Using PostgreSQL (production mode)")
        else:
            logger.error(f"❌ Unknown database type: {db_url}")
            sys.exit(1)

        # Initialize database tables
        logger.info("Initializing database tables...")

        # Force table creation
        async with engine.begin() as conn:
            from HYPERRSI.src.core.database_dir.base import Base
            await conn.run_sync(Base.metadata.create_all)
            logger.info("Tables created successfully")

        logger.info("=" * 60)
        logger.info("✅ Database initialization completed successfully!")
        logger.info("=" * 60)

        # Display created tables
        logger.info("\nCreated tables:")
        logger.info("  1. hyperrsi_users - User information")
        logger.info("  2. hyperrsi_exchange_keys - Exchange API keys")
        logger.info("  3. hyperrsi_user_preferences - Trading preferences")
        logger.info("  4. hyperrsi_user_states - User trading states")
        logger.info("  5. hyperrsi_tick_sizes - Tick size data (reference)")

    except Exception as e:
        logger.error(f"❌ Database initialization failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
