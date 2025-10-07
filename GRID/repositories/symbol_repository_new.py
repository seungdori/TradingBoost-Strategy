"""
Symbol Repository - Migrated to New Infrastructure

Implements access list operations (blacklist/whitelist) on top of the
PostgreSQL-backed repositories.
"""

from typing import List

from sqlalchemy.ext.asyncio import AsyncSession

from shared.errors import DatabaseException, ValidationException
from shared.validation import sanitize_symbol
from shared.logging import get_logger

from GRID.repositories.symbol_list_repository_pg import SymbolListRepositoryPG

logger = get_logger(__name__)


class SymbolRepository:
    """Repository for managing symbol access lists."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self._repo = SymbolListRepositoryPG(session)

    async def get_blacklist(self, exchange_name: str, user_id: int) -> List[str]:
        """Return the blacklist symbols for the specified user/exchange."""
        try:
            logger.info(
                "Fetching blacklist",
                extra={"exchange": exchange_name, "user_id": user_id}
            )
            symbols = await self._repo.get_blacklist(user_id, exchange_name)
            logger.info(
                "Blacklist fetched",
                extra={
                    "exchange": exchange_name,
                    "user_id": user_id,
                    "count": len(symbols)
                }
            )
            return list(symbols)
        except Exception as exc:  # pragma: no cover - logged below
            logger.error(
                "Failed to fetch blacklist",
                exc_info=True,
                extra={"exchange": exchange_name, "user_id": user_id}
            )
            raise DatabaseException(
                f"Failed to fetch blacklist for user {user_id}",
                details={
                    "exchange": exchange_name,
                    "user_id": user_id,
                    "error": str(exc)
                }
            ) from exc

    async def get_whitelist(self, exchange_name: str, user_id: int) -> List[str]:
        """Return the whitelist symbols for the specified user/exchange."""
        try:
            logger.info(
                "Fetching whitelist",
                extra={"exchange": exchange_name, "user_id": user_id}
            )
            symbols = await self._repo.get_whitelist(user_id, exchange_name)
            logger.info(
                "Whitelist fetched",
                extra={
                    "exchange": exchange_name,
                    "user_id": user_id,
                    "count": len(symbols)
                }
            )
            return list(symbols)
        except Exception as exc:  # pragma: no cover - logged below
            logger.error(
                "Failed to fetch whitelist",
                exc_info=True,
                extra={"exchange": exchange_name, "user_id": user_id}
            )
            raise DatabaseException(
                f"Failed to fetch whitelist for user {user_id}",
                details={
                    "exchange": exchange_name,
                    "user_id": user_id,
                    "error": str(exc)
                }
            ) from exc

    async def add_to_blacklist(
        self,
        exchange_name: str,
        user_id: int,
        symbols: List[str]
    ) -> int:
        """Add the supplied symbols to the blacklist."""
        sanitized_symbols = [sanitize_symbol(symbol) for symbol in symbols]
        inserted = 0

        try:
            for symbol in sanitized_symbols:
                await self._repo.add_to_blacklist(user_id, exchange_name, symbol)
                inserted += 1

            logger.info(
                "Symbols added to blacklist",
                extra={
                    "exchange": exchange_name,
                    "user_id": user_id,
                    "symbols": sanitized_symbols,
                    "count": inserted
                }
            )
            return inserted
        except ValidationException:
            raise
        except Exception as exc:  # pragma: no cover - logged below
            logger.error(
                "Failed to add symbols to blacklist",
                exc_info=True,
                extra={
                    "exchange": exchange_name,
                    "user_id": user_id,
                    "symbols": sanitized_symbols
                }
            )
            raise DatabaseException(
                f"Failed to add symbols to blacklist for user {user_id}",
                details={
                    "exchange": exchange_name,
                    "user_id": user_id,
                    "symbols": sanitized_symbols,
                    "error": str(exc)
                }
            ) from exc

    async def add_to_whitelist(
        self,
        exchange_name: str,
        user_id: int,
        symbols: List[str]
    ) -> int:
        """Add the supplied symbols to the whitelist."""
        sanitized_symbols = [sanitize_symbol(symbol) for symbol in symbols]
        inserted = 0

        try:
            for symbol in sanitized_symbols:
                await self._repo.add_to_whitelist(user_id, exchange_name, symbol)
                inserted += 1

            logger.info(
                "Symbols added to whitelist",
                extra={
                    "exchange": exchange_name,
                    "user_id": user_id,
                    "symbols": sanitized_symbols,
                    "count": inserted
                }
            )
            return inserted
        except ValidationException:
            raise
        except Exception as exc:  # pragma: no cover - logged below
            logger.error(
                "Failed to add symbols to whitelist",
                exc_info=True,
                extra={
                    "exchange": exchange_name,
                    "user_id": user_id,
                    "symbols": sanitized_symbols
                }
            )
            raise DatabaseException(
                f"Failed to add symbols to whitelist for user {user_id}",
                details={
                    "exchange": exchange_name,
                    "user_id": user_id,
                    "symbols": sanitized_symbols,
                    "error": str(exc)
                }
            ) from exc
