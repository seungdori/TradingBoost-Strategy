"""
Symbol Repository Module

Async helpers for managing blacklist and whitelist entries using PostgreSQL.

"""

from typing import Iterable, List, Sequence, Union

from shared.database.session import get_db, get_transactional_session
from shared.logging import get_logger

from GRID.repositories.symbol_list_repository_pg import SymbolListRepositoryPG

logger = get_logger(__name__)


def _normalize_user_id(user_id: Union[int, str]) -> int:
    """Cast user identifier to int while preserving legacy support."""
    try:
        return int(user_id)
    except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
        raise ValueError(f"Invalid user_id: {user_id}") from exc


def _normalize_symbols(symbols: Iterable[str]) -> List[str]:
    """Strip whitespace and drop empty symbol entries."""
    return [symbol.strip() for symbol in symbols if symbol and symbol.strip()]


async def get_ban_list_from_db(
    user_id: Union[int, str],
    exchange_name: str
) -> List[str]:
    """Return blacklist symbols for the given user/exchange."""
    normalized_user_id = _normalize_user_id(user_id)

    async with get_db() as session:
        repo = SymbolListRepositoryPG(session)
        symbols = await repo.get_blacklist(normalized_user_id, exchange_name)

    logger.debug(
        "Fetched blacklist",
        extra={
            "user_id": normalized_user_id,
            "exchange": exchange_name,
            "count": len(symbols)
        }
    )
    return list(symbols)


async def get_white_list_from_db(
    user_id: Union[int, str],
    exchange_name: str
) -> List[str]:
    """Return whitelist symbols for the given user/exchange."""
    normalized_user_id = _normalize_user_id(user_id)

    async with get_db() as session:
        repo = SymbolListRepositoryPG(session)
        symbols = await repo.get_whitelist(normalized_user_id, exchange_name)

    logger.debug(
        "Fetched whitelist",
        extra={
            "user_id": normalized_user_id,
            "exchange": exchange_name,
            "count": len(symbols)
        }
    )
    return list(symbols)


async def clear_blacklist(user_id: Union[int, str], exchange_name: str) -> int:
    """Remove all blacklist entries for the given user/exchange."""
    normalized_user_id = _normalize_user_id(user_id)

    async with get_transactional_session() as session:
        repo = SymbolListRepositoryPG(session)
        removed = await repo.clear_blacklist(normalized_user_id, exchange_name)

    logger.info(
        "Cleared blacklist",
        extra={
            "user_id": normalized_user_id,
            "exchange": exchange_name,
            "removed": removed
        }
    )
    return removed


async def clear_whitelist(user_id: Union[int, str], exchange_name: str) -> int:
    """Remove all whitelist entries for the given user/exchange."""
    normalized_user_id = _normalize_user_id(user_id)

    async with get_transactional_session() as session:
        repo = SymbolListRepositoryPG(session)
        removed = await repo.clear_whitelist(normalized_user_id, exchange_name)

    logger.info(
        "Cleared whitelist",
        extra={
            "user_id": normalized_user_id,
            "exchange": exchange_name,
            "removed": removed
        }
    )
    return removed


async def add_symbols(
    user_id: Union[int, str],
    exchange_name: str,
    symbols: Sequence[str],
    setting_type: str
) -> int:
    """Add symbols to blacklist or whitelist and return the number inserted."""
    normalized_user_id = _normalize_user_id(user_id)
    normalized_symbols = _normalize_symbols(symbols)
    if not normalized_symbols:
        logger.debug(
            "No symbols provided for insertion",
            extra={
                "user_id": normalized_user_id,
                "exchange": exchange_name,
                "type": setting_type
            }
        )
        return 0

    async with get_transactional_session() as session:
        repo = SymbolListRepositoryPG(session)

        inserted = 0
        if setting_type == "blacklist":
            for symbol in normalized_symbols:
                await repo.add_to_blacklist(normalized_user_id, exchange_name, symbol)
                inserted += 1
        elif setting_type == "whitelist":
            for symbol in normalized_symbols:
                await repo.add_to_whitelist(normalized_user_id, exchange_name, symbol)
                inserted += 1
        else:  # pragma: no cover - protected by callers
            raise ValueError(f"Invalid setting_type: {setting_type}")

    logger.info(
        "Inserted symbols into access list",
        extra={
            "user_id": normalized_user_id,
            "exchange": exchange_name,
            "type": setting_type,
            "count": inserted
        }
    )
    return inserted


async def remove_symbols(
    user_id: Union[int, str],
    exchange_name: str,
    symbols: Sequence[str],
    setting_type: str
) -> int:
    """Remove the provided symbols from blacklist or whitelist."""
    normalized_user_id = _normalize_user_id(user_id)
    normalized_symbols = _normalize_symbols(symbols)
    if not normalized_symbols:
        return 0

    async with get_transactional_session() as session:
        repo = SymbolListRepositoryPG(session)

        if setting_type == "blacklist":
            removed = await repo.remove_from_blacklist_bulk(
                normalized_user_id,
                exchange_name,
                normalized_symbols,
            )
        elif setting_type == "whitelist":
            removed = await repo.remove_from_whitelist_bulk(
                normalized_user_id,
                exchange_name,
                normalized_symbols,
            )
        else:  # pragma: no cover - protected by callers
            raise ValueError(f"Invalid setting_type: {setting_type}")

    logger.info(
        "Removed symbols from access list",
        extra={
            "user_id": normalized_user_id,
            "exchange": exchange_name,
            "type": setting_type,
            "count": removed
        }
    )
    return removed
