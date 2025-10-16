"""
Position Handler Core Utilities

This module provides core utility functions shared across all position handler modules,
including Redis client access and timeframe calculations.
"""

from datetime import datetime, timedelta
from typing import Any, Dict

from HYPERRSI.src.trading.models import get_timeframe
from shared.logging import get_logger

logger = get_logger(__name__)


async def get_redis_client():
    """
    Get redis_client dynamically to avoid import-time errors.

    This function uses dynamic import to prevent circular dependency issues
    and initialization order problems.

    Returns:
        Async Redis client instance from shared database module
    """
    from shared.database.redis import get_redis
    return await get_redis()


async def calculate_next_candle_time(timeframe: str) -> int:
    """
    Calculate the start time of the next candle based on timeframe.

    This function determines when the next candle will start for a given timeframe,
    which is used to set position entry locks that expire at the next candle.

    Args:
        timeframe: Timeframe string (e.g., "1m", "5m", "15m", "1h", "4h", "1d")

    Returns:
        Unix timestamp (seconds) of the next candle start time

    Examples:
        >>> # If current time is 14:37:30
        >>> await calculate_next_candle_time("5m")  # Returns timestamp for 14:40:00
        >>> await calculate_next_candle_time("1h")  # Returns timestamp for 15:00:00
    """
    now = datetime.now()
    tf_str = get_timeframe(timeframe)

    if tf_str == "1m":
        # Next minute start time
        next_minute = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
        return int(next_minute.timestamp())

    elif tf_str == "5m":
        # Calculate remainder when dividing current minute by 5
        current_minute = now.minute
        minutes_to_add = 5 - (current_minute % 5)
        if minutes_to_add == 5:
            minutes_to_add = 0
        next_5min = now.replace(second=0, microsecond=0) + timedelta(minutes=minutes_to_add)
        return int(next_5min.timestamp())

    elif tf_str == "15m":
        # Calculate remainder when dividing current minute by 15
        current_minute = now.minute
        minutes_to_add = 15 - (current_minute % 15)
        if minutes_to_add == 15:
            minutes_to_add = 0
        next_15min = now.replace(second=0, microsecond=0) + timedelta(minutes=minutes_to_add)
        return int(next_15min.timestamp())

    elif tf_str == "1h":
        # Next hour start time
        next_hour = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        return int(next_hour.timestamp())

    elif tf_str == "4h":
        # Calculate remainder when dividing current hour by 4
        current_hour = now.hour
        hours_to_add = 4 - (current_hour % 4)
        if hours_to_add == 4:
            hours_to_add = 0
        next_4hour = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=hours_to_add)
        return int(next_4hour.timestamp())

    elif tf_str == "1d":
        # Next day start time (midnight)
        next_day = (now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1))
        return int(next_day.timestamp())

    # Default: return 1 minute from now
    return int((now + timedelta(minutes=1)).timestamp())


def get_investment_amount(settings: Dict[str, Any], symbol: str) -> float:
    """
    Extract the investment amount for a specific symbol from user settings.

    Different symbols may have different investment amounts configured.
    This function centralizes the logic for retrieving the correct investment.

    Args:
        settings: User settings dictionary containing investment amounts
        symbol: Trading symbol (e.g., "BTC-USDT-SWAP", "ETH-USDT-SWAP")

    Returns:
        Investment amount in USDT

    Examples:
        >>> settings = {'btc_investment': 100, 'investment': 50}
        >>> get_investment_amount(settings, "BTC-USDT-SWAP")
        100.0
        >>> get_investment_amount(settings, "DOGE-USDT-SWAP")
        50.0
    """
    if symbol == "BTC-USDT-SWAP":
        return float(settings.get('btc_investment', settings.get('investment', 0.0)))
    elif symbol == "SOL-USDT-SWAP":
        return float(settings.get('sol_investment', settings.get('investment', 0.0)))
    elif symbol == "ETH-USDT-SWAP":
        return float(settings.get('eth_investment', settings.get('investment', 0.0)))
    else:
        return float(settings.get('investment', 0.0))


async def set_position_lock(
    user_id: str,
    symbol: str,
    side: str,
    timeframe: str,
    expire_seconds: int = None
) -> None:
    """
    Set a position entry lock for a specific timeframe to prevent duplicate entries.

    Position locks are timeframe-specific to allow entries on different timeframes
    while preventing multiple entries within the same timeframe interval.

    Args:
        user_id: User identifier
        symbol: Trading symbol
        side: Position side ("long" or "short")
        timeframe: Timeframe string (e.g., "1m", "5m")
        expire_seconds: Optional custom expiry time. If None, calculated from timeframe.

    Examples:
        >>> # Lock long entry for 5m timeframe until next candle
        >>> await set_position_lock("user123", "BTC-USDT-SWAP", "long", "5m")
    """
    from HYPERRSI.src.trading.utils.position_handler.constants import POSITION_LOCK_KEY

    redis = await get_redis_client()
    tf_str = get_timeframe(timeframe)

    # Calculate expiry time if not provided
    if expire_seconds is None:
        next_candle_time = await calculate_next_candle_time(timeframe)
        current_time = int(datetime.now().timestamp())
        expire_seconds = max(next_candle_time - current_time, 60)  # Minimum 60 seconds

    lock_key = POSITION_LOCK_KEY.format(
        user_id=user_id,
        symbol=symbol,
        side=side,
        timeframe=tf_str
    )

    await redis.setex(lock_key, expire_seconds, "1")
    logger.debug(f"[{user_id}] Position lock set: {lock_key} for {expire_seconds}s")


async def calculate_min_sustain_contract_size(
    user_id: str,
    symbol: str,
    contracts_amount: float,
    settings: Dict[str, Any]
) -> float:
    """
    Calculate and store the minimum sustainable contract size for position management.

    This is used to ensure that after partial take-profits, the remaining position
    is still above the exchange's minimum order size.

    Args:
        user_id: User identifier
        symbol: Trading symbol
        contracts_amount: Initial contract amount
        settings: User settings containing TP ratios

    Returns:
        Minimum sustainable contract size
    """
    from HYPERRSI.src.trading.utils.position_handler.constants import MIN_SUSTAIN_CONTRACT_SIZE_KEY

    redis = await get_redis_client()

    # Calculate based on TP ratio configuration
    tp_sum = (
        float(settings.get('tp1_ratio', 0)) +
        float(settings.get('tp2_ratio', 0)) +
        float(settings.get('tp3_ratio', 0))
    )

    # If TP ratios sum to 1 (100%), use 1% of initial size
    # Otherwise use 0.01% for partial TP scenarios
    if tp_sum in [1, 100]:
        min_size = max(float(contracts_amount) * 0.01, 0.02)
    else:
        min_size = max(float(contracts_amount) * 0.0001, 0.02)

    # Store in Redis for later reference
    min_size_key = MIN_SUSTAIN_CONTRACT_SIZE_KEY.format(
        user_id=user_id,
        symbol=symbol
    )
    await redis.set(min_size_key, min_size)

    return min_size


async def get_atr_value(symbol: str, timeframe: str) -> float:
    """
    Get the ATR (Average True Range) value for a symbol from Redis candle data.

    Args:
        symbol: Trading symbol
        timeframe: Timeframe string

    Returns:
        ATR value, or 0.0 if not found
    """
    import json

    from HYPERRSI.src.trading.utils.position_handler.constants import CANDLES_WITH_INDICATORS_KEY

    redis = await get_redis_client()
    tf_str = get_timeframe(timeframe)

    key = CANDLES_WITH_INDICATORS_KEY.format(symbol=symbol, timeframe=tf_str)

    try:
        candle = await redis.lindex(key, -1)
        if candle:
            candle_data = json.loads(candle)
            return float(candle_data.get('atr14', 0.0))
        else:
            logger.warning(f"Candle data not found for key: {key}")
            return 0.0
    except Exception as e:
        logger.error(f"Failed to fetch ATR data from Redis: {str(e)}")
        return 0.0
