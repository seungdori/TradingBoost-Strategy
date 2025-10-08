"""
Position Handler Exit Module

This module handles position exit logic based on trend reversal conditions.
Includes position closing, stats update, and Redis cleanup.
"""

import traceback
from datetime import datetime
from typing import Dict, Any

from HYPERRSI.src.trading.trading_service import TradingService
from HYPERRSI.src.trading.models import Position
from HYPERRSI.src.bot.telegram_message import send_telegram_message
from HYPERRSI.src.trading.stats import update_trading_stats
from HYPERRSI.src.trading.utils.trading_utils import init_user_position_data
from shared.utils import contracts_to_qty
from shared.logging import get_logger
from HYPERRSI.src.core.logger import setup_error_logger

# Import from position_handler package
from HYPERRSI.src.trading.utils.position_handler.core import get_redis_client
from HYPERRSI.src.trading.utils.position_handler.constants import (
    POSITION_KEY,
    DCA_COUNT_KEY,
    DCA_LEVELS_KEY,
    TREND_STATE_STRONG_DOWNTREND,
    TREND_STATE_STRONG_UPTREND
)

logger = get_logger(__name__)
error_logger = setup_error_logger()


async def handle_trend_reversal_exit(
    user_id: str,
    settings: dict,
    trading_service: TradingService,
    symbol: str,
    current_state: int,
    current_position: Position,
    side: str,
    use_dual_side_settings: str,
    trend_close_enabled: str
) -> None:
    """
    Handle position exit based on trend reversal conditions.

    This function checks if the trend has reversed strongly against the current position
    and closes the position if use_trend_close setting is enabled.

    Args:
        user_id: User identifier
        settings: User trading settings dictionary
        trading_service: Trading service instance
        symbol: Trading symbol (e.g., "BTC-USDT-SWAP")
        current_state: Current trend state (-2 to +2)
        current_position: Current position object
        side: Position side ("long" or "short")
        use_dual_side_settings: Whether dual-side trading is enabled
        trend_close_enabled: Whether trend-based closing is enabled

    Returns:
        None

    Side Effects:
        - Closes position via exchange API
        - Updates trading statistics
        - Clears Redis position data
        - Sends Telegram notifications

    Trend Reversal Conditions:
        - Long position: Closes when current_state == -2 (strong downtrend)
        - Short position: Closes when current_state == +2 (strong uptrend)
    """
    redis_client = get_redis_client()

    # Check if trend-based closing is enabled
    should_close_with_trend = settings.get('use_trend_close', True)

    if not should_close_with_trend:
        return

    try:
        # Check if trend has reversed strongly against position
        should_exit = (
            (side == "long" and current_state == TREND_STATE_STRONG_DOWNTREND) or
            (side == "short" and current_state == TREND_STATE_STRONG_UPTREND)
        )

        if not should_exit:
            return

        try:
            # Determine dual side if applicable
            dual_side = None
            if side == "long":
                dual_side = "short"
            else:
                dual_side = "long"

            print("트렌드 역전")
            print("강제청산")

            # Close main position
            await _execute_position_close(
                user_id=user_id,
                symbol=symbol,
                side=side,
                trading_service=trading_service,
                reason="트렌드 역전으로 포지션 청산"
            )

            # Close dual-side position if enabled
            if use_dual_side_settings == "true" and trend_close_enabled == "true":
                await _execute_position_close(
                    user_id=user_id,
                    symbol=symbol,
                    side=dual_side,
                    trading_service=trading_service,
                    reason="트렌드 역전으로 양방향 포지션 청산"
                )

            # Update stats
            await _update_stats_on_close(
                user_id=user_id,
                symbol=symbol,
                side=side,
                current_position=current_position,
                redis_client=redis_client
            )

            # Cleanup Redis data
            await _cleanup_redis_on_close(
                user_id=user_id,
                symbol=symbol,
                side=side,
                redis_client=redis_client
            )

        except Exception as e:
            traceback.print_exc()
            error_logger.error(f"[{user_id}]: 트렌드 역전 처리 실패", exc_info=True)
            await send_telegram_message(
                f"⚠️ 트렌드 역전 처리 실패: {str(e)}",
                user_id,
                debug=True
            )

    except Exception as e:
        error_logger.error(f"[{user_id}]:포지션 처리 실패", exc_info=True)
        await send_telegram_message(
            f"⚠️ 포지션 처리 실패: {str(e)}",
            user_id,
            debug=True
        )


async def _execute_position_close(
    user_id: str,
    symbol: str,
    side: str,
    trading_service: TradingService,
    reason: str
) -> None:
    """
    Execute position close via trading service.

    Args:
        user_id: User identifier
        symbol: Trading symbol
        side: Position side to close
        trading_service: Trading service instance
        reason: Reason for closing (for logging/notification)

    Raises:
        Exception: If position close fails
    """
    await trading_service.close_position(
        user_id=user_id,
        symbol=symbol,
        side=side,
        reason=reason
    )
    logger.info(f"[{user_id}] Position closed: {symbol} {side} - {reason}")


async def _update_stats_on_close(
    user_id: str,
    symbol: str,
    side: str,
    current_position: Position,
    redis_client: Any
) -> None:
    """
    Update trading statistics after position close.

    Args:
        user_id: User identifier
        symbol: Trading symbol
        side: Position side
        current_position: Position object with entry price and size
        redis_client: Redis client instance

    Side Effects:
        - Records trade statistics in database
        - Logs success or failure
    """
    try:
        # Get position info from Redis
        position_key = POSITION_KEY.format(user_id=user_id, symbol=symbol, side=side)
        position_info = await redis_client.hgetall(position_key)

        # Calculate PnL
        size = current_position.size
        entry_price = current_position.entry_price
        current_price = current_position.mark_price or current_position.entry_price

        if side == "long":
            pnl = size * (current_price - float(entry_price))
        else:
            pnl = size * (float(entry_price) - current_price)

        # Convert contracts to quantity
        position_qty = await contracts_to_qty(symbol, int(size))
        if position_qty is None:
            position_qty = 0.0

        # Update trading stats
        await update_trading_stats(
            user_id=user_id,
            symbol=symbol,
            entry_price=float(entry_price),
            exit_price=float(current_price),
            position_size=float(position_qty),
            pnl=float(pnl),
            side=side,
            entry_time=position_info.get("entry_time", str(datetime.now())),
            exit_time=str(datetime.now()),
        )

        logger.info(
            f"[{user_id}] Stats updated: {symbol} {side} - PnL: {pnl:+.2f} USDT"
        )

    except Exception as e:
        error_logger.error(f"[{user_id}]: 포지션 통계 업데이트 실패", exc_info=True)
        await send_telegram_message(
            f"⚠️ 포지션 통계 업데이트 실패: {str(e)}",
            user_id,
            debug=True
        )


async def _cleanup_redis_on_close(
    user_id: str,
    symbol: str,
    side: str,
    redis_client: Any
) -> None:
    """
    Clean up Redis position data after position close.

    Args:
        user_id: User identifier
        symbol: Trading symbol
        side: Position side
        redis_client: Redis client instance

    Side Effects:
        - Deletes position-related Redis keys
        - Reinitializes position data
        - Logs success or failure
    """
    try:
        # Delete all position-related keys
        await redis_client.delete(f"user:{user_id}:position:{symbol}:entry_price")

        # Delete DCA count for both sides
        long_dca_count_key = DCA_COUNT_KEY.format(user_id=user_id, symbol=symbol, side="long")
        short_dca_count_key = DCA_COUNT_KEY.format(user_id=user_id, symbol=symbol, side="short")
        await redis_client.delete(long_dca_count_key)
        await redis_client.delete(short_dca_count_key)

        # Delete DCA levels for both sides
        long_dca_levels_key = DCA_LEVELS_KEY.format(user_id=user_id, symbol=symbol, side="long")
        short_dca_levels_key = DCA_LEVELS_KEY.format(user_id=user_id, symbol=symbol, side="short")
        await redis_client.delete(long_dca_levels_key)
        await redis_client.delete(short_dca_levels_key)

        # Delete position data
        position_key = POSITION_KEY.format(user_id=user_id, symbol=symbol, side=side)
        await redis_client.delete(position_key)

        # Reinitialize position data
        await init_user_position_data(user_id, symbol, side)

        logger.info(f"[{user_id}] Redis cleanup completed for {symbol} {side}")

    except Exception as e:
        error_logger.error(f"[{user_id}]: REDIS 포지션 정리 실패", exc_info=True)
        await send_telegram_message(
            f"⚠️ REDIS 포지션 정리 실패: {str(e)}",
            user_id,
            debug=True
        )
