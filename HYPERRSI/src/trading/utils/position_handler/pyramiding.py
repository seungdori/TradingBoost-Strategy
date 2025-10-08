"""
Position Handler Pyramiding Module

This module handles DCA (Dollar Cost Averaging) and pyramiding logic for existing positions.
Includes entry size calculation, long/short pyramiding execution, and DCA state updates.
"""

import asyncio
import json
from datetime import datetime
from typing import Dict, Any, Tuple, Optional

from HYPERRSI.src.trading.trading_service import TradingService
from HYPERRSI.src.trading.models import Position, get_timeframe
from HYPERRSI.src.bot.telegram_message import send_telegram_message
from HYPERRSI.src.trading.stats import record_trade_entry
from HYPERRSI.src.trading.error_message import map_exchange_error
from HYPERRSI.src.trading.position_manager import PositionStateManager
from HYPERRSI.src.trading.services.get_current_price import get_current_price
from HYPERRSI.src.api.routes.position import open_position_endpoint, OpenPositionRequest
from HYPERRSI.src.trading.dual_side_entry import manage_dual_side_entry
from HYPERRSI.src.trading.utils.trading_utils import (
    calculate_dca_levels,
    update_dca_levels_redis,
    check_dca_condition
)
from shared.logging import get_logger
from HYPERRSI.src.core.logger import setup_error_logger

# Import from position_handler package
from HYPERRSI.src.trading.utils.position_handler.core import (
    get_redis_client,
    calculate_next_candle_time,
    set_position_lock,
    get_investment_amount
)
from HYPERRSI.src.trading.utils.position_handler.validation import (
    check_cooldown,
    check_position_lock,
    validate_position_response,
    should_enter_with_trend
)
from HYPERRSI.src.trading.utils.position_handler.constants import (
    DCA_COUNT_KEY,
    DCA_LEVELS_KEY,
    POSITION_KEY,
    TREND_SIGNAL_ALERT_KEY,
    TREND_ALERT_EXPIRY_SECONDS,
    TREND_STATE_STRONG_DOWNTREND,
    TREND_STATE_STRONG_UPTREND
)
from HYPERRSI.src.trading.utils.position_handler.messaging import (
    parse_tp_prices,
    format_next_dca_level
)

logger = get_logger(__name__)
error_logger = setup_error_logger()


async def handle_pyramiding(
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
    current_price: float,
    atr_value: float,
    use_dual_side_settings: str
) -> Position:
    """
    Handle DCA/pyramiding additional entry for existing positions.

    This is the main orchestrator for adding to positions via Dollar Cost Averaging (DCA)
    or pyramiding strategy. It handles both long and short positions.

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
        side: Position side ("long" or "short")
        current_price: Current market price
        atr_value: ATR value for DCA level calculation
        use_dual_side_settings: Whether dual-side trading is enabled

    Returns:
        Updated position object (or original if no changes)

    Side Effects:
        - Opens additional position via exchange API
        - Updates Redis DCA state and position info
        - Sends Telegram notifications
        - Records trade entries in stats
        - Sets position locks
    """
    redis_client = get_redis_client()
    position_manager = PositionStateManager(trading_service)

    # Get pyramiding settings
    pyramiding_limit = settings.get('pyramiding_limit', 1)
    use_check_DCA_with_price = settings.get('use_check_DCA_with_price', True)

    # Check cooldown and position lock
    is_cooldown, left_time = await check_cooldown(user_id, symbol, side)
    if is_cooldown:
        print(f"[{user_id}] 쿨다운 중입니다. {symbol}의 {side}방향 종목에 대해서는 진입을 하지 않습니다. 남은 시간: {left_time}초")
        return current_position

    is_locked, remaining_time = await check_position_lock(user_id, symbol, side, timeframe)
    if is_locked:
        logger.info(f"[{user_id}] 포지션 {symbol}의 {side}방향 진입 잠금 중입니다. 남은 시간: {remaining_time}s")
        return current_position

    # Proceed only if pyramiding is enabled
    if pyramiding_limit <= 1:
        return current_position

    # Get position info
    position_key = POSITION_KEY.format(user_id=user_id, symbol=symbol, side=side)
    position_info = await redis_client.hgetall(position_key)

    # Get or calculate DCA levels
    dca_key = DCA_LEVELS_KEY.format(user_id=user_id, symbol=symbol, side=side)
    dca_levels = await redis_client.lrange(dca_key, 0, -1)

    # Always recalculate DCA levels for accuracy
    entry_price = position_info.get('entry_price', str(current_price))
    if entry_price == 'None' or entry_price == None:
        initial_entry_price = float(current_price)
    else:
        initial_entry_price = float(entry_price)

    last_filled_price_raw = position_info.get('last_filled_price', str(initial_entry_price))
    if last_filled_price_raw == 'None' or last_filled_price_raw == None:
        last_filled_price = float(initial_entry_price)
    else:
        last_filled_price = float(last_filled_price_raw)

    print(f"[{user_id}] initial_entry_price : {initial_entry_price}, last_filled_price : {last_filled_price}")
    dca_levels = await calculate_dca_levels(
        initial_entry_price,
        last_filled_price,
        settings,
        side,
        atr_value,
        current_price,
        user_id
    )
    await update_dca_levels_redis(user_id, symbol, dca_levels, side)

    # Refresh DCA levels from Redis
    dca_levels = await redis_client.lrange(dca_key, 0, -1)

    # Check if DCA condition is met
    check_dca_condition_result = await check_dca_condition(
        current_price,
        dca_levels,
        side,
        use_check_DCA_with_price
    )

    if not check_dca_condition_result:
        return current_position

    # Get DCA order count
    dca_count_key = DCA_COUNT_KEY.format(user_id=user_id, symbol=symbol, side=side)
    dca_order_count = await redis_client.get(dca_count_key)

    if dca_order_count is None:
        dca_order_count = 1
        await redis_client.set(dca_count_key, 1)
    else:
        dca_order_count = int(dca_order_count)

    print(f"[{user_id}] dca_order_count: {dca_order_count}")

    # Get position size info
    position_size = float(position_info.get('size', 0))
    entry_price = float(position_info.get('entry_price', current_price))
    last_entry_size = float(position_info.get('last_entry_size', 0))

    # Handle missing last_entry_size
    if last_entry_size == 0 and dca_order_count > 1:
        last_entry_size = await _recover_last_entry_size(
            user_id,
            symbol,
            side,
            dca_order_count,
            position_info,
            settings,
            redis_client
        )
        if last_entry_size == 0:
            return current_position

    # Calculate new entry size
    new_entry_contracts_amount = await _calculate_dca_entry_size(
        user_id=user_id,
        symbol=symbol,
        side=side,
        dca_order_count=dca_order_count,
        last_entry_size=last_entry_size,
        settings=settings,
        trading_service=trading_service,
        current_price=current_price,
        position_info=position_info,
        redis_client=redis_client
    )

    if new_entry_contracts_amount <= 0:
        logger.warning(f"[{user_id}] Invalid DCA entry size: {new_entry_contracts_amount}")
        return current_position

    # Execute pyramiding based on side
    if side == "long":
        await _execute_long_pyramiding(
            user_id=user_id,
            symbol=symbol,
            timeframe=timeframe,
            dca_order_count=dca_order_count,
            new_entry_contracts_amount=new_entry_contracts_amount,
            settings=settings,
            trading_service=trading_service,
            current_price=current_price,
            current_state=current_state,
            rsi_signals=rsi_signals,
            position_manager=position_manager,
            use_dual_side_settings=use_dual_side_settings,
            redis_client=redis_client
        )
    elif side == "short":
        await _execute_short_pyramiding(
            user_id=user_id,
            symbol=symbol,
            timeframe=timeframe,
            dca_order_count=dca_order_count,
            new_entry_contracts_amount=new_entry_contracts_amount,
            settings=settings,
            trading_service=trading_service,
            current_price=current_price,
            current_state=current_state,
            rsi_signals=rsi_signals,
            position_manager=position_manager,
            use_dual_side_settings=use_dual_side_settings,
            redis_client=redis_client
        )
    else:
        print("side 오류입니다. side : ", side)

    return current_position


async def _recover_last_entry_size(
    user_id: str,
    symbol: str,
    side: str,
    dca_order_count: int,
    position_info: dict,
    settings: dict,
    redis_client: Any
) -> float:
    """
    Recover last_entry_size when it's missing from Redis.

    This handles cases where last_entry_size is 0 or None by calculating
    it from initial_size and entry multiplier.

    Args:
        user_id: User identifier
        symbol: Trading symbol
        side: Position side
        dca_order_count: Current DCA count
        position_info: Position info from Redis
        settings: User settings
        redis_client: Redis client instance

    Returns:
        Recovered last_entry_size value
    """
    try:
        initial_size = float(position_info.get('initial_size', 0))
        if initial_size == 0:
            initial_size_str = await redis_client.get(
                f"user:{user_id}:position:{symbol}:{side}:initial_size"
            )
            if initial_size_str is None:
                initial_size = 0
            else:
                initial_size = float(initial_size_str)
    except Exception as e:
        initial_size = 0
        await send_telegram_message(
            f"[{user_id}] initial_size가 없습니다. 초기화 중입니다. 오류를 확인해주세요",
            user_id,
            debug=True
        )

    scale = settings.get('entry_multiplier', 0.5)
    if initial_size > 0:
        calculated_last_entry_size = initial_size * (scale ** (dca_order_count - 1))

        position_key = POSITION_KEY.format(user_id=user_id, symbol=symbol, side=side)
        await redis_client.hset(position_key, "last_entry_size", str(calculated_last_entry_size))
        await send_telegram_message(
            f"[{user_id}] last_entry_size가 0이어서 재계산했습니다: {calculated_last_entry_size}",
            user_id,
            debug=True
        )
        return calculated_last_entry_size
    else:
        await send_telegram_message(
            f"[{user_id}] last_entry_size가 0이고 initial_size도 없습니다. 초기화 중입니다. 오류를 확인해주세요",
            user_id,
            debug=True
        )
        return 0.0


async def _calculate_dca_entry_size(
    user_id: str,
    symbol: str,
    side: str,
    dca_order_count: int,
    last_entry_size: float,
    settings: dict,
    trading_service: TradingService,
    current_price: float,
    position_info: dict,
    redis_client: Any
) -> float:
    """
    Calculate the contract size for DCA entry.

    This function attempts to calculate the new entry size using the trading service,
    and falls back to manual calculation if that fails.

    Args:
        user_id: User identifier
        symbol: Trading symbol
        side: Position side
        dca_order_count: Current DCA count
        last_entry_size: Size of last entry
        settings: User settings
        trading_service: Trading service instance
        current_price: Current market price
        position_info: Position info from Redis
        redis_client: Redis client instance

    Returns:
        New entry contract amount
    """
    scale = settings.get('entry_multiplier', 0.5)
    manual_calculated_initial_size: float = 0.0

    try:
        # Get investment amount for symbol
        investment = get_investment_amount(settings, symbol)
        new_investment = float(investment) * (scale ** dca_order_count)

        # Get contract info from trading service
        contract_info = await trading_service.get_contract_info(
            symbol=symbol,
            user_id=user_id,
            size_usdt=new_investment,
            leverage=settings['leverage'],
            current_price=current_price
        )

        new_entry_contracts_amount = contract_info['contracts_amount']
        return new_entry_contracts_amount

    except Exception as e:
        # Manual calculation fallback
        print(f"[{user_id}] scale : {scale}")
        manual_calculated_initial_size_raw = await redis_client.get(
            f"user:{user_id}:position:{symbol}:{side}:initial_size"
        )

        position_size = float(position_info.get('size', 0))

        if dca_order_count == 1:
            manual_calculated_initial_size = float(position_size)
        elif dca_order_count > 1:
            if manual_calculated_initial_size_raw is None or \
               manual_calculated_initial_size_raw == "None" or \
               manual_calculated_initial_size_raw == "0":
                manual_calculated_initial_size = float(position_size) / float(dca_order_count)
            else:
                try:
                    manual_calculated_initial_size = float(manual_calculated_initial_size_raw)
                    if manual_calculated_initial_size == 0:
                        manual_calculated_initial_size = float(position_size) / float(dca_order_count)
                except (ValueError, TypeError):
                    manual_calculated_initial_size = float(position_size) / float(dca_order_count)

        new_entry_contracts_amount = float(manual_calculated_initial_size) * float(scale) * float(dca_order_count)

        await send_telegram_message(
            f"⛔️[{user_id}] : 뭔가 이상한 상황! 초기진입사이즈! "
            f"초기진입사이즈 : {manual_calculated_initial_size}, "
            f"배율 : {scale}, "
            f"DCA횟수 : {dca_order_count}, "
            f"총 진입사이즈 : {new_entry_contracts_amount}",
            user_id,
            debug=True
        )

        return new_entry_contracts_amount


async def _execute_long_pyramiding(
    user_id: str,
    symbol: str,
    timeframe: str,
    dca_order_count: int,
    new_entry_contracts_amount: float,
    settings: dict,
    trading_service: TradingService,
    current_price: float,
    current_state: int,
    rsi_signals: dict,
    position_manager: PositionStateManager,
    use_dual_side_settings: str,
    redis_client: Any
) -> None:
    """
    Execute long pyramiding (DCA) entry.

    This function handles the complete long pyramiding workflow including:
    - Trend and RSI validation
    - Position entry via API
    - State updates
    - Notifications
    - Dual-side entry management

    Args:
        user_id: User identifier
        symbol: Trading symbol
        timeframe: Timeframe string
        dca_order_count: Current DCA count
        new_entry_contracts_amount: New entry size in contracts
        settings: User settings
        trading_service: Trading service instance
        current_price: Current market price
        current_state: Current trend state
        rsi_signals: RSI signal flags
        position_manager: Position manager instance
        use_dual_side_settings: Whether dual-side is enabled
        redis_client: Redis client instance
    """
    # Check trend condition
    should_check_trend = settings.get('use_trend_logic', True)
    trend_condition = True
    if should_check_trend and current_state == TREND_STATE_STRONG_DOWNTREND:
        trend_condition = False

    # Check RSI condition
    rsi_long_signals_condition = False
    if settings.get('use_rsi_with_pyramiding', True):
        rsi_long_signals_condition = rsi_signals['is_oversold']
    else:
        rsi_long_signals_condition = True

    print(
        f"[{user_id}] rsi_signals['is_oversold'] : {rsi_signals['is_oversold']}, "
        f"trend_condition : {trend_condition}, "
        f"dca_order_count : {dca_order_count}, "
        f"pyramiding_limit : {settings.get('pyramiding_limit', 1)}"
    )

    if dca_order_count + 1 > settings.get('pyramiding_limit', 1):
        return

    if not rsi_long_signals_condition:
        return

    if not trend_condition:
        print("하락 트랜드이므로 추가 진입을 하지 않습니다.")
        await _send_pyramiding_trend_alert(user_id, symbol, timeframe, "long", redis_client)
        return

    try:
        print("3번")

        # Convert to qty for display
        new_position_entry_qty = await trading_service.contract_size_to_qty(
            user_id,
            symbol,
            new_entry_contracts_amount
        )

        position_key = POSITION_KEY.format(user_id=user_id, symbol=symbol, side="long")
        position_info = await redis_client.hgetall(position_key)
        initial_size = float(position_info.get('initial_size', 0))
        initial_entry_qty = await trading_service.contract_size_to_qty(user_id, symbol, initial_size)

        scale = settings.get('entry_multiplier', 0.5)
        await send_telegram_message(
            f"[{user_id}] 새로진입크기 : {new_position_entry_qty}, "
            f"초기진입사이즈 : {initial_entry_qty}, "
            f"배율 : {scale}, "
            f"DCA횟수 : {dca_order_count}\n "
            f"USDT계산 : {float(new_position_entry_qty) * current_price:,.2f}USDT",
            user_id,
            debug=True
        )

        logger.info(f"[{user_id}] new_position_entry_qty : {new_entry_contracts_amount}")

        # Create DCA entry request
        request = OpenPositionRequest(
            user_id=user_id,
            symbol=symbol,
            direction="long",
            size=new_entry_contracts_amount,
            leverage=settings['leverage'],
            take_profit=None,
            stop_loss=None,
            order_concept='',
            is_DCA=True,
            is_hedge=False,
            hedge_tp_price=None,
            hedge_sl_price=None
        )

        try:
            # Execute DCA entry
            position = await open_position_endpoint(request)

            # Validate position response
            await validate_position_response(position, user_id, "long", "DCA")

            # Update DCA count
            dca_count_key = DCA_COUNT_KEY.format(user_id=user_id, symbol=symbol, side="long")
            dca_order_count = await redis_client.get(dca_count_key)
            dca_order_count = int(dca_order_count) + 1
            await redis_client.set(dca_count_key, dca_order_count)

            # Update last_entry_size
            await redis_client.hset(
                f"user:{user_id}:position:{symbol}:long",
                "last_entry_size",
                new_entry_contracts_amount
            )

        except Exception as e:
            error_logger.error(f"[{user_id}]:DCA 롱 주문 실패", exc_info=True)
            await send_telegram_message(
                f"⚠️ DCA 추가진입 실패 (롱)\n\n{e}\n",
                okx_uid=user_id,
                debug=True
            )
            await set_position_lock(user_id, symbol, "long", timeframe)
            return

        # Update position state
        dca_key = DCA_LEVELS_KEY.format(user_id=user_id, symbol=symbol, side="long")
        new_entry_price = position.entry_price

        try:
            new_position_contract_size = position.size
            new_position_qty = await trading_service.contract_size_to_qty(
                user_id,
                symbol,
                new_position_contract_size
            )
        except Exception as e:
            await send_telegram_message(f"롱 추가진입 실패 오류: {e}", user_id, debug=True)
            print("롱 추가진입 실패 오류: ", e)
            return

        # Update position manager
        new_avg, new_size = await position_manager.update_position_state(
            user_id,
            symbol,
            current_price,
            contracts_amount_delta=new_position_contract_size,
            position_qty_delta=new_position_qty,
            side="long",
            operation_type="add_position",
            new_entry_exact_price=new_entry_price,
            new_exact_contract_size=new_position_contract_size
        )

        # Get updated position info
        new_position_qty_size_from_redis = await redis_client.hget(
            f"user:{user_id}:position:{symbol}:long",
            "position_qty"
        )
        position_avg_price = await trading_service.get_position_avg_price(user_id, symbol, "long")

        # Build and send Telegram message
        await _send_long_pyramiding_message(
            user_id=user_id,
            symbol=symbol,
            dca_order_count=dca_order_count,
            current_price=current_price,
            new_position_entry_qty=new_position_entry_qty,
            position_avg_price=position_avg_price,
            new_position_qty_size_from_redis=new_position_qty_size_from_redis,
            settings=settings,
            redis_client=redis_client
        )

        # Record trade entry
        try:
            await record_trade_entry(
                user_id=user_id,
                symbol=symbol,
                entry_price=current_price,
                current_price=current_price,
                size=new_position_contract_size,
                side="long",
                is_DCA=True,
                dca_count=dca_order_count
            )

            # Set position lock
            await set_position_lock(user_id, symbol, "long", timeframe)

        except Exception as e:
            error_logger.error(f"[{user_id}]:롱 주문 실패", exc_info=True)
            await send_telegram_message(
                f"⚠️ 추가진입 로깅 실패 (롱)\n\n{e}\n",
                okx_uid=user_id,
                debug=True
            )

        # Handle dual-side entry if enabled
        print("😍😍use dual side entry : ", use_dual_side_settings)
        if use_dual_side_settings:
            print("😍4번")
            print("=" * 100)
            try:
                await manage_dual_side_entry(
                    user_id=user_id,
                    symbol=symbol,
                    current_price=current_price,
                    dca_order_count=dca_order_count,
                    main_position_side="long",
                    settings=settings,
                    trading_service=trading_service,
                    exchange=trading_service.client
                )
            except Exception as e:
                error_logger.error(f"[{user_id}]:양방향 롱 진입 실패", exc_info=True)
                await send_telegram_message(
                    f"⚠️ 양방향 롱 진입 실패\n\n{e}\n",
                    okx_uid=user_id,
                    debug=True
                )

    except Exception as e:
        error_msg = map_exchange_error(e)
        error_logger.error(f"[{user_id}]:롱 주문 실패", exc_info=True)
        await send_telegram_message(
            f"⚠️[{user_id}] 추가진입 실패 (롱)\n"
            f"\n"
            f"{error_msg}\n"
            f"현재가: {current_price}\n"
            f"💰 추가 진입 수량: {new_position_entry_qty}\n"
            f"📊 추가 진입 계약 수량: {new_entry_contracts_amount}",
            user_id,
            debug=True
        )


async def _execute_short_pyramiding(
    user_id: str,
    symbol: str,
    timeframe: str,
    dca_order_count: int,
    new_entry_contracts_amount: float,
    settings: dict,
    trading_service: TradingService,
    current_price: float,
    current_state: int,
    rsi_signals: dict,
    position_manager: PositionStateManager,
    use_dual_side_settings: str,
    redis_client: Any
) -> None:
    """
    Execute short pyramiding (DCA) entry.

    Similar to long pyramiding but for short positions.

    Args:
        user_id: User identifier
        symbol: Trading symbol
        timeframe: Timeframe string
        dca_order_count: Current DCA count
        new_entry_contracts_amount: New entry size in contracts
        settings: User settings
        trading_service: Trading service instance
        current_price: Current market price
        current_state: Current trend state
        rsi_signals: RSI signal flags
        position_manager: Position manager instance
        use_dual_side_settings: Whether dual-side is enabled
        redis_client: Redis client instance
    """
    # Check trend condition
    should_check_trend = settings.get('use_trend_logic', True)
    trend_condition = True
    if should_check_trend and current_state == TREND_STATE_STRONG_UPTREND:
        trend_condition = False

    # Check RSI condition
    rsi_short_signals_condition = False
    if settings.get('use_rsi_with_pyramiding', True):
        rsi_short_signals_condition = rsi_signals['is_overbought']
    else:
        rsi_short_signals_condition = True

    print(
        f"[{user_id}] rsi short signals condition : {rsi_short_signals_condition}, "
        f"trend_condition : {trend_condition}, "
        f"dca_order_count : {dca_order_count}, "
        f"new_size : {new_entry_contracts_amount}"
    )

    if dca_order_count + 1 > settings.get('pyramiding_limit', 1):
        return

    if not (rsi_short_signals_condition and trend_condition):
        if rsi_short_signals_condition and not trend_condition:
            print("상승 트랜드이므로 추가 진입을 하지 않습니다.")
            await _send_pyramiding_trend_alert(user_id, symbol, timeframe, "short", redis_client)
        return

    print("<숏 포지션> 추가 진입 시작")

    try:
        # Create DCA entry request
        request = OpenPositionRequest(
            user_id=user_id,
            symbol=symbol,
            direction="short",
            size=new_entry_contracts_amount,
            leverage=settings['leverage'],
            take_profit=None,
            stop_loss=None,
            order_concept='',
            is_DCA=True,
            is_hedge=False,
            hedge_tp_price=None,
            hedge_sl_price=None
        )

        try:
            # Execute DCA entry
            position = await open_position_endpoint(request)

            # Validate position response
            await validate_position_response(position, user_id, "short", "DCA")

            # Update DCA count
            dca_count_key = DCA_COUNT_KEY.format(user_id=user_id, symbol=symbol, side="short")
            dca_order_count = await redis_client.get(dca_count_key)
            dca_order_count = int(dca_order_count) + 1
            await redis_client.set(dca_count_key, dca_order_count)

            # Set position lock
            await set_position_lock(user_id, symbol, "short", timeframe)

            # Update last_entry_size
            await redis_client.hset(
                f"user:{user_id}:position:{symbol}:short",
                "last_entry_size",
                new_entry_contracts_amount
            )

        except Exception as e:
            error_logger.error(f"[{user_id}]:DCA 숏 주문 실패", exc_info=True)
            await send_telegram_message(
                f"⚠️ DCA 추가진입 실패 (숏)\n\n{e}\n",
                okx_uid=user_id,
                debug=True
            )
            await set_position_lock(user_id, symbol, "short", timeframe)
            return

        # Handle dual-side entry if enabled
        if use_dual_side_settings:
            print("😍4번")
            print("=" * 100)
            try:
                await manage_dual_side_entry(
                    user_id=user_id,
                    symbol=symbol,
                    current_price=current_price,
                    dca_order_count=dca_order_count,
                    main_position_side="short",
                    settings=settings,
                    trading_service=trading_service,
                    exchange=trading_service.client
                )
            except Exception as e:
                error_logger.error(f"[{user_id}]: 양방향 숏 진입 실패", exc_info=True)
                await send_telegram_message(
                    f"⚠️ 양방향 숏 진입 실패\n\n{e}\n",
                    okx_uid=user_id,
                    debug=True
                )

        # Remove first DCA level
        dca_key = DCA_LEVELS_KEY.format(user_id=user_id, symbol=symbol, side="short")
        await redis_client.lpop(dca_key)

        # Get position info
        new_entry_price = position.entry_price

        try:
            new_total_contract_size = position.size
            new_position_contract_size = position.size
            new_position_qty = await trading_service.contract_size_to_qty(
                user_id,
                symbol,
                new_entry_contracts_amount
            )
        except Exception as e:
            await send_telegram_message(f"숏 추가진입 실패 오류: {e}", user_id, debug=True)
            print("숏 추가진입 실패 오류: ", e)
            return

        # Update position state
        await position_manager.update_position_state(
            user_id,
            symbol,
            current_price,
            contracts_amount_delta=new_entry_contracts_amount,
            position_qty_delta=new_position_qty,
            side="short",
            operation_type="add_position",
            new_entry_exact_price=new_entry_price,
            new_exact_contract_size=new_total_contract_size
        )

        # Send debug message
        position_key = POSITION_KEY.format(user_id=user_id, symbol=symbol, side="short")
        position_info = await redis_client.hgetall(position_key)
        initial_size = float(position_info.get('initial_size', 0))
        initial_entry_qty = await trading_service.contract_size_to_qty(user_id, symbol, initial_size)
        new_position_entry_qty = await trading_service.contract_size_to_qty(
            user_id,
            symbol,
            new_entry_contracts_amount
        )

        scale = settings.get('entry_multiplier', 0.5)
        await send_telegram_message(
            f"[{user_id}] 새로진입크기 : {new_position_entry_qty}, "
            f"초기진입사이즈 : {initial_entry_qty}, "
            f"배율 : {scale}, "
            f"DCA횟수 : {dca_order_count}\n "
            f"USDT계산 : {float(new_position_entry_qty) * current_price:,.2f}USDT",
            user_id,
            debug=True
        )

        # Record trade entry
        await record_trade_entry(
            user_id=user_id,
            symbol=symbol,
            entry_price=current_price,
            current_price=current_price,
            size=new_position_contract_size,
            side="short",
            is_DCA=True,
            dca_count=dca_order_count
        )

        # Build and send Telegram message
        await _send_short_pyramiding_message(
            user_id=user_id,
            symbol=symbol,
            dca_order_count=dca_order_count,
            current_price=current_price,
            new_position_qty=new_position_qty,
            trading_service=trading_service,
            settings=settings,
            redis_client=redis_client
        )

    except Exception as e:
        error_msg = map_exchange_error(e)
        error_logger.error(f"[{user_id}]:DCA 숏 주문 실패", exc_info=True)
        await send_telegram_message(
            f"⚠️ 숏 추가진입 실패)\n"
            f"\n"
            f"현재가: {current_price}\n"
            f"💰 추가 진입 수량: {new_position_qty}",
            user_id
        )
        await send_telegram_message(
            f"⚠️ 숏 추가진입 실패\n"
            f"\n"
            f"{error_msg}\n"
            f"현재가: {current_price}\n"
            f"💰 추가 진입 수량: {new_position_qty}\n"
            f"📊 추가 진입 계약 수량: {new_entry_contracts_amount}",
            user_id,
            debug=True
        )
        await set_position_lock(user_id, symbol, "short", timeframe)


async def _send_long_pyramiding_message(
    user_id: str,
    symbol: str,
    dca_order_count: int,
    current_price: float,
    new_position_entry_qty: float,
    position_avg_price: float,
    new_position_qty_size_from_redis: str,
    settings: dict,
    redis_client: Any
) -> None:
    """
    Build and send long pyramiding notification message.

    Args:
        user_id: User identifier
        symbol: Trading symbol
        dca_order_count: DCA count
        current_price: Current price
        new_position_entry_qty: New entry quantity
        position_avg_price: Average position price
        new_position_qty_size_from_redis: Total position size
        settings: User settings
        redis_client: Redis client instance
    """
    # Get TP prices
    tp_prices = await redis_client.hget(f"user:{user_id}:position:{symbol}:long", "tp_prices")
    use_tp1 = settings.get('use_tp1', True)
    use_tp2 = settings.get('use_tp2', True)
    use_tp3 = settings.get('use_tp3', True)

    use_trailing_stop = settings.get('trailing_stop_active', False)
    trailing_start_point = settings.get('trailing_start_point', 'tp3')

    # Parse TP prices
    tp_prices_str = ""
    if tp_prices:
        tp_prices_str = parse_tp_prices(tp_prices, settings)

        # Adjust for trailing stop
        if use_trailing_stop:
            if trailing_start_point == 'tp1':
                use_tp2 = False
                use_tp3 = False
            elif trailing_start_point == 'tp2':
                use_tp3 = False

    # Get next DCA level
    next_dca_level_str = ""
    dca_levels_key = DCA_LEVELS_KEY.format(user_id=user_id, symbol=symbol, side="long")
    dca_levels = await redis_client.lrange(dca_levels_key, 0, 0)

    if dca_levels and len(dca_levels) > 0:
        next_dca_level_str = format_next_dca_level(dca_levels, "long")

    # Build message
    telegram_message = "🔼 추가진입 (롱)"
    telegram_message += "\n"
    telegram_message += f"[{symbol}]\n"
    telegram_message += f"📊 롱 {dca_order_count}회차 진입\n\n"
    telegram_message += f"💲 진입 가격 : {current_price:,.2f}\n"
    telegram_message += f"📈 수량: +{new_position_entry_qty}\n"
    telegram_message += f"(USDT 기준 : {float(new_position_entry_qty) * current_price:,.2f}USDT)\n"
    telegram_message += f"💰 새 평균가: {position_avg_price:,.2f}\n"
    telegram_message += f"📝 총 포지션: {float(new_position_qty_size_from_redis):.3f}\n"

    if tp_prices_str != "":
        telegram_message += f"\n{tp_prices_str}\n"

    if next_dca_level_str != "":
        telegram_message += f"\n📍 {next_dca_level_str}\n"

    telegram_message += ""

    asyncio.create_task(send_telegram_message(telegram_message, user_id))


async def _send_short_pyramiding_message(
    user_id: str,
    symbol: str,
    dca_order_count: int,
    current_price: float,
    new_position_qty: float,
    trading_service: TradingService,
    settings: dict,
    redis_client: Any
) -> None:
    """
    Build and send short pyramiding notification message.

    Args:
        user_id: User identifier
        symbol: Trading symbol
        dca_order_count: DCA count
        current_price: Current price
        new_position_qty: New position quantity
        trading_service: Trading service instance
        settings: User settings
        redis_client: Redis client instance
    """
    # Get position info
    total_position_qty = await redis_client.hget(
        f"user:{user_id}:position:{symbol}:short",
        "position_qty"
    )
    position_avg_price = await trading_service.get_position_avg_price(user_id, symbol, "short")

    # Get TP prices
    tp_prices = await redis_client.hget(f"user:{user_id}:position:{symbol}:short", "tp_prices")
    use_tp1 = settings.get('use_tp1', True)
    use_tp2 = settings.get('use_tp2', True) and not (
        settings.get('trailing_stop_active', False) and
        (settings.get('trailing_start_point', 'tp3') == 'tp1')
    )
    use_tp3 = settings.get('use_tp3', True) and not (
        settings.get('trailing_stop_active', False) and
        (settings.get('trailing_start_point', 'tp3') == 'tp1' or
         settings.get('trailing_start_point', 'tp3') == 'tp2')
    )

    # Parse TP prices
    tp_prices_str = ""
    if tp_prices:
        tp_prices_str = parse_tp_prices(tp_prices, settings)

    # Get next DCA level
    next_dca_level_str = ""
    dca_levels_key = DCA_LEVELS_KEY.format(user_id=user_id, symbol=symbol, side="short")
    dca_levels = await redis_client.lrange(dca_levels_key, 0, 0)

    # If DCA levels are empty, recalculate
    if not dca_levels or len(dca_levels) == 0:
        print(f"[{user_id}] DCA 레벨이 비어있지만 조건 충족.")
        # Recalculation logic would go here if needed
    else:
        next_dca_level_str = format_next_dca_level(dca_levels, "short")

    # Build message
    telegram_message = "🔻 추가진입 (숏)"
    telegram_message += "\n"
    telegram_message += f"[{symbol}]\n"
    telegram_message += f"📊 숏 {dca_order_count}회차 진입\n\n"
    telegram_message += f"💲 진입 가격 : {current_price:,.2f}\n"
    telegram_message += f"📈 수량: +{new_position_qty}\n"
    telegram_message += f"(USDT 기준 : {float(new_position_qty) * current_price:,.2f}USDT)\n"
    telegram_message += f"💰 새 평균가: {position_avg_price:,.2f}\n"
    telegram_message += f"📝 총 포지션: {float(total_position_qty):.3f}\n"

    if tp_prices_str:
        telegram_message += f"\n{tp_prices_str}\n"

    if next_dca_level_str != "":
        telegram_message += f"\n📍 {next_dca_level_str}\n"
    else:
        print("next_dca_level_str 없음!!")

    telegram_message += ""

    await send_telegram_message(telegram_message, user_id)


async def _send_pyramiding_trend_alert(
    user_id: str,
    symbol: str,
    timeframe: str,
    side: str,
    redis_client: Any
) -> None:
    """
    Send trend alert when pyramiding is blocked by trend conditions.

    Args:
        user_id: User identifier
        symbol: Trading symbol
        timeframe: Timeframe string
        side: Position side
        redis_client: Redis client instance
    """
    alert_key = TREND_SIGNAL_ALERT_KEY.format(user_id=user_id)
    is_alerted = await redis_client.get(alert_key)

    if not is_alerted:
        side_kr = "q" if side == "long" else ""
        await send_telegram_message(
            f"⚠️ {side_kr} 추가진입 진입 조건 불충족\n"
            f"\n"
            f"RSI 신호는 있지만 트렌드 조건이 맞지 않아 추가진입하지 않습니다.",
            user_id
        )
        await redis_client.set(alert_key, "true", ex=TREND_ALERT_EXPIRY_SECONDS)
        await set_position_lock(user_id, symbol, side, timeframe)
