"""Trading data access helpers using PostgreSQL infrastructure."""

from __future__ import annotations

from typing import Optional

from GRID.repositories.trading_repository_pg import TradingDataRepositoryPG
from shared.database.session import get_db
from shared.dtos.trading import TradingDataDto
from shared.logging import get_logger

logger = get_logger(__name__)


async def fetch_db_prices(exchange_name: str, symbol: str) -> Optional[TradingDataDto]:
    """Fetch trading price data for a symbol from PostgreSQL."""
    try:
        async with get_db() as session:
            repo = TradingDataRepositoryPG(session)
            entry = await repo.get_entry(exchange_name, symbol)

            if entry is None:
                logger.debug(
                    "No entry found for symbol",
                    extra={"exchange": exchange_name, "symbol": symbol}
                )
                return None

            tp1 = entry.tp1_price
            tp2 = entry.tp2_price
            tp3 = entry.tp3_price
            sl = entry.sl_price

            if not all(value and value > 0 for value in [tp1, tp2, tp3, sl]):
                logger.warning(
                    "Entry missing TP/SL values",
                    extra={
                        "exchange": exchange_name,
                        "symbol": symbol,
                        "tp1": tp1,
                        "tp2": tp2,
                        "tp3": tp3,
                        "sl": sl,
                    }
                )
                return None

            return TradingDataDto(
                symbol=entry.symbol,
                long_tp1_price=float(tp1),
                long_tp2_price=float(tp2),
                long_tp3_price=float(tp3),
                long_sl_price=float(sl),
                short_tp1_price=None,
                short_tp2_price=None,
                short_tp3_price=None,
                short_sl_price=None,
            )

    except Exception as exc:  # pragma: no cover - defensive logging
        logger.error(
            "Failed to fetch trading data",
            exc_info=True,
            extra={"exchange": exchange_name, "symbol": symbol}
        )
        raise exc

    return None
