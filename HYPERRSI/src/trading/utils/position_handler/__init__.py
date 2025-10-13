"""
Position Handler Package

Modular position lifecycle management for HYPERRSI trading strategy.

This package provides a backward-compatible interface to the refactored position
handler modules while maintaining the exact same public API as the original
monolithic position_handler.py file.

Public API (backward compatible):
    - handle_no_position: Initial position entry logic
    - handle_existing_position: Existing position management (DCA, exits)
    - check_margin_block: Check if user has margin block status

Usage:
    from HYPERRSI.src.trading.utils.position_handler import (
        handle_no_position,
        handle_existing_position
    )
"""

import json
from datetime import datetime
from typing import Any, Dict

from HYPERRSI.src.bot.telegram_message import send_telegram_message
from HYPERRSI.src.trading.models import Position, get_timeframe
from HYPERRSI.src.trading.position_manager import PositionStateManager
from HYPERRSI.src.trading.services.get_current_price import get_current_price
from HYPERRSI.src.trading.trading_service import TradingService
from HYPERRSI.src.trading.utils.position_handler.constants import (
    MAIN_POSITION_DIRECTION_KEY,
    POSITION_KEY,
)
from HYPERRSI.src.trading.utils.position_handler.core import (
    calculate_next_candle_time,
    get_investment_amount,
    get_redis_client,
)

# Import public API functions from modules
from HYPERRSI.src.trading.utils.position_handler.entry import handle_no_position
from HYPERRSI.src.trading.utils.position_handler.exit import handle_trend_reversal_exit
from HYPERRSI.src.trading.utils.position_handler.pyramiding import handle_pyramiding
from HYPERRSI.src.trading.utils.position_handler.validation import check_margin_block
from shared.logging import get_logger

logger = get_logger(__name__)


async def handle_existing_position(
    user_id: str,
    settings: dict,
    trading_service: TradingService,
    symbol: str,
    timeframe: str,
    current_position: Position,
    current_rsi: float,
    rsi_signals: dict,
    current_state: int,
    side: str,
) -> Position:
    """
    Handle existing position management including DCA/pyramiding and trend-based exits.

    This is a backward-compatible wrapper that orchestrates:
    1. Position synchronization and validation
    2. DCA/pyramiding logic via handle_pyramiding()
    3. Trend-based position closure via handle_trend_reversal_exit()

    Args:
        user_id: User identifier
        settings: User trading settings dictionary
        trading_service: Trading service instance
        symbol: Trading symbol (e.g., "BTC-USDT-SWAP")
        timeframe: Timeframe string (e.g., "5m", "15m")
        current_position: Current position object
        current_rsi: Current RSI value
        rsi_signals: Dictionary with RSI signal flags
        current_state: Current trend state (-2 to +2)
        side: Position side ("long", "short", or "any")

    Returns:
        Updated position object

    Side Effects:
        - May open additional DCA positions
        - May close positions on trend reversals
        - Updates Redis position state
        - Sends Telegram notifications
    """
    redis = await get_redis_client()

    try:
        # ========================================================================
        # Position Synchronization and Validation
        # ========================================================================
        korean_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        position_manager = PositionStateManager(trading_service)
        current_price = await get_current_price(symbol, timeframe)

        # Determine position side if "any"
        if side == "any":
            print("[종목] 종목X )종목t 종목. 종목X )종목D >D $i종목.")
            main_position_direction_key = MAIN_POSITION_DIRECTION_KEY.format(
                user_id=user_id,
                symbol=symbol
            )
            side = await redis.get(main_position_direction_key)
            if side is None or side == "any":
                side = current_position.side
                await redis.set(main_position_direction_key, side)

        size = current_position.size
        entry_price = current_position.entry_price

        # Get or recalculate initial position size
        position_key = POSITION_KEY.format(user_id=user_id, symbol=symbol, side=side)
        initial_position_size = await redis.hget(position_key, "initial_size")

        initial_investment = get_investment_amount(settings, symbol)

        if initial_position_size is None:
            initial_position_size = await redis.get(
                f"user:{user_id}:position:{symbol}:{side}:initial_size"
            )
            if initial_position_size is None:
                try:
                    # Recalculate contract info
                    contract_info = await trading_service.get_contract_info(
                        symbol=symbol,
                        user_id=user_id,
                        size_usdt=initial_investment,
                        leverage=settings['leverage'],
                        current_price=current_price
                    )
                    initial_position_size = contract_info['contracts_amount']

                    # Store in Redis
                    await redis.set(
                        f"user:{user_id}:position:{symbol}:{side}:initial_size",
                        initial_position_size
                    )
                    await redis.hset(
                        f"user:{user_id}:position:{symbol}:{side}",
                        "initial_size",
                        initial_position_size
                    )
                    print(f"[{user_id}] 0 종목 종목 종목  종목 D종목: {initial_position_size}")
                except Exception as e:
                    logger.error(f"0 종목 종목 종목 종목(: {str(e)}")
                    initial_position_size = float(size)
                    print(f"[{user_id}] 0 종목 종목 종목 종목(, 현재 포지션 크기 사용: {initial_position_size}")
                    await redis.set(
                        f"user:{user_id}:position:{symbol}:{side}:initial_size",
                        initial_position_size
                    )
                    await redis.hset(
                        f"user:{user_id}:position:{symbol}:{side}",
                        "initial_size",
                        initial_position_size
                    )

        # Get dual-side settings
        use_dual_side_settings = await redis.hget(
            f"user:{user_id}:dual_side",
            "use_dual_side_entry"
        )
        trend_close_enabled = await redis.hget(
            f"user:{user_id}:dual_side",
            "dual_side_trend_close"
        )

        print(
            f"[{user_id}]종목:{korean_time} 포지션이 이미 존재. "
            f"평단: {entry_price}, 포지션 수량(amount): {size}, 포지션 방향: {side}"
        )

        # Get ATR value
        tf_str = get_timeframe(timeframe)
        key = f"candles_with_indicators:{symbol}:{tf_str}"
        candle = await redis.lindex(key, -1)
        if candle:
            candle = json.loads(candle)
            atr_value = max(candle.get('atr14'), current_price * 0.1 * 0.01)
        else:
            atr_value = current_price * 0.01 * 0.1
            logger.error(f"캔들 정보를 찾을 수 없습니다: {key}")

        # Resynchronize if position data is missing
        if not entry_price or not size:
            exch_pos = await trading_service.get_current_position(user_id, symbol, side)
            if exch_pos is None:
                # Position mismatch - cleanup Redis
                await position_manager.cleanup_position_data(user_id, symbol, side)
                await send_telegram_message(
                    f"[{user_id}]L 종목X 종목 종목|X: Redis 0T",
                    user_id,
                    debug=True
                )
                return current_position
            else:
                entry_price = exch_pos.entry_price
                size = exch_pos.size
                await position_manager.update_position_state(
                    user_id,
                    symbol,
                    entry_price,
                    size,
                    side,
                    operation_type="add_position"
                )
                print("포지션 정보 동기화 완료")

        # ========================================================================
        # DCA/Pyramiding Logic
        # ========================================================================
        await handle_pyramiding(
            user_id=user_id,
            settings=settings,
            trading_service=trading_service,
            symbol=symbol,
            timeframe=timeframe,
            current_position=current_position,
            current_rsi=current_rsi,
            rsi_signals=rsi_signals,
            current_state=current_state,
            side=side,
            current_price=current_price,
            atr_value=atr_value,
            use_dual_side_settings=use_dual_side_settings
        )

        # ========================================================================
        # Trend-Based Exit Logic
        # ========================================================================
        await handle_trend_reversal_exit(
            user_id=user_id,
            settings=settings,
            trading_service=trading_service,
            symbol=symbol,
            current_state=current_state,
            current_position=current_position,
            side=side,
            use_dual_side_settings=use_dual_side_settings,
            trend_close_enabled=trend_close_enabled
        )

        return current_position

    except Exception as e:
        logger.error(f"[{user_id}] handle_existing_position error: {str(e)}", exc_info=True)
        await send_telegram_message(
            f"⚠️ 포지션 처리 중 오류:\n{str(e)}",
            user_id,
            debug=True
        )
        return current_position


# Public API exports
__all__ = [
    'handle_no_position',
    'handle_existing_position',
    'check_margin_block',
    'calculate_next_candle_time',
    'get_redis_client',
]
