"""
SQLite to PostgreSQL Migration Script for GRID

Migrates data from SQLite databases to PostgreSQL.
"""

import asyncio
import sys
import json
from pathlib import Path
import aiosqlite

# Add project root to path
project_root = Path(__file__).parent.parent.parent.resolve()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from GRID.infra.database_pg import get_grid_db, init_grid_db
from GRID.models.user import User, TelegramID, Job, Blacklist, Whitelist
from shared.logging import get_logger

logger = get_logger(__name__)

# SQLite database paths (in shared/database directory)
SQLITE_DB_DIR = project_root / "shared" / "database"
SQLITE_DBS = {
    "okx": SQLITE_DB_DIR / "okx_users.db",
    "binance": SQLITE_DB_DIR / "binance_users.db",
    "upbit": SQLITE_DB_DIR / "upbit_users.db",
    "bitget": SQLITE_DB_DIR / "bitget_users.db",
    "okx_spot": SQLITE_DB_DIR / "okx_spot_users.db",
    "binance_spot": SQLITE_DB_DIR / "binance_spot_users.db",
    "bitget_spot": SQLITE_DB_DIR / "bitget_spot_users.db",
    "bybit": SQLITE_DB_DIR / "bybit_users.db",
    "bybit_spot": SQLITE_DB_DIR / "bybit_spot_users.db",
}


async def migrate_users_from_sqlite(exchange_name: str, db_path: Path):
    """
    Migrate users from SQLite to PostgreSQL.

    Args:
        exchange_name: Exchange identifier
        db_path: Path to SQLite database
    """
    if not db_path.exists():
        logger.warning(
            f"SQLite database not found for {exchange_name}, skipping"
        )
        return

    logger.info(f"Migrating users from {exchange_name}...")

    async with aiosqlite.connect(db_path) as sqlite_db:
        # Migrate users
        cursor = await sqlite_db.execute("""
            SELECT user_id, api_key, api_secret, password, initial_capital,
                   direction, numbers_to_entry, leverage, is_running, stop_loss,
                   tasks, running_symbols, grid_num
            FROM users
        """)
        users = await cursor.fetchall()

        async with get_grid_db() as session:
            user_count = 0
            for row in users:
                (
                    user_id, api_key, api_secret, password, initial_capital,
                    direction, numbers_to_entry, leverage, is_running, stop_loss,
                    tasks, running_symbols, grid_num
                ) = row

                # Check if user exists
                existing = await session.get(User, (user_id, exchange_name))
                if existing:
                    logger.info(
                        f"User {user_id} already exists for {exchange_name}, skipping"
                    )
                    continue

                # Create user
                user = User(
                    user_id=user_id,
                    exchange_name=exchange_name,
                    api_key=api_key,
                    api_secret=api_secret,
                    password=password,
                    initial_capital=float(initial_capital) if initial_capital else 10.0,
                    direction=direction or "long",
                    numbers_to_entry=int(numbers_to_entry) if numbers_to_entry else 5,
                    leverage=float(leverage) if leverage else 10.0,
                    is_running=bool(is_running),
                    stop_loss=float(stop_loss) if stop_loss else None,
                    tasks=tasks or "[]",
                    running_symbols=running_symbols or "[]",
                    grid_num=int(grid_num) if grid_num else 20,
                )
                session.add(user)
                user_count += 1

            await session.commit()
            logger.info(f"✅ Migrated {user_count} users from {exchange_name}")

        # Migrate telegram IDs
        cursor = await sqlite_db.execute("""
            SELECT user_id, telegram_id FROM telegram_ids
        """)
        telegram_ids = await cursor.fetchall()

        async with get_grid_db() as session:
            telegram_count = 0
            for user_id, telegram_id in telegram_ids:
                # Check if exists
                existing = await session.get(
                    TelegramID, (user_id, exchange_name)
                )
                if existing:
                    continue

                telegram = TelegramID(
                    user_id=user_id,
                    exchange_name=exchange_name,
                    telegram_id=telegram_id
                )
                session.add(telegram)
                telegram_count += 1

            await session.commit()
            logger.info(
                f"✅ Migrated {telegram_count} Telegram IDs from {exchange_name}"
            )

        # Migrate jobs
        cursor = await sqlite_db.execute("""
            SELECT user_id, job_id, status, start_time FROM jobs
        """)
        jobs = await cursor.fetchall()

        async with get_grid_db() as session:
            job_count = 0
            for user_id, job_id, status, start_time in jobs:
                # Check if exists
                existing = await session.get(Job, (user_id, exchange_name))
                if existing:
                    continue

                job = Job(
                    user_id=user_id,
                    exchange_name=exchange_name,
                    job_id=job_id,
                    status=status,
                    start_time=start_time
                )
                session.add(job)
                job_count += 1

            await session.commit()
            logger.info(f"✅ Migrated {job_count} jobs from {exchange_name}")

        # Migrate blacklist
        cursor = await sqlite_db.execute("""
            SELECT user_id, symbol FROM blacklist
        """)
        blacklist = await cursor.fetchall()

        async with get_grid_db() as session:
            blacklist_count = 0
            for user_id, symbol in blacklist:
                blacklist_entry = Blacklist(
                    user_id=user_id,
                    exchange_name=exchange_name,
                    symbol=symbol
                )
                session.add(blacklist_entry)
                blacklist_count += 1

            await session.commit()
            logger.info(
                f"✅ Migrated {blacklist_count} blacklist entries from {exchange_name}"
            )

        # Migrate whitelist
        cursor = await sqlite_db.execute("""
            SELECT user_id, symbol FROM whitelist
        """)
        whitelist = await cursor.fetchall()

        async with get_grid_db() as session:
            whitelist_count = 0
            for user_id, symbol in whitelist:
                whitelist_entry = Whitelist(
                    user_id=user_id,
                    exchange_name=exchange_name,
                    symbol=symbol
                )
                session.add(whitelist_entry)
                whitelist_count += 1

            await session.commit()
            logger.info(
                f"✅ Migrated {whitelist_count} whitelist entries from {exchange_name}"
            )


async def main():
    """Run migration"""
    try:
        logger.info("Starting SQLite to PostgreSQL migration...")

        # Initialize PostgreSQL tables
        await init_grid_db()

        # Migrate each exchange
        for exchange_name, db_file in SQLITE_DBS.items():
            try:
                await migrate_users_from_sqlite(exchange_name, db_file)
            except Exception as e:
                logger.error(
                    f"Failed to migrate {exchange_name}",
                    exc_info=True
                )
                # Continue with other exchanges

        logger.info("✅ Migration completed successfully")

    except Exception as e:
        logger.error(
            "❌ Migration failed",
            exc_info=True
        )
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
