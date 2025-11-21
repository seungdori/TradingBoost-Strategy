"""
Position Handler Entry Module

This module handles initial position entry logic for both long and short positions.
Includes validation, execution, success/failure handling, and dual-side entry management.
"""

import asyncio
import json
import traceback
from datetime import datetime
from typing import Any, Dict, TYPE_CHECKING

# Lazy import to avoid circular dependency
if TYPE_CHECKING:
    from HYPERRSI.src.api.routes.position import OpenPositionRequest, open_position_endpoint

from HYPERRSI.src.api.trading.Calculate_signal import TrendStateCalculator
from HYPERRSI.src.bot.telegram_message import send_telegram_message
from HYPERRSI.src.core.logger import setup_error_logger
from HYPERRSI.src.trading.error_message import map_exchange_error
from HYPERRSI.src.trading.models import Position, get_timeframe
from HYPERRSI.src.trading.position_manager import PositionStateManager
from HYPERRSI.src.trading.services.get_current_price import get_current_price
from HYPERRSI.src.trading.stats import record_trade_entry
from HYPERRSI.src.trading.trading_service import TradingService
from HYPERRSI.src.trading.utils.message_builder import create_position_message
from HYPERRSI.src.trading.utils.position_handler.constants import (
    DCA_COUNT_KEY,
    DCA_LEVELS_KEY,
    DIRECTION_LONG,
    DIRECTION_LONG_SHORT,
    DIRECTION_SHORT,
    DUAL_SIDE_COUNT_KEY,
    ENTRY_FAIL_COUNT_KEY,
    MAIN_POSITION_DIRECTION_KEY,
    MAX_ENTRY_FAILURES,
    POSITION_KEY,
    TP_DATA_KEY,
    TREND_ALERT_EXPIRY_SECONDS,
    TREND_SIGNAL_ALERT_KEY,
)

# Import from position_handler package
from HYPERRSI.src.trading.utils.position_handler.core import (
    calculate_min_sustain_contract_size,
    calculate_next_candle_time,
    get_atr_value,
    get_investment_amount,
    get_redis_client,
    set_position_lock,
)
from HYPERRSI.src.trading.utils.position_handler.validation import (
    check_any_direction_locked,
    check_entry_failure_limit,
    check_margin_block,
    increment_entry_failure,
    reset_entry_failure,
    should_enter_with_trend,
    validate_position_response,
)
from HYPERRSI.src.trading.utils.trading_utils import init_user_position_data
from shared.logging import get_logger

logger = get_logger(__name__)
error_logger = setup_error_logger()


async def handle_no_position(
    user_id: str,
    settings: dict,
    trading_service: TradingService,
    calculator: TrendStateCalculator,
    symbol: str,
    timeframe: str,
    current_rsi: float,
    rsi_signals: dict,
    current_state: int
) -> None:
    """
    Handle initial position entry when no position exists.

    This is the main orchestrator for opening new long or short positions.
    It performs validation, attempts entry, handles success/failure, and manages Redis state.

    Args:
        user_id: User identifier
        settings: User trading settings dictionary
        trading_service: Trading service instance for API calls
        calculator: Trend state calculator instance
        symbol: Trading symbol (e.g., "BTC-USDT-SWAP")
        timeframe: Timeframe string (e.g., "5m", "15m")
        current_rsi: Current RSI value
        rsi_signals: Dictionary with RSI signal flags (is_oversold, is_overbought)
        current_state: Current trend state (-2 to +2)

    Returns:
        None - function handles all state updates and notifications

    Side Effects:
        - Opens position via exchange API
        - Updates Redis position state
        - Sends Telegram notifications
        - Records trade entry in stats
        - Sets position locks and failure counts
    """
    redis = await get_redis_client()

    try:
        print(f"[{user_id}] ✅포지션이 없는 경우")
        position_manager = PositionStateManager(trading_service)
        current_price = await get_current_price(symbol)

        # Get symbol-specific investment amount
        investment = get_investment_amount(settings, symbol)

        # Get contract information from exchange
        contract_info = await trading_service.get_contract_info(
            symbol=symbol,
            user_id=user_id,
            size_usdt=investment,
            leverage=settings['leverage'],
            current_price=current_price
        )

        # Calculate actual contract amount (already considers minimum order size)
        contracts_amount = contract_info['contracts_amount']

        # Calculate and store minimum sustainable contract size
        await calculate_min_sustain_contract_size(
            user_id=user_id,
            symbol=symbol,
            contracts_amount=contracts_amount,
            settings=settings
        )

        # Initialize position data for both sides
        await init_user_position_data(user_id, symbol, "long")
        await init_user_position_data(user_id, symbol, "short")

        timeframe_str = get_timeframe(timeframe)
        print(f"[{user_id}][{timeframe_str}] 포지션 없는 경우의 디버깅 : {current_rsi}, rsi signals : {rsi_signals},current state : {current_state}", flush=True)

        # Check entry failure limit
        exceeded, fail_count = await check_entry_failure_limit(user_id)

        # Clear main position direction if exists
        main_position_direction_key = MAIN_POSITION_DIRECTION_KEY.format(
            user_id=user_id,
            symbol=symbol
        )
        if await redis.exists(main_position_direction_key):
            await redis.delete(main_position_direction_key)

        # Exit if too many failures
        if exceeded:
            return

        # Get ATR value for messaging
        atr_value = await get_atr_value(symbol, timeframe)

        entry_success = False

        # ============================================================================
        # Long Entry Logic
        # ============================================================================
        print(f"[{user_id}] 롱 진입 체크 시작 - direction: {settings['direction']}", flush=True)
        if settings['direction'] in [DIRECTION_LONG_SHORT, DIRECTION_LONG]:
            # Check if position is locked
            is_locked, locked_direction, remaining = await check_any_direction_locked(
                user_id=user_id,
                symbol=symbol,
                timeframe=timeframe
            )
            #print(f"[{user_id}] 잠금 체크 완료 - is_locked: {is_locked}", flush=True)

            if is_locked:
                logger.info(
                    f"[{user_id}] Position is locked for {symbol} with timeframe {timeframe_str}. "
                    f"Remaining time: {remaining}s"
                )
                return

            # Check trend condition for long entry
            should_enter, reason = await should_enter_with_trend(settings, current_state, "long")
            if rsi_signals['is_oversold'] and should_enter:
                print(f"[{user_id}] 롱 진입 시도!", flush=True)
                entry_success = await _execute_long_entry(
                    user_id=user_id,
                    symbol=symbol,
                    timeframe=timeframe,
                    timeframe_str=timeframe_str,
                    contracts_amount=contracts_amount,
                    settings=settings,
                    current_price=current_price,
                    position_manager=position_manager,
                    trading_service=trading_service,
                    atr_value=atr_value,
                    redis_client=redis
                )

                if entry_success:
                    await _handle_entry_success(user_id, redis)
                else:
                    fail_count = await _handle_entry_failure(user_id, "long", fail_count, redis)

            elif rsi_signals['is_oversold'] and not should_enter:
                # Trend condition not met - send alert
                await _send_trend_alert(user_id, symbol, timeframe, "long", redis)
            else:
                print(f"[{user_id}] 롱 진입 조건3 - is_oversold: {rsi_signals['is_oversold']}, should_enter: {should_enter}, reason: {reason}, current_state: {current_state}", flush=True)

        # ============================================================================
        # Short Entry Logic
        # ============================================================================
        print(f"[{user_id}] 숏 진입 체크 시작 - direction: {settings['direction']}", flush=True)
        if settings['direction'] in [DIRECTION_LONG_SHORT, DIRECTION_SHORT]:
            # Check if position is locked
            is_locked, locked_direction, remaining = await check_any_direction_locked(
                user_id=user_id,
                symbol=symbol,
                timeframe=timeframe
            )
            #print(f"[{user_id}] 잠금 체크 완료 - is_locked: {is_locked}", flush=True)

            if is_locked:
                logger.info(
                    f"[{user_id}] Position is locked for {symbol} with timeframe {timeframe_str}. "
                    f"Remaining time: {remaining}s"
                )
                return

            # Check trend condition for short entry
            should_enter, reason = await should_enter_with_trend(settings, current_state, "short")
            #print(f"[{user_id}] 숏 진입 조건2 - is_overbought: {rsi_signals['is_overbought']}, should_enter: {should_enter}, reason: {reason}, current_state: {current_state}", flush=True)

            if rsi_signals['is_overbought'] and should_enter:
                print(f"[{user_id}] 숏 진입 시도!", flush=True)
                entry_success = await _execute_short_entry(
                    user_id=user_id,
                    symbol=symbol,
                    timeframe=timeframe,
                    timeframe_str=timeframe_str,
                    contracts_amount=contracts_amount,
                    settings=settings,
                    current_price=current_price,
                    position_manager=position_manager,
                    trading_service=trading_service,
                    atr_value=atr_value,
                    redis_client=redis
                )

                if entry_success:
                    await _handle_entry_success(user_id, redis)
                else:
                    fail_count = await _handle_entry_failure(user_id, "short", fail_count, redis)

            elif rsi_signals['is_overbought'] and not should_enter:
                # Trend condition not met - send alert
                await _send_trend_alert(user_id, symbol, timeframe, "short", redis)
            else:
                print(f"[{user_id}] 숏 진입 조건3 - is_overbought: {rsi_signals['is_overbought']}, should_enter: {should_enter}, reason: {reason}, current_state: {current_state}", flush=True)

        # Check if trading should be stopped due to failures
        if fail_count >= 3:
            await redis.set(f"user:{user_id}:trading:status", "stopped")
            await send_telegram_message(
                f"⚠️[{user_id}] User의 상태를 Stopped로 강제 변경",
                user_id,
                debug=True
            )
            await send_telegram_message(
                "3회 연속 진입 실패로 트레이딩이 종료되었습니다.",
                user_id,
                debug=True
            )
            entry_fail_count_key = ENTRY_FAIL_COUNT_KEY.format(user_id=user_id)
            await redis.delete(entry_fail_count_key)

    except Exception as e:
        import traceback
        error_msg = map_exchange_error(e)
        error_logger.error(f"[{user_id}]:포지션 진입 실패", exc_info=True)
        print(f"[{user_id}] ❌❌❌ EXCEPTION CAUGHT in handle_no_position: {e}", flush=True)
        print(f"[{user_id}] Exception type: {type(e)}", flush=True)
        print(f"[{user_id}] Traceback:", flush=True)
        traceback.print_exc()
        await send_telegram_message(
            f"⚠️ 포지션 진입 오류:\n{error_msg}\n\nException: {e}",
            user_id,
            debug=True
        )


async def _execute_long_entry(
    user_id: str,
    symbol: str,
    timeframe: str,
    timeframe_str: str,
    contracts_amount: float,
    settings: dict,
    current_price: float,
    position_manager: PositionStateManager,
    trading_service: TradingService,
    atr_value: float,
    redis_client: Any
) -> bool:
    """
    Execute long position entry.

    Args:
        user_id: User identifier
        symbol: Trading symbol
        timeframe: Timeframe string
        timeframe_str: Formatted timeframe string
        contracts_amount: Contract amount to enter
        settings: User settings
        current_price: Current market price
        position_manager: Position manager instance
        trading_service: Trading service instance
        atr_value: ATR value for messaging
        redis_client: Redis client instance

    Returns:
        True if entry successful, False otherwise
    """
    try:
        # Runtime import to avoid circular dependency
        from HYPERRSI.src.api.routes.position import OpenPositionRequest, open_position_endpoint

        request = OpenPositionRequest(
            user_id=user_id,
            symbol=symbol,
            direction="long",
            size=contracts_amount,
            leverage=settings['leverage'],
            take_profit=None,
            stop_loss=None,
            order_concept='',
            is_DCA=False,
            is_hedge=False,
            hedge_tp_price=None,
            hedge_sl_price=None
        )

        # Check if position is locked for this timeframe
        is_locked, locked_direction, remaining = await check_any_direction_locked(
            user_id=user_id,
            symbol=symbol,
            timeframe=timeframe
        )

        if is_locked:
            logger.info(
                f"[{user_id}] Position is locked for {symbol} with timeframe {timeframe_str}. "
                f"Remaining time: {remaining}s"
            )
            return False

        # Open position via API
        position = await open_position_endpoint(request)

        # Validate position response
        await validate_position_response(position, user_id, "long", "entry")

        print(f"﹗사이즈 점검! : position.size: {position.size},contracts_amount: {contracts_amount}")

        # Update Redis keys
        short_dca_key = DCA_LEVELS_KEY.format(user_id=user_id, symbol=symbol, side="short")
        dca_count_key = DCA_COUNT_KEY.format(user_id=user_id, symbol=symbol, side="long")
        dual_side_count_key = DUAL_SIDE_COUNT_KEY.format(user_id=user_id, symbol=symbol)

        await redis_client.set(dca_count_key, "1")
        await redis_client.delete(short_dca_key)
        await redis_client.set(dual_side_count_key, "0")

        long_dca_key = DCA_LEVELS_KEY.format(user_id=user_id, symbol=symbol, side="long")
        await redis_client.delete(long_dca_key)

        # Set initial_size and last_entry_size
        position_key = POSITION_KEY.format(user_id=user_id, symbol=symbol, side="long")
        await redis_client.hset(position_key, "initial_size", contracts_amount)
        await redis_client.hset(position_key, "last_entry_size", contracts_amount)

        # Set position lock until next candle
        await set_position_lock(user_id, symbol, "long", timeframe)

        # Update position state
        try:
            await position_manager.update_position_state(
                user_id=user_id,
                symbol=symbol,
                entry_price=position.entry_price,
                contracts_amount_delta=contracts_amount,
                side="long",
                operation_type="new_position"
            )
        except Exception as e:
            logger.error(f"포지션 정보 업데이트 실패: {str(e)}")

        # Send success message
        message = await create_position_message(
            user_id=user_id,
            symbol=symbol,
            position_type="long",
            position=position,
            settings=settings,
            tp_levels=position.tp_prices if position.tp_prices else None,
            stop_loss=position.sl_price,
            contracts_amount=contracts_amount,
            trading_service=trading_service,
            atr_value=atr_value
        )
        await send_telegram_message(message, user_id)

        # Record trade entry
        await record_trade_entry(
            user_id=user_id,
            symbol=symbol,
            entry_price=position.entry_price,
            current_price=current_price,
            size=contracts_amount,
            side="long",
            is_DCA=False
        )

        # Store TP data
        tp_data_key = TP_DATA_KEY.format(user_id=user_id, symbol=symbol, side="long")
        await redis_client.set(tp_data_key, json.dumps(position.tp_prices))

        return True

    except Exception as e:
        if "직전 주문 종료 후 쿨다운 시간이 지나지 않았습니다." in str(e):
            pass
        else:
            error_logger.error("롱 포지션 진입 실패", exc_info=True)
            traceback.print_exc()
            error_msg = map_exchange_error(e)
            await send_telegram_message(
                f"[{user_id}]⚠️ 롱 포지션 주문 실패\n"
                f"📊 심볼: {symbol}\n"
                f"\n"
                f"{error_msg}",
                1709556958,
                immediate=True
            )
        return False


async def _execute_short_entry(
    user_id: str,
    symbol: str,
    timeframe: str,
    timeframe_str: str,
    contracts_amount: float,
    settings: dict,
    current_price: float,
    position_manager: PositionStateManager,
    trading_service: TradingService,
    atr_value: float,
    redis_client: Any
) -> bool:
    """
    Execute short position entry.

    Args:
        user_id: User identifier
        symbol: Trading symbol
        timeframe: Timeframe string
        timeframe_str: Formatted timeframe string
        contracts_amount: Contract amount to enter
        settings: User settings
        current_price: Current market price
        position_manager: Position manager instance
        trading_service: Trading service instance
        atr_value: ATR value for messaging
        redis_client: Redis client instance

    Returns:
        True if entry successful, False otherwise
    """
    try:
        # Runtime import to avoid circular dependency
        from HYPERRSI.src.api.routes.position import OpenPositionRequest, open_position_endpoint

        print("2번")
        request = OpenPositionRequest(
            user_id=user_id,
            symbol=symbol,
            direction="short",
            size=contracts_amount,
            leverage=settings['leverage'],
            take_profit=None,
            stop_loss=None,
            order_concept='',
            is_DCA=False,
            is_hedge=False,
            hedge_tp_price=None,
            hedge_sl_price=None
        )

        # Open position via API
        position = await open_position_endpoint(request)

        # Validate position response
        await validate_position_response(position, user_id, "short", "entry")

        # Update Redis keys
        dca_long_key = DCA_LEVELS_KEY.format(user_id=user_id, symbol=symbol, side="long")
        dca_count_key = DCA_COUNT_KEY.format(user_id=user_id, symbol=symbol, side="short")
        dual_side_count_key = DUAL_SIDE_COUNT_KEY.format(user_id=user_id, symbol=symbol)

        await redis_client.set(dca_count_key, "1")
        await redis_client.delete(dca_long_key)
        await redis_client.set(dual_side_count_key, "0")

        # Set initial_size and last_entry_size
        position_key = POSITION_KEY.format(user_id=user_id, symbol=symbol, side="short")
        await redis_client.hset(position_key, "initial_size", contracts_amount)
        await redis_client.hset(position_key, "last_entry_size", contracts_amount)

        # Set position lock until next candle
        await set_position_lock(user_id, symbol, "short", timeframe)

        # Send success message
        message = await create_position_message(
            user_id=user_id,
            symbol=symbol,
            position_type="short",
            position=position,
            settings=settings,
            tp_levels=position.tp_prices if position.tp_prices else None,
            stop_loss=position.sl_price,
            contracts_amount=contracts_amount,
            trading_service=trading_service,
            atr_value=atr_value
        )

        await send_telegram_message(message, user_id)

        # Update position state
        await position_manager.update_position_state(
            user_id,
            symbol,
            current_price,
            contracts_amount,
            "short",
            operation_type="new_position"
        )

        # Store TP data
        tp_data_key = TP_DATA_KEY.format(user_id=user_id, symbol=symbol, side="short")
        await redis_client.set(tp_data_key, json.dumps(position.tp_prices))

        # Record trade entry
        await record_trade_entry(
            user_id=user_id,
            symbol=symbol,
            entry_price=position.entry_price,
            current_price=current_price,
            size=contracts_amount,
            side="short"
        )

        return True

    except Exception as e:
        if "직전 주문 종료 후 쿨다운 시간이 지나지 않았습니다." in str(e):
            pass
        else:
            error_msg = map_exchange_error(e)
            error_logger.error("숏 포지션 진입 실패", exc_info=True)
            await send_telegram_message(
                f"[{user_id}]⚠️ 숏 포지션 주문 실패\n"
                f"📊 심볼: {symbol}\n"
                f"\n"
                f"{error_msg}",
                user_id,
                debug=True,
                immediate=True
            )
        return False


async def _handle_entry_success(user_id: str, redis_client: Any) -> None:
    """
    Handle successful entry by resetting failure count.

    Args:
        user_id: User identifier
        redis_client: Redis client instance
    """
    await reset_entry_failure(user_id)


async def _handle_entry_failure(
    user_id: str,
    side: str,
    current_fail_count: int,
    redis_client: Any
) -> int:
    """
    Handle entry failure by incrementing failure count.

    Args:
        user_id: User identifier
        side: Position side ("long" or "short")
        current_fail_count: Current failure count
        redis_client: Redis client instance

    Returns:
        Updated failure count
    """
    entry_fail_count_key = ENTRY_FAIL_COUNT_KEY.format(user_id=user_id)
    new_count = current_fail_count + 1
    await redis_client.set(entry_fail_count_key, new_count)
    return new_count


async def _send_trend_alert(
    user_id: str,
    symbol: str,
    timeframe: str,
    side: str,
    redis_client: Any
) -> None:
    """
    Send trend condition alert when entry is blocked by trend logic.

    Args:
        user_id: User identifier
        symbol: Trading symbol
        timeframe: Timeframe string
        side: Position side ("long" or "short")
        redis_client: Redis client instance
    """
    alert_key = TREND_SIGNAL_ALERT_KEY.format(user_id=user_id)
    is_alerted = await redis_client.get(alert_key)

    if not is_alerted:
        side_kr = "롱" if side == "long" else "숏"
        message = (
            f"⚠️ {side_kr} 포지션 진입 조건 불충족\n"
            f"\n"
            f"RSI {'과매도' if side == 'long' else '과매수'} 상태이지만 "
            f"트렌드 조건이 맞지 않아 진입하지 않습니다."
        )
        await send_telegram_message(message, user_id)
        await redis_client.set(alert_key, "true", ex=TREND_ALERT_EXPIRY_SECONDS)
        logger.info(f"[{user_id}] {side_kr} 포지션 진입 조건 불충족 알림 전송 완료. {symbol} {timeframe}")
