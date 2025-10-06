"""
Trading Data Service - PostgreSQL Implementation

Provides backward-compatible interface for trading data operations using PostgreSQL.
Replaces GRID.database.database and GRID.infra.database SQLite implementation.
"""

from typing import Optional, Any
import pandas as pd

from GRID.infra.database_pg import get_grid_db
from GRID.repositories.trading_repository_pg import TradingDataRepositoryPG
from shared.logging import get_logger

logger = get_logger(__name__)


# =============================================================================
# Entry Data Operations
# =============================================================================

async def update_entry_data(
    exchange_name: str,
    symbol: str,
    direction: Optional[str] = None,
    entry_time: Optional[str] = None,
    entry_order_id: Optional[str] = None,
    tp1_price: Optional[float] = None,
    tp2_price: Optional[float] = None,
    tp3_price: Optional[float] = None,
    tp1_order_id: Optional[str] = None,
    tp2_order_id: Optional[str] = None,
    tp3_order_id: Optional[str] = None,
    sl_price: Optional[float] = None
) -> None:
    """
    Update or create entry data for a symbol.

    Args:
        exchange_name: Exchange name
        symbol: Trading symbol
        direction: Trade direction ('long' or 'short')
        entry_time: Entry timestamp
        entry_order_id: Entry order ID
        tp1_price: Take profit 1 price
        tp2_price: Take profit 2 price
        tp3_price: Take profit 3 price
        tp1_order_id: Take profit 1 order ID
        tp2_order_id: Take profit 2 order ID
        tp3_order_id: Take profit 3 order ID
        sl_price: Stop loss price
    """
    async with get_grid_db() as session:
        repo = TradingDataRepositoryPG(session)

        entry_data: dict[str, Any] = {}
        if direction is not None:
            entry_data['direction'] = direction
        if entry_time is not None:
            entry_data['entry_time'] = entry_time
        if entry_order_id is not None:
            entry_data['entry_order_id'] = entry_order_id
        if tp1_price is not None:
            entry_data['tp1_price'] = tp1_price
        if tp2_price is not None:
            entry_data['tp2_price'] = tp2_price
        if tp3_price is not None:
            entry_data['tp3_price'] = tp3_price
        if tp1_order_id is not None:
            entry_data['tp1_order_id'] = tp1_order_id
        if tp2_order_id is not None:
            entry_data['tp2_order_id'] = tp2_order_id
        if tp3_order_id is not None:
            entry_data['tp3_order_id'] = tp3_order_id
        if sl_price is not None:
            entry_data['sl_price'] = sl_price

        await repo.update_entry(exchange_name, symbol, **entry_data)
        await session.commit()


# =============================================================================
# Take Profit Data Operations
# =============================================================================

async def update_tp_data(
    exchange_name: str,
    symbol: str,
    **kwargs: Any
) -> None:
    """
    Update or create take profit data for a symbol.

    Args:
        exchange_name: Exchange name
        symbol: Trading symbol
        **kwargs: TP fields (tp1_order_id, tp1_price, tp1_status, tp2_*, tp3_*)
    """
    async with get_grid_db() as session:
        repo = TradingDataRepositoryPG(session)

        tp_data = {}
        for key in ['tp1_order_id', 'tp1_price', 'tp1_status',
                    'tp2_order_id', 'tp2_price', 'tp2_status',
                    'tp3_order_id', 'tp3_price', 'tp3_status']:
            if key in kwargs and kwargs[key] is not None:
                tp_data[key] = kwargs[key]

        await repo.update_take_profit(exchange_name, symbol, **tp_data)
        await session.commit()


# =============================================================================
# Stop Loss Data Operations
# =============================================================================

async def update_sl_data(
    exchange_name: str,
    symbol: str,
    sl_order_id: str,
    sl_price: float,
    sl_status: str
) -> None:
    """
    Update or create stop loss data for a symbol.

    Args:
        exchange_name: Exchange name
        symbol: Trading symbol
        sl_order_id: Stop loss order ID
        sl_price: Stop loss price
        sl_status: Stop loss status
    """
    async with get_grid_db() as session:
        repo = TradingDataRepositoryPG(session)

        await repo.update_stop_loss(
            exchange_name=exchange_name,
            symbol=symbol,
            sl_order_id=sl_order_id,
            sl_price=sl_price,
            sl_status=sl_status
        )
        await session.commit()


# =============================================================================
# Win Rate Data Operations
# =============================================================================

async def save_win_rates_to_db(
    exchange_id: str,
    symbol: str,
    df: pd.DataFrame
) -> None:
    """
    Save win rate statistics to database.

    Args:
        exchange_id: Exchange identifier
        symbol: Trading symbol
        df: DataFrame with win rate statistics
    """
    try:
        # Calculate total_win_rate length
        new_length = len(df['total_win_rate'].dropna())

        # Get timestamps from DataFrame index
        first_timestamp = df.index[0].isoformat()
        last_timestamp = df.index[-1].isoformat()

        async with get_grid_db() as session:
            repo = TradingDataRepositoryPG(session)

            # Check if existing data should be updated
            existing = await repo.get_win_rate(exchange_id, symbol)

            # Only update if new length is >= existing length
            if existing is None or new_length >= (existing.total_win_rate_length or 0):
                win_rate_data = {
                    'long_win_rate': float(df['long_win_rate'].iloc[-1]),
                    'short_win_rate': float(df['short_win_rate'].iloc[-1]),
                    'total_win_rate': float(df['total_win_rate'].iloc[-1]),
                    'long_entry_count': int(df['long_entry_count'].iloc[-1]),
                    'short_entry_count': int(df['short_entry_count'].iloc[-1]),
                    'long_stop_loss_count': int(df['long_stop_loss_count'].iloc[-1]),
                    'long_take_profit_count': int(df['long_take_profit_count'].iloc[-1]),
                    'short_stop_loss_count': int(df['short_stop_loss_count'].iloc[-1]),
                    'short_take_profit_count': int(df['short_take_profit_count'].iloc[-1]),
                    'first_timestamp': first_timestamp,
                    'last_timestamp': last_timestamp,
                    'total_win_rate_length': new_length
                }

                await repo.update_win_rate(exchange_id, symbol, **win_rate_data)
                await session.commit()
                logger.info(f"Saved win rates for {exchange_id}/{symbol}")
            else:
                logger.debug(f"Skipped win rate update for {exchange_id}/{symbol} - new length {new_length} < existing {existing.total_win_rate_length}")

    except Exception as e:
        logger.error(
            f"Error saving win rates for {exchange_id}/{symbol}",
            exc_info=True
        )
        raise


# =============================================================================
# Backward Compatibility
# =============================================================================

async def ensure_database_exists(db_name: str) -> str:
    """
    Backward compatibility function - No-op for PostgreSQL.

    In SQLite, this created database files. In PostgreSQL, tables
    are already created via init_grid_db().

    Args:
        db_name: Database name (ignored in PostgreSQL)

    Returns:
        Empty string (for compatibility)
    """
    logger.debug(f"ensure_database_exists called for {db_name} - no-op in PostgreSQL")
    return ""


async def create_database(db_path: str) -> None:
    """
    Backward compatibility function - No-op for PostgreSQL.

    Args:
        db_path: Database path (ignored in PostgreSQL)
    """
    logger.debug(f"create_database called for {db_path} - no-op in PostgreSQL")
