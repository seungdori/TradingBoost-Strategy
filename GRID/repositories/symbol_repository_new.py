"""
Symbol Repository - Migrated to New Infrastructure

Demonstrates:
- New session management
- Exception handling
- Input validation
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, insert, delete
from typing import List

from shared.errors import DatabaseException, ValidationException
from shared.validation import sanitize_symbol
from shared.logging import get_logger

logger = get_logger(__name__)


class SymbolRepository:
    """
    Repository for managing symbol access lists (blacklist/whitelist).

    Migrated from old aiosqlite approach to new SQLAlchemy async infrastructure.
    """

    def __init__(self, session: AsyncSession):
        """
        Initialize repository with database session.

        Args:
            session: SQLAlchemy async session
        """
        self.session = session

    async def get_blacklist(self, exchange_name: str, user_id: int) -> List[str]:
        """
        Get user's blacklisted symbols.

        Args:
            exchange_name: Exchange identifier
            user_id: User ID

        Returns:
            List of blacklisted symbols

        Example:
            >>> repo = SymbolRepository(session)
            >>> blacklist = await repo.get_blacklist("okx", 123)
            >>> print(blacklist)  # ['BTC/USDT', 'ETH/USDT']
        """
        try:
            logger.info(
                "Fetching blacklist",
                extra={"exchange": exchange_name, "user_id": user_id}
            )

            # TODO: Replace with actual SQLAlchemy model
            # query = select(Blacklist.symbol).where(
            #     Blacklist.exchange_name == exchange_name,
            #     Blacklist.user_id == user_id
            # )
            # result = await self.session.execute(query)
            # symbols = result.scalars().all()

            # Placeholder - replace with actual implementation
            symbols = []

            logger.info(
                "Blacklist fetched",
                extra={
                    "exchange": exchange_name,
                    "user_id": user_id,
                    "count": len(symbols)
                }
            )

            return symbols

        except Exception as e:
            logger.error(
                "Failed to fetch blacklist",
                exc_info=True,
                extra={"exchange": exchange_name, "user_id": user_id}
            )
            raise DatabaseException(
                f"Failed to fetch blacklist for user {user_id}",
                details={"exchange": exchange_name, "user_id": user_id, "error": str(e)}
            )

    async def get_whitelist(self, exchange_name: str, user_id: int) -> List[str]:
        """
        Get user's whitelisted symbols.

        Args:
            exchange_name: Exchange identifier
            user_id: User ID

        Returns:
            List of whitelisted symbols
        """
        try:
            logger.info(
                "Fetching whitelist",
                extra={"exchange": exchange_name, "user_id": user_id}
            )

            # TODO: Replace with actual SQLAlchemy model
            # query = select(Whitelist.symbol).where(
            #     Whitelist.exchange_name == exchange_name,
            #     Whitelist.user_id == user_id
            # )
            # result = await self.session.execute(query)
            # symbols = result.scalars().all()

            symbols = []

            return symbols

        except Exception as e:
            logger.error(
                "Failed to fetch whitelist",
                exc_info=True,
                extra={"exchange": exchange_name, "user_id": user_id}
            )
            raise DatabaseException(
                f"Failed to fetch whitelist for user {user_id}",
                details={"exchange": exchange_name, "user_id": user_id, "error": str(e)}
            )

    async def add_to_blacklist(
        self,
        exchange_name: str,
        user_id: int,
        symbols: List[str]
    ) -> int:
        """
        Add symbols to blacklist.

        Args:
            exchange_name: Exchange identifier
            user_id: User ID
            symbols: List of symbols to add

        Returns:
            Number of symbols added

        Raises:
            ValidationException: Invalid symbol format
            DatabaseException: Database operation failed

        Example:
            >>> repo = SymbolRepository(session)
            >>> count = await repo.add_to_blacklist("okx", 123, ["BTC/USDT", "ETH/USDT"])
        """
        try:
            # Validate symbols
            sanitized_symbols = [sanitize_symbol(s) for s in symbols]

            logger.info(
                "Adding symbols to blacklist",
                extra={
                    "exchange": exchange_name,
                    "user_id": user_id,
                    "symbols": sanitized_symbols
                }
            )

            # TODO: Replace with actual SQLAlchemy model
            # for symbol in sanitized_symbols:
            #     stmt = insert(Blacklist).values(
            #         exchange_name=exchange_name,
            #         user_id=user_id,
            #         symbol=symbol
            #     )
            #     # Handle duplicates with on_conflict_do_nothing() or similar
            #     await self.session.execute(stmt)

            # await self.session.flush()

            added_count = len(sanitized_symbols)

            logger.info(
                "Symbols added to blacklist",
                extra={
                    "exchange": exchange_name,
                    "user_id": user_id,
                    "count": added_count
                }
            )

            return added_count

        except ValidationException:
            raise
        except Exception as e:
            logger.error(
                "Failed to add symbols to blacklist",
                exc_info=True,
                extra={"exchange": exchange_name, "user_id": user_id}
            )
            raise DatabaseException(
                f"Failed to add symbols to blacklist",
                details={"exchange": exchange_name, "user_id": user_id, "error": str(e)}
            )

    async def remove_from_blacklist(
        self,
        exchange_name: str,
        user_id: int,
        symbols: List[str]
    ) -> int:
        """
        Remove symbols from blacklist.

        Args:
            exchange_name: Exchange identifier
            user_id: User ID
            symbols: List of symbols to remove

        Returns:
            Number of symbols removed
        """
        try:
            sanitized_symbols = [sanitize_symbol(s) for s in symbols]

            logger.info(
                "Removing symbols from blacklist",
                extra={
                    "exchange": exchange_name,
                    "user_id": user_id,
                    "symbols": sanitized_symbols
                }
            )

            # TODO: Replace with actual SQLAlchemy model
            # stmt = delete(Blacklist).where(
            #     Blacklist.exchange_name == exchange_name,
            #     Blacklist.user_id == user_id,
            #     Blacklist.symbol.in_(sanitized_symbols)
            # )
            # result = await self.session.execute(stmt)
            # await self.session.flush()

            removed_count = len(sanitized_symbols)

            return removed_count

        except ValidationException:
            raise
        except Exception as e:
            logger.error(
                "Failed to remove symbols from blacklist",
                exc_info=True,
                extra={"exchange": exchange_name, "user_id": user_id}
            )
            raise DatabaseException(
                f"Failed to remove symbols from blacklist",
                details={"exchange": exchange_name, "user_id": user_id, "error": str(e)}
            )


# Migration helper: Backward-compatible wrapper
async def get_black_list(exchange_name: str, user_id: int, session: AsyncSession) -> List[str]:
    """
    Legacy function wrapper for backward compatibility.

    Use SymbolRepository directly in new code.
    """
    repo = SymbolRepository(session)
    return await repo.get_blacklist(exchange_name, user_id)


async def get_white_list(exchange_name: str, user_id: int, session: AsyncSession) -> List[str]:
    """
    Legacy function wrapper for backward compatibility.

    Use SymbolRepository directly in new code.
    """
    repo = SymbolRepository(session)
    return await repo.get_whitelist(exchange_name, user_id)
