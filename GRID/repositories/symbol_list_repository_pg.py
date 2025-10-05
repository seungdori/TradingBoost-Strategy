"""
Symbol List Repository for PostgreSQL

Handles blacklist and whitelist operations.
"""

from typing import List
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from GRID.models.user import Blacklist, Whitelist
from shared.logging import get_logger

logger = get_logger(__name__)


class SymbolListRepositoryPG:
    """Repository for Blacklist and Whitelist operations"""

    def __init__(self, session: AsyncSession):
        self.session = session

    # Blacklist operations
    async def get_blacklist(
        self, user_id: int, exchange_name: str
    ) -> List[str]:
        """
        Get user's blacklist symbols.

        Args:
            user_id: User identifier
            exchange_name: Exchange name

        Returns:
            List of blacklisted symbols
        """
        stmt = select(Blacklist.symbol).where(
            Blacklist.user_id == user_id,
            Blacklist.exchange_name == exchange_name
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def add_to_blacklist(
        self, user_id: int, exchange_name: str, symbol: str
    ) -> Blacklist:
        """
        Add symbol to blacklist.

        Args:
            user_id: User identifier
            exchange_name: Exchange name
            symbol: Symbol to blacklist

        Returns:
            Blacklist object
        """
        # Check if already exists
        stmt = select(Blacklist).where(
            Blacklist.user_id == user_id,
            Blacklist.exchange_name == exchange_name,
            Blacklist.symbol == symbol
        )
        result = await self.session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            return existing

        # Create new blacklist entry
        blacklist = Blacklist(
            user_id=user_id,
            exchange_name=exchange_name,
            symbol=symbol
        )
        self.session.add(blacklist)
        await self.session.flush()
        logger.info(
            f"Added {symbol} to blacklist for user {user_id}"
        )
        return blacklist

    async def remove_from_blacklist(
        self, user_id: int, exchange_name: str, symbol: str
    ) -> bool:
        """
        Remove symbol from blacklist.

        Args:
            user_id: User identifier
            exchange_name: Exchange name
            symbol: Symbol to remove

        Returns:
            True if removed, False if not found
        """
        stmt = delete(Blacklist).where(
            Blacklist.user_id == user_id,
            Blacklist.exchange_name == exchange_name,
            Blacklist.symbol == symbol
        )
        result = await self.session.execute(stmt)

        if result.rowcount > 0:
            logger.info(
                f"Removed {symbol} from blacklist for user {user_id}"
            )
            return True
        return False

    # Whitelist operations
    async def get_whitelist(
        self, user_id: int, exchange_name: str
    ) -> List[str]:
        """
        Get user's whitelist symbols.

        Args:
            user_id: User identifier
            exchange_name: Exchange name

        Returns:
            List of whitelisted symbols
        """
        stmt = select(Whitelist.symbol).where(
            Whitelist.user_id == user_id,
            Whitelist.exchange_name == exchange_name
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def add_to_whitelist(
        self, user_id: int, exchange_name: str, symbol: str
    ) -> Whitelist:
        """
        Add symbol to whitelist.

        Args:
            user_id: User identifier
            exchange_name: Exchange name
            symbol: Symbol to whitelist

        Returns:
            Whitelist object
        """
        # Check if already exists
        stmt = select(Whitelist).where(
            Whitelist.user_id == user_id,
            Whitelist.exchange_name == exchange_name,
            Whitelist.symbol == symbol
        )
        result = await self.session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            return existing

        # Create new whitelist entry
        whitelist = Whitelist(
            user_id=user_id,
            exchange_name=exchange_name,
            symbol=symbol
        )
        self.session.add(whitelist)
        await self.session.flush()
        logger.info(
            f"Added {symbol} to whitelist for user {user_id}"
        )
        return whitelist

    async def remove_from_whitelist(
        self, user_id: int, exchange_name: str, symbol: str
    ) -> bool:
        """
        Remove symbol from whitelist.

        Args:
            user_id: User identifier
            exchange_name: Exchange name
            symbol: Symbol to remove

        Returns:
            True if removed, False if not found
        """
        stmt = delete(Whitelist).where(
            Whitelist.user_id == user_id,
            Whitelist.exchange_name == exchange_name,
            Whitelist.symbol == symbol
        )
        result = await self.session.execute(stmt)

        if result.rowcount > 0:
            logger.info(
                f"Removed {symbol} from whitelist for user {user_id}"
            )
            return True
        return False
