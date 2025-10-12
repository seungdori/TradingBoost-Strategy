"""
Trading Service - Migrated to New Infrastructure

Manages trading access lists (blacklist/whitelist) with database operations.

DEPRECATED: File-based functions remain for backward compatibility.
New code should use TradingAccessService from trading_service_new.py
"""

import json
from pathlib import Path
from typing import List, cast

from GRID.dtos.symbol import AccessListDto
from GRID.repositories.symbol_repository import (
    get_ban_list_from_db,
    get_white_list_from_db,
)
from shared.errors import ConfigurationException, DatabaseException, ValidationException
from shared.logging import get_logger
from shared.utils import path_helper

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
            symbols = cast(List[str], json.load(file))
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


def get_ban_list_from_file(file_name: str) -> List[str]:
    return get_list_from_file(file_name)


def get_white_list_from_file(file_name: str) -> List[str]:
    return get_list_from_file(file_name)


async def get_black_list(exchange_name: str, user_id: int) -> List[str]:
    """
    DEPRECATED: Get blacklist from database.

    Use TradingAccessService instead for new code.

    Args:
        exchange_name: Exchange identifier
        user_id: User ID

    Returns:
        List of blacklisted symbols
    """
    logger.warning(
        "Using deprecated blacklist function",
        extra={
            "exchange": exchange_name,
            "user_id": user_id,
            "function": "get_black_list"
        }
    )
    return await get_list_from_db(exchange_name, user_id, 'blacklist')


async def get_white_list(exchange_name: str, user_id: int) -> List[str]:
    """
    DEPRECATED: Get whitelist from database.

    Use TradingAccessService instead for new code.

    Args:
        exchange_name: Exchange identifier
        user_id: User ID

    Returns:
        List of whitelisted symbols
    """
    logger.warning(
        "Using deprecated whitelist function",
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
    DEPRECATED: Get access list from database.

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
        "Using deprecated database access function",
        extra={
            "exchange": exchange_name,
            "user_id": user_id,
            "list_type": list_type,
            "function": "get_list_from_db"
        }
    )

    try:
        if list_type == 'blacklist':
            result = await get_ban_list_from_db(user_id, exchange_name)
        elif list_type == 'whitelist':
            result = await get_white_list_from_db(user_id, exchange_name)
        else:
            raise ValidationException(
                f"Invalid access list type: {list_type}",
                details={"valid_types": ["blacklist", "whitelist"]}
            )

        logger.debug(
            "Access list retrieved",
            extra={
                "exchange": exchange_name,
                "user_id": user_id,
                "list_type": list_type,
                "count": len(result)
            }
        )

        return list(result) if result else []

    except ValidationException:
        raise
    except Exception as e:
        logger.error(
            "Failed to get list from database",
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


async def get_access_list(exchange_name: str, user_id: int, type: str) -> AccessListDto:
    if type == 'blacklist':
        symbols = await get_black_list(exchange_name, user_id)
        return AccessListDto(exchange_name=exchange_name, user_id=user_id, type=type, symbols=symbols)
    if type == 'whitelist':
        symbols = await get_white_list(exchange_name, user_id)
        return AccessListDto(exchange_name=exchange_name, user_id=user_id, type=type, symbols=symbols)
    else:
        raise ValueError(f"Invalid access type: {type}")


#

def update_file(file_name: str, new_items: List[str], append: bool = False) -> None:
    file_path = file_name
    items = get_list_from_file(file_name) if append else []
    # Combine existing items with new_items, ensuring no duplicates
    updated_items = list(set(items + new_items))
    try:
        with open(file_path, 'w') as file:
            json.dump(updated_items, file)
    except Exception as e:
        raise e


def remove_items_from_file(file_name: str, items_to_remove: List[str]) -> None:
    items = get_list_from_file(file_name)
    updated_items = [item for item in items if item not in items_to_remove]
    update_file(file_name, updated_items, append=False)


def update_access_list(dto: AccessListDto, append: bool = False) -> None:
    file_name = 'ban_list.json' if dto.type == 'blacklist' else 'white_list.json'
    update_file(file_name=file_name, new_items=dto.symbols, append=append)


def add_access_list(dto: AccessListDto) -> None:
    update_access_list(dto=dto, append=True)


def delete_access_list(dto: AccessListDto) -> None:
    file_name = 'ban_list.json' if dto.type == 'blacklist' else 'white_list.json'
    remove_items_from_file(file_name, dto.symbols)
