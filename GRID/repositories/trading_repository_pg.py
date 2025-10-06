"""
Trading Data Repository for PostgreSQL

Handles Entry, TakeProfit, StopLoss, and WinRate operations.
"""

from typing import Optional, Dict, List
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from GRID.models.trading import Entry, TakeProfit, StopLoss, WinRate
from shared.logging import get_logger

logger = get_logger(__name__)


class TradingDataRepositoryPG:
    """Repository for all trading data operations"""

    def __init__(self, session: AsyncSession):
        self.session = session

    # =============================================================================
    # Entry Operations
    # =============================================================================

    async def get_entry(
        self, exchange_name: str, symbol: str
    ) -> Optional[Entry]:
        """Get entry data for a symbol"""
        stmt = select(Entry).where(
            Entry.exchange_name == exchange_name,
            Entry.symbol == symbol
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_entry(
        self,
        exchange_name: str,
        symbol: str,
        **kwargs
    ) -> Entry:
        """
        Update or create entry data.

        Args:
            exchange_name: Exchange name
            symbol: Trading symbol
            **kwargs: Entry fields to update
        """
        entry = await self.get_entry(exchange_name, symbol)

        if entry:
            # Update existing
            for key, value in kwargs.items():
                if value is not None and hasattr(entry, key):
                    setattr(entry, key, value)
        else:
            # Create new
            entry = Entry(
                exchange_name=exchange_name,
                symbol=symbol,
                **kwargs
            )
            self.session.add(entry)

        await self.session.flush()
        logger.info(f"Updated entry for {exchange_name}/{symbol}")
        return entry

    async def delete_entry(self, exchange_name: str, symbol: str) -> bool:
        """Delete entry data"""
        stmt = delete(Entry).where(
            Entry.exchange_name == exchange_name,
            Entry.symbol == symbol
        )
        result = await self.session.execute(stmt)
        return result.rowcount > 0

    # =============================================================================
    # Take Profit Operations
    # =============================================================================

    async def get_take_profit(
        self, exchange_name: str, symbol: str
    ) -> Optional[TakeProfit]:
        """Get take profit data for a symbol"""
        stmt = select(TakeProfit).where(
            TakeProfit.exchange_name == exchange_name,
            TakeProfit.symbol == symbol
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_take_profit(
        self,
        exchange_name: str,
        symbol: str,
        **kwargs
    ) -> TakeProfit:
        """
        Update or create take profit data.

        Args:
            exchange_name: Exchange name
            symbol: Trading symbol
            **kwargs: TakeProfit fields to update
        """
        tp = await self.get_take_profit(exchange_name, symbol)

        if tp:
            # Update existing
            for key, value in kwargs.items():
                if value is not None and hasattr(tp, key):
                    setattr(tp, key, value)
        else:
            # Create new
            tp = TakeProfit(
                exchange_name=exchange_name,
                symbol=symbol,
                **kwargs
            )
            self.session.add(tp)

        await self.session.flush()
        logger.info(f"Updated take profit for {exchange_name}/{symbol}")
        return tp

    async def delete_take_profit(self, exchange_name: str, symbol: str) -> bool:
        """Delete take profit data"""
        stmt = delete(TakeProfit).where(
            TakeProfit.exchange_name == exchange_name,
            TakeProfit.symbol == symbol
        )
        result = await self.session.execute(stmt)
        return result.rowcount > 0

    # =============================================================================
    # Stop Loss Operations
    # =============================================================================

    async def get_stop_loss(
        self, exchange_name: str, symbol: str
    ) -> Optional[StopLoss]:
        """Get stop loss data for a symbol"""
        stmt = select(StopLoss).where(
            StopLoss.exchange_name == exchange_name,
            StopLoss.symbol == symbol
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_stop_loss(
        self,
        exchange_name: str,
        symbol: str,
        **kwargs
    ) -> StopLoss:
        """
        Update or create stop loss data.

        Args:
            exchange_name: Exchange name
            symbol: Trading symbol
            **kwargs: StopLoss fields to update
        """
        sl = await self.get_stop_loss(exchange_name, symbol)

        if sl:
            # Update existing
            for key, value in kwargs.items():
                if value is not None and hasattr(sl, key):
                    setattr(sl, key, value)
        else:
            # Create new
            sl = StopLoss(
                exchange_name=exchange_name,
                symbol=symbol,
                **kwargs
            )
            self.session.add(sl)

        await self.session.flush()
        logger.info(f"Updated stop loss for {exchange_name}/{symbol}")
        return sl

    async def delete_stop_loss(self, exchange_name: str, symbol: str) -> bool:
        """Delete stop loss data"""
        stmt = delete(StopLoss).where(
            StopLoss.exchange_name == exchange_name,
            StopLoss.symbol == symbol
        )
        result = await self.session.execute(stmt)
        return result.rowcount > 0

    # =============================================================================
    # Win Rate Operations
    # =============================================================================

    async def get_win_rate(
        self, exchange_name: str, symbol: str
    ) -> Optional[WinRate]:
        """Get win rate data for a symbol"""
        stmt = select(WinRate).where(
            WinRate.exchange_name == exchange_name,
            WinRate.symbol == symbol
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_win_rate(
        self,
        exchange_name: str,
        symbol: str,
        **kwargs
    ) -> WinRate:
        """
        Update or create win rate data.

        Args:
            exchange_name: Exchange name
            symbol: Trading symbol
            **kwargs: WinRate fields to update
        """
        wr = await self.get_win_rate(exchange_name, symbol)

        if wr:
            # Update existing
            for key, value in kwargs.items():
                if value is not None and hasattr(wr, key):
                    setattr(wr, key, value)
        else:
            # Create new
            wr = WinRate(
                exchange_name=exchange_name,
                symbol=symbol,
                **kwargs
            )
            self.session.add(wr)

        await self.session.flush()
        logger.info(f"Updated win rate for {exchange_name}/{symbol}")
        return wr

    async def delete_win_rate(self, exchange_name: str, symbol: str) -> bool:
        """Delete win rate data"""
        stmt = delete(WinRate).where(
            WinRate.exchange_name == exchange_name,
            WinRate.symbol == symbol
        )
        result = await self.session.execute(stmt)
        return result.rowcount > 0

    async def get_all_win_rates(self, exchange_name: str) -> List[WinRate]:
        """Get all win rates for an exchange"""
        stmt = select(WinRate).where(
            WinRate.exchange_name == exchange_name
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
