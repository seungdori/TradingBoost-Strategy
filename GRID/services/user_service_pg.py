"""
User Service - PostgreSQL Implementation

Provides backward-compatible interface for user database operations using PostgreSQL.
Replaces GRID.database.user_database SQLite implementation.
"""

import json
from typing import Dict, List, Optional
from datetime import datetime

from GRID.infra.database_pg import get_grid_db
from GRID.repositories.user_repository_pg import UserRepositoryPG
from GRID.repositories.job_repository_pg import JobRepositoryPG
from GRID.repositories.symbol_list_repository_pg import SymbolListRepositoryPG
from shared.logging import get_logger

logger = get_logger(__name__)


# Backward compatibility: Global user_keys cache (matches old behavior)
user_keys: Dict[int, Dict] = {}


async def initialize_database(exchange_name: str) -> None:
    """
    Initialize database for an exchange.

    This is a no-op for PostgreSQL as tables are already initialized via init_db.py.
    Kept for backward compatibility.

    Args:
        exchange_name: Exchange name (e.g., 'okx', 'binance')
    """
    logger.info(f"Database for {exchange_name} already initialized (PostgreSQL)")


async def insert_user(
    user_id: int,
    exchange_name: str,
    api_key: str,
    api_secret: str,
    password: Optional[str] = None
) -> Dict:
    """
    Insert a new user into the database.

    Args:
        user_id: User identifier
        exchange_name: Exchange name
        api_key: API key for exchange
        api_secret: API secret for exchange
        password: Optional password/passphrase

    Returns:
        Dictionary with user data
    """
    async with get_grid_db() as session:
        user_repo = UserRepositoryPG(session)

        user_data = {
            "user_id": user_id,
            "exchange_name": exchange_name,
            "api_key": api_key,
            "api_secret": api_secret,
            "password": password,
            "initial_capital": 10.0,
            "direction": "long",
            "numbers_to_entry": 5,
            "leverage": 10.0,
            "is_running": False,
            "grid_num": 20
        }

        user = await user_repo.create(user_data)
        await session.commit()

        logger.info(f"User {user_id} inserted for {exchange_name}")

        return {
            "user_id": user.user_id,
            "exchange_name": user.exchange_name,
            "initial_capital": user.initial_capital,
            "direction": user.direction,
            "leverage": user.leverage
        }


async def get_user_keys(exchange_name: str) -> Dict[int, Dict]:
    """
    Get all users for an exchange with their configuration.

    Args:
        exchange_name: Exchange name

    Returns:
        Dictionary mapping user_id to user data
    """
    global user_keys

    async with get_grid_db() as session:
        user_repo = UserRepositoryPG(session)
        users = await user_repo.get_all_by_exchange(exchange_name)

        for user in users:
            # Parse JSON fields
            tasks = json.loads(user.tasks) if user.tasks else []
            running_symbols = set(json.loads(user.running_symbols) if user.running_symbols else [])

            user_data = {
                "user_id": user.user_id,
                "api_key": user.api_key,
                "api_secret": user.api_secret,
                "password": user.password,
                "initial_capital": user.initial_capital,
                "direction": user.direction,
                "numbers_to_entry": user.numbers_to_entry,
                "leverage": user.leverage,
                "is_running": user.is_running,
                "stop_loss": user.stop_loss,
                "tasks": tasks,
                "running_symbols": running_symbols,
                "grid_num": user.grid_num
            }

            user_keys[user.user_id] = user_data

    logger.info(f"Loaded {len(user_keys)} users for {exchange_name}")
    return user_keys


async def save_job_id(exchange_name: str, user_id: int, job_id: str) -> None:
    """
    Save a job ID for a user.

    Args:
        exchange_name: Exchange name
        user_id: User identifier
        job_id: Celery job ID
    """
    async with get_grid_db() as session:
        job_repo = JobRepositoryPG(session)
        await job_repo.save_job(
            user_id=user_id,
            exchange_name=exchange_name,
            job_id=job_id,
            status="running"
        )
        await session.commit()
        logger.info(f"Job ID saved for user {user_id} in {exchange_name}: {job_id}")


async def get_job_id(exchange_name: str, user_id: int) -> Optional[str]:
    """
    Get job ID for a user.

    Args:
        exchange_name: Exchange name
        user_id: User identifier

    Returns:
        Job ID or None
    """
    async with get_grid_db() as session:
        job_repo = JobRepositoryPG(session)
        job_id = await job_repo.get_job_id(user_id, exchange_name)
        return job_id


async def update_job_status(
    exchange_name: str,
    user_id: int,
    status: str,
    job_id: Optional[str] = None
) -> None:
    """
    Update job status for a user.

    Args:
        exchange_name: Exchange name
        user_id: User identifier
        status: Job status ('running', 'stopped', 'error')
        job_id: Optional job ID (if creating new job)
    """
    async with get_grid_db() as session:
        job_repo = JobRepositoryPG(session)
        await job_repo.update_job_status(user_id, exchange_name, status, job_id)
        await session.commit()
        logger.info(f"Job status updated for user {user_id}: {status}")


async def get_job_status(exchange_name: str, user_id: int) -> Optional[tuple]:
    """
    Get job status for a user.

    Args:
        exchange_name: Exchange name
        user_id: User identifier

    Returns:
        Tuple of (status, job_id) or None
    """
    async with get_grid_db() as session:
        job_repo = JobRepositoryPG(session)
        result = await job_repo.get_job_status(user_id, exchange_name)
        return result


async def update_user_running_status(
    exchange_name: str,
    user_id: int,
    is_running: bool
) -> None:
    """
    Update user's running status.

    Args:
        exchange_name: Exchange name
        user_id: User identifier
        is_running: Running status
    """
    async with get_grid_db() as session:
        user_repo = UserRepositoryPG(session)
        await user_repo.update_running_status(user_id, exchange_name, is_running)

        # Update job status accordingly
        job_repo = JobRepositoryPG(session)
        if not is_running:
            # Delete job when stopping
            await job_repo.delete_job(user_id, exchange_name)

        await session.commit()
        logger.info(f"User {user_id} running status updated: {is_running}")


async def update_telegram_id(
    exchange_name: str,
    user_id: int,
    telegram_id: str
) -> None:
    """
    Update Telegram ID for a user.

    Args:
        exchange_name: Exchange name
        user_id: User identifier
        telegram_id: Telegram ID to set
    """
    async with get_grid_db() as session:
        user_repo = UserRepositoryPG(session)
        await user_repo.update_telegram_id(user_id, exchange_name, telegram_id)
        await session.commit()
        logger.info(f"Telegram ID updated for user {user_id}")


async def get_telegram_id(exchange_name: str, user_id: int) -> Optional[str]:
    """
    Get Telegram ID for a user.

    Args:
        exchange_name: Exchange name
        user_id: User identifier

    Returns:
        Telegram ID or None
    """
    async with get_grid_db() as session:
        user_repo = UserRepositoryPG(session)
        telegram_id = await user_repo.get_telegram_id(user_id, exchange_name)
        return telegram_id


async def get_running_user_ids(exchange_name: str) -> List[int]:
    """
    Get all running user IDs for an exchange.

    Args:
        exchange_name: Exchange name

    Returns:
        List of running user IDs
    """
    async with get_grid_db() as session:
        user_repo = UserRepositoryPG(session)
        users = await user_repo.get_running_users(exchange_name)
        return [user.user_id for user in users]


async def get_all_running_user_ids() -> List[int]:
    """
    Get all running user IDs across all exchanges.

    Returns:
        List of running user IDs
    """
    all_running_user_ids = []
    exchanges = ['binance', 'upbit', 'bitget', 'binance_spot', 'bitget_spot',
                 'okx', 'okx_spot', 'bybit', 'bybit_spot']

    for exchange_name in exchanges:
        running_ids = await get_running_user_ids(exchange_name)
        all_running_user_ids.extend(running_ids)

    return all_running_user_ids


async def add_running_symbol(
    user_id: int,
    new_symbols: List[str],
    exchange_name: str
) -> None:
    """
    Add symbols to user's running symbols list.

    Args:
        user_id: User identifier
        new_symbols: Symbol or list of symbols to add
        exchange_name: Exchange name
    """
    async with get_grid_db() as session:
        user_repo = UserRepositoryPG(session)
        await user_repo.add_running_symbol(user_id, exchange_name, new_symbols)
        await session.commit()


async def get_running_symbols(user_id: int, exchange_name: str) -> List[str]:
    """
    Get running symbols for a user.

    Args:
        user_id: User identifier
        exchange_name: Exchange name

    Returns:
        List of running symbols
    """
    async with get_grid_db() as session:
        user_repo = UserRepositoryPG(session)
        user = await user_repo.get_by_id(user_id, exchange_name)

        if user and user.running_symbols:
            return json.loads(user.running_symbols)
        return []


async def update_user_info(
    user_id: int,
    user_keys: Dict,
    exchange_name: str,
    running_status: bool
) -> Dict:
    """
    Update comprehensive user information.

    Args:
        user_id: User identifier
        user_keys: Dictionary with user configuration
        exchange_name: Exchange name
        running_status: Running status

    Returns:
        Updated user_keys dictionary
    """
    async with get_grid_db() as session:
        user_repo = UserRepositoryPG(session)

        updates = {
            "leverage": user_keys[user_id]['leverage'],
            "numbers_to_entry": user_keys[user_id]['numbers_to_entry'],
            "stop_loss": user_keys[user_id]['stop_loss'],
            "initial_capital": user_keys[user_id]['initial_capital'],
            "direction": user_keys[user_id]['direction'],
            "is_running": running_status,
            "tasks": json.dumps(user_keys[user_id]['tasks']),
            "running_symbols": json.dumps(list(user_keys[user_id]['running_symbols']))
        }

        await user_repo.update(user_id, exchange_name, updates)
        await session.commit()

        user_keys[user_id]['is_running'] = running_status
        logger.info(f"User info updated for user {user_id} in {exchange_name}")

        return user_keys


async def save_user(
    user_id: int,
    api_key: Optional[str] = None,
    api_secret: Optional[str] = None,
    password: Optional[str] = None,
    initial_capital: Optional[float] = None,
    direction: Optional[str] = None,
    numbers_to_entry: Optional[int] = None,
    leverage: Optional[float] = None,
    is_running: Optional[bool] = None,
    stop_loss: Optional[float] = None,
    tasks: Optional[List] = None,
    running_symbols: Optional[List] = None,
    grid_num: Optional[int] = None,
    exchange_name: str = 'okx'
) -> None:
    """
    Save or update user with all fields.

    Args:
        user_id: User identifier
        api_key: API key
        api_secret: API secret
        password: Password/passphrase
        initial_capital: Initial capital
        direction: Trade direction
        numbers_to_entry: Number of entries
        leverage: Leverage setting
        is_running: Running status
        stop_loss: Stop loss setting
        tasks: Task list
        running_symbols: Running symbols list
        grid_num: Grid number
        exchange_name: Exchange name
    """
    global user_keys

    async with get_grid_db() as session:
        user_repo = UserRepositoryPG(session)

        # Check if user exists
        user = await user_repo.get_by_id(user_id, exchange_name)

        user_data = {
            "user_id": user_id,
            "exchange_name": exchange_name,
            "api_key": api_key,
            "api_secret": api_secret,
            "password": password,
            "initial_capital": initial_capital if initial_capital is not None else 10.0,
            "direction": direction if direction else "long",
            "numbers_to_entry": numbers_to_entry if numbers_to_entry is not None else 5,
            "leverage": leverage if leverage is not None else 10.0,
            "is_running": is_running if is_running is not None else False,
            "stop_loss": stop_loss,
            "tasks": json.dumps(tasks) if tasks else "[]",
            "running_symbols": json.dumps(running_symbols) if running_symbols else "[]",
            "grid_num": grid_num if grid_num is not None else 20
        }

        if user:
            # Update existing user
            await user_repo.update(user_id, exchange_name, user_data)
        else:
            # Create new user
            await user_repo.create(user_data)

        await session.commit()

        # Update global cache
        if user_id in user_keys:
            user_keys[user_id].update({
                "api_key": api_key,
                "api_secret": api_secret,
                "password": password,
                "initial_capital": initial_capital,
                "direction": direction,
                "numbers_to_entry": numbers_to_entry,
                "leverage": leverage,
                "is_running": bool(is_running),
                "stop_loss": stop_loss,
                "tasks": tasks if tasks else [],
                "running_symbols": set(running_symbols) if running_symbols else set(),
                "grid_num": grid_num
            })
        else:
            user_keys[user_id] = {
                "api_key": api_key,
                "api_secret": api_secret,
                "password": password,
                "initial_capital": initial_capital,
                "direction": direction,
                "numbers_to_entry": numbers_to_entry,
                "leverage": leverage,
                "is_running": bool(is_running),
                "stop_loss": stop_loss,
                "tasks": tasks if tasks else [],
                "running_symbols": set(running_symbols) if running_symbols else set(),
                "grid_num": grid_num
            }


async def get_all_users(exchange: str) -> List[tuple]:
    """
    Get all users for an exchange.

    Args:
        exchange: Exchange name

    Returns:
        List of tuples with (user_id,)
    """
    async with get_grid_db() as session:
        user_repo = UserRepositoryPG(session)
        users = await user_repo.get_all_by_exchange(exchange)
        return [(user.user_id,) for user in users]


async def delete_user(exchange_name: str, user_id: int) -> None:
    """
    Delete a user from the database.

    Args:
        exchange_name: Exchange name
        user_id: User identifier
    """
    async with get_grid_db() as session:
        user_repo = UserRepositoryPG(session)
        await user_repo.delete(user_id, exchange_name)
        await session.commit()
        logger.info(f"User {user_id} deleted from {exchange_name}")

        # Remove from global cache
        global user_keys
        if user_id in user_keys:
            del user_keys[user_id]


# =============================================================================
# Blacklist Operations
# =============================================================================

async def add_to_blacklist(
    exchange_name: str,
    user_id: int,
    symbol: str
) -> None:
    """
    Add a symbol to user's blacklist.

    Args:
        exchange_name: Exchange name
        user_id: User identifier
        symbol: Symbol to blacklist
    """
    async with get_grid_db() as session:
        symbol_repo = SymbolListRepositoryPG(session)
        await symbol_repo.add_to_blacklist(user_id, exchange_name, symbol)
        await session.commit()
        logger.info(f"Added {symbol} to blacklist for user {user_id}")


async def get_blacklist(exchange_name: str, user_id: int) -> List[str]:
    """
    Get user's blacklist symbols.

    Args:
        exchange_name: Exchange name
        user_id: User identifier

    Returns:
        List of blacklisted symbols
    """
    async with get_grid_db() as session:
        symbol_repo = SymbolListRepositoryPG(session)
        symbols = await symbol_repo.get_blacklist(user_id, exchange_name)
        return symbols


async def remove_from_blacklist(
    exchange_name: str,
    user_id: int,
    symbol: str
) -> bool:
    """
    Remove a symbol from user's blacklist.

    Args:
        exchange_name: Exchange name
        user_id: User identifier
        symbol: Symbol to remove

    Returns:
        True if removed, False if not found
    """
    async with get_grid_db() as session:
        symbol_repo = SymbolListRepositoryPG(session)
        result = await symbol_repo.remove_from_blacklist(user_id, exchange_name, symbol)
        await session.commit()
        return result


# =============================================================================
# Whitelist Operations
# =============================================================================

async def add_to_whitelist(
    exchange_name: str,
    user_id: int,
    symbol: str
) -> None:
    """
    Add a symbol to user's whitelist.

    Args:
        exchange_name: Exchange name
        user_id: User identifier
        symbol: Symbol to whitelist
    """
    async with get_grid_db() as session:
        symbol_repo = SymbolListRepositoryPG(session)
        await symbol_repo.add_to_whitelist(user_id, exchange_name, symbol)
        await session.commit()
        logger.info(f"Added {symbol} to whitelist for user {user_id}")


async def get_whitelist(exchange_name: str, user_id: int) -> List[str]:
    """
    Get user's whitelist symbols.

    Args:
        exchange_name: Exchange name
        user_id: User identifier

    Returns:
        List of whitelisted symbols
    """
    async with get_grid_db() as session:
        symbol_repo = SymbolListRepositoryPG(session)
        symbols = await symbol_repo.get_whitelist(user_id, exchange_name)
        return symbols


async def remove_from_whitelist(
    exchange_name: str,
    user_id: int,
    symbol: str
) -> bool:
    """
    Remove a symbol from user's whitelist.

    Args:
        exchange_name: Exchange name
        user_id: User identifier
        symbol: Symbol to remove

    Returns:
        True if removed, False if not found
    """
    async with get_grid_db() as session:
        symbol_repo = SymbolListRepositoryPG(session)
        result = await symbol_repo.remove_from_whitelist(user_id, exchange_name, symbol)
        await session.commit()
        return result
