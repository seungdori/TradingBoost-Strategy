"""
Trading Service - Migrated to New Infrastructure

Manages trading access lists (blacklist/whitelist) with database operations.

DEPRECATED: File-based functions remain for backward compatibility.
New code should use TradingAccessService from trading_service_new.py
"""

import json
from typing import List
from pathlib import Path

from shared.logging import get_logger
from shared.errors import DatabaseException, ConfigurationException, ValidationException

from GRID.dtos.symbol import AccessListDto
from shared.utils import path_helper
import aiosqlite

logger = get_logger(__name__)


def get_list_from_file(file_name: str) -> List[str]:
    """
    DEPRECATED: Get list from JSON file.

    Use TradingAccessService instead for new code.

    Args:
        file_name: Path to JSON file

    Returns:
        List of symbols from file

    Raises:
        ConfigurationException: File read error
    """
    logger.warning(
        "Using deprecated file-based access list",
        extra={"file_name": file_name, "function": "get_list_from_file"}
    )

    file_path = file_name
    try:
        with open(file_path, 'r') as file:
            symbols = json.load(file)
            logger.debug(
                "File-based list loaded",
                extra={"file_name": file_name, "count": len(symbols)}
            )
            return symbols
    except FileNotFoundError:
        logger.warning(f"File not found: {file_name}")
        return []
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in file {file_name}: {e}")
        raise ConfigurationException(f"Invalid JSON file: {file_name}")
    except Exception as e:
        logger.error(f"Error reading file {file_name}: {e}")
        raise ConfigurationException(f"Failed to read file: {file_name}")


def get_ban_list_from_file(file_name: str):
    return get_list_from_file(file_name)


def get_white_list_from_file(file_name: str):
    return get_list_from_file(file_name)


async def get_black_list(exchange_name: str, user_id: int) -> List[str]:
    """
    DEPRECATED: Get blacklist from SQLite database.

    Use TradingAccessService instead for new code.

    Args:
        exchange_name: Exchange identifier
        user_id: User ID

    Returns:
        List of blacklisted symbols
    """
    logger.warning(
        "Using deprecated SQLite blacklist",
        extra={
            "exchange": exchange_name,
            "user_id": user_id,
            "function": "get_black_list"
        }
    )
    return await get_list_from_db(exchange_name, user_id, 'blacklist')


async def get_white_list(exchange_name: str, user_id: int) -> List[str]:
    """
    DEPRECATED: Get whitelist from SQLite database.

    Use TradingAccessService instead for new code.

    Args:
        exchange_name: Exchange identifier
        user_id: User ID

    Returns:
        List of whitelisted symbols
    """
    logger.warning(
        "Using deprecated SQLite whitelist",
        extra={
            "exchange": exchange_name,
            "user_id": user_id,
            "function": "get_white_list"
        }
    )
    return await get_list_from_db(exchange_name, user_id, 'whitelist')


async def get_list_from_db(
    exchange_name: str,
    user_id: int,
    list_type: str
) -> List[str]:
    """
    DEPRECATED: Get access list from SQLite database.

    Use TradingAccessService instead for new code.

    Args:
        exchange_name: Exchange identifier
        user_id: User ID
        list_type: 'blacklist' or 'whitelist'

    Returns:
        List of symbols

    Raises:
        DatabaseException: Database operation failed
    """
    logger.warning(
        "Using deprecated SQLite database access",
        extra={
            "exchange": exchange_name,
            "user_id": user_id,
            "list_type": list_type,
            "function": "get_list_from_db"
        }
    )

    try:
        db_path = f'{exchange_name}_users.db'
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute(
                f'SELECT symbol FROM {list_type} WHERE user_id = ?',
                (user_id,)
            )
            symbols = await cursor.fetchall()
            await cursor.close()

        result = [symbol[0] for symbol in symbols] if symbols else []

        logger.debug(
            "SQLite list retrieved",
            extra={
                "exchange": exchange_name,
                "user_id": user_id,
                "list_type": list_type,
                "count": len(result)
            }
        )

        return result

    except Exception as e:
        logger.error(
            "Failed to get list from SQLite",
            exc_info=True,
            extra={
                "exchange": exchange_name,
                "user_id": user_id,
                "list_type": list_type
            }
        )
        raise DatabaseException(
            f"Failed to get {list_type} from database",
            details={
                "exchange": exchange_name,
                "user_id": user_id,
                "list_type": list_type,
                "error": str(e)
            }
        )

# def update_file(file_name: str, items: List[str]):
#     file_path = str(path_helper.packaged_binary_dir / file_name)
#     print('[UPDATE FILE PATH]', file_path)
#     try:
#         with open(file_path, 'w') as file:
#             json.dump(items, file)
#     except Exception as e:
#         raise e


# def remove_items_from_file(file_name: str, items_to_remove: List[str]):
#     try:
#         items = get_list_from_file(file_name)
#         # Remove each item in items_to_remove if it exists in items
#         updated_items = [item for item in items if item not in items_to_remove]
#         update_file(file_name, updated_items)
#     except FileNotFoundError:
#         print(f"No such file: {file_name}")


def get_access_list(exchange_name, user_id, type) -> AccessListDto:
    if type == 'blacklist':
        return AccessListDto(type=type, symbols=get_black_list(exchange_name, user_id))
    if type == 'whitelist':
        return AccessListDto(type=type, symbols=get_white_list(exchange_name, user_id))
    else:
        raise ValueError(f"Invalid access type: {type}")

async def get_black_list(exchange_name, user_id):
    db_path = f'{exchange_name}_users.db'
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute('SELECT symbol FROM blacklist WHERE user_id = ?', (user_id,))
        symbols = await cursor.fetchall()
        await cursor.close()

async def get_white_list(exchange_name, user_id):
    db_path = f'{exchange_name}_users.db'
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute('SELECT symbol FROM whitelist WHERE user_id = ?', (user_id,))
        symbols = await cursor.fetchall()
        await cursor.close()


#

def update_file(file_name: str, new_items: List[str], append: bool = False):
    file_path = file_name
    items = get_list_from_file(file_name) if append else []
    # Combine existing items with new_items, ensuring no duplicates
    updated_items = list(set(items + new_items))
    try:
        with open(file_path, 'w') as file:
            json.dump(updated_items, file)
    except Exception as e:
        raise e


def remove_items_from_file(file_name: str, items_to_remove: List[str]):
    items = get_list_from_file(file_name)
    updated_items = [item for item in items if item not in items_to_remove]
    update_file(file_name, updated_items, append=False)


def update_access_list(dto: AccessListDto, append: bool = False):
    file_name = 'ban_list.json' if dto.type == 'blacklist' else 'white_list.json'
    update_file(file_name=file_name, new_items=dto.symbols, append=append)


def add_access_list(dto: AccessListDto):
    update_access_list(dto=dto, append=True)


def delete_access_list(dto: AccessListDto):
    file_name = 'ban_list.json' if dto.type == 'blacklist' else 'white_list.json'
    remove_items_from_file(file_name, dto.symbols)
