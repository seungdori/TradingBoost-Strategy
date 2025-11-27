# execute_trading_logic.py

import asyncio
import json
import traceback
from datetime import datetime, timedelta
from os import error
from typing import Dict

from HYPERRSI.src.api.routes.position import OpenPositionRequest, open_position_endpoint
from HYPERRSI.src.api.trading.Calculate_signal import TrendStateCalculator
from HYPERRSI.src.bot.telegram_message import send_telegram_message
from HYPERRSI.src.core.logger import setup_error_logger
from HYPERRSI.src.trading.dual_side_entry import manage_dual_side_entry
from HYPERRSI.src.trading.error_message import map_exchange_error
from HYPERRSI.src.trading.models import Position, get_timeframe
from HYPERRSI.src.trading.position_manager import PositionStateManager
from HYPERRSI.src.trading.services.get_current_price import get_current_price
from HYPERRSI.src.trading.stats import record_trade_entry, update_trading_stats
from HYPERRSI.src.trading.trading_service import TradingService
from HYPERRSI.src.trading.utils.message_builder import create_position_message
from HYPERRSI.src.trading.utils.trading_utils import (
    calculate_dca_levels,
    check_dca_condition,
    init_user_position_data,
    update_dca_levels_redis,
)
from shared.database.redis_helper import get_redis_client
from shared.logging import get_logger
from shared.utils import contracts_to_qty

logger = get_logger(__name__)
error_logger = setup_error_logger()

# Dynamic redis_client access


async def check_margin_block(user_id: str, symbol: str) -> bool:
    """사용자의 특정 심볼에 대한 자금 부족 차단 상태를 확인합니다.

    Args:
        user_id (str): 사용자 ID
        symbol (str): 심볼

    Returns:
        bool: 차단된 경우 True, 아닌 경우 False
    """

    redis = await get_redis_client()
    redis_client = get_redis_client()
    block_key = f"margin_block:{user_id}:{symbol}"
    block_status = await redis.get(block_key)
    return block_status is not None


# 타임프레임에 따른 다음 봉의 시작 시간을 계산하는 함수
async def calculate_next_candle_time(timeframe):
    """
    타임프레임에 따라 다음 캔들(봉)의 시작 시간을 계산합니다.
    
    Args:
        timeframe (str): 타임프레임 (예: "1m", "5m", "15m" 등)
        
    Returns:
        int: 다음 캔들 시작 시간의 Unix 타임스탬프 (초 단위)
    """
    now = datetime.now()
    tf_str = get_timeframe(timeframe)
    
    if tf_str == "1m":
        # 다음 분의 시작 시간
        next_minute = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
        return int(next_minute.timestamp())
    
    elif tf_str == "5m":
        # 현재 분을 5로 나눈 나머지를 계산
        current_minute = now.minute
        minutes_to_add = 5 - (current_minute % 5)
        if minutes_to_add == 5:
            minutes_to_add = 0
        next_5min = now.replace(second=0, microsecond=0) + timedelta(minutes=minutes_to_add)
        return int(next_5min.timestamp())
    
    elif tf_str == "15m":
        # 현재 분을 15로 나눈 나머지를 계산
        current_minute = now.minute
        minutes_to_add = 15 - (current_minute % 15)
        if minutes_to_add == 15:
            minutes_to_add = 0
        next_15min = now.replace(second=0, microsecond=0) + timedelta(minutes=minutes_to_add)
        return int(next_15min.timestamp())
    
    elif tf_str == "1h":
        # 다음 시간의 시작 시간
        next_hour = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        return int(next_hour.timestamp())
    
    elif tf_str == "4h":
        # 현재 시간을 4로 나눈 나머지를 계산
        current_hour = now.hour
        hours_to_add = 4 - (current_hour % 4)
        if hours_to_add == 4:
            hours_to_add = 0
        next_4hour = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=hours_to_add)
        return int(next_4hour.timestamp())
    
    elif tf_str == "1d":
        # 다음 날의 시작 시간
        next_day = (now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1))
        return int(next_day.timestamp())
    
    # 기본값으로 1분 후 반환
    return int((now + timedelta(minutes=1)).timestamp())

# ======== (A) 포지션이 없는 경우 ========
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
    포지션이 없을 때 롱/숏 진입 시도 -> 주문 발행
    """

    redis = await get_redis_client()
    redis_client = get_redis_client()
    try:
        print(f"[{user_id}] ✅포지션이 없는 경우")
        position_manager = PositionStateManager(trading_service)
        current_price = await get_current_price(symbol)
        
        investment = 0.0
        if symbol == "BTC-USDT-SWAP":
            investment = settings['btc_investment']
        elif symbol == "SOL-USDT-SWAP":
            investment = settings['sol_investment']
        elif symbol == "ETH-USDT-SWAP":
            investment = settings['eth_investment']
        else:
            investment = settings['investment']
        
        
        # 계약 정보 조회
        contract_info = await trading_service.get_contract_info(
            symbol=symbol,
            user_id=user_id,
            size_usdt=investment,
            leverage=settings['leverage'],
            current_price=current_price
        )
        # 실제 계약 수량 계산
        contracts_amount = contract_info['contracts_amount']  # 이미 최소 주문 수량 등이 고려된 값
        min_sustain_contract_size = 0.0
        if (float(settings['tp1_ratio']) + float(settings['tp2_ratio']) + float(settings['tp3_ratio']) == 1) or (float(settings['tp1_ratio']) + float(settings['tp2_ratio']) + float(settings['tp3_ratio']) == 100):
            min_sustain_contract_size = max(float(contracts_amount)*0.01, 0.02)
        else:
            min_sustain_contract_size = max(float(contracts_amount)*0.0001, 0.02)
        min_size_key = f"user:{user_id}:position:{symbol}:min_sustain_contract_size"
        await redis.set(min_size_key, min_sustain_contract_size)
        #print(f"[{user_id}] OKX 기준 주문 수량(콘트랙트 갯수): {contracts_amount}. 즉, 이게 주문이 들어가는 계약 수량.")
        await init_user_position_data(user_id, symbol, "long")
        await init_user_position_data(user_id, symbol, "short")
        timeframe_str = get_timeframe(timeframe)
        print(f"[{user_id}][{timeframe_str}] 포지션 없는 경우의 디버깅 : {current_rsi}, rsi signals : {rsi_signals},current state : {current_state}", flush=True)


        entry_fail_count_key = f"user:{user_id}:{symbol}:entry_fail_count"
        fail_count = int(await redis.get(entry_fail_count_key) or 0)
        print(f"[{user_id}] fail_count: {fail_count}")
        main_position_direction_key = f"user:{user_id}:position:{symbol}:main_position_direction"
        if await redis.exists(main_position_direction_key):
            await redis.delete(main_position_direction_key)
        if fail_count >= 5:
            #await send_telegram_message(
            #    "3회 연속 진입 실패로 트레이딩이 종료되었습니다.",
            #    user_id,
            #    debug=True
            #)
            #await redis_client.set(f"user:{user_id}:symbol:{symbol}:status", "stopped")
            #await send_telegram_message(f"⚠️[{user_id}] User의 상태를 Stopped로 강제 변경4.", user_id, debug=True)
            #await redis_client.delete(entry_fail_count_key)
            return

        key = f"candles_with_indicators:{symbol}:{timeframe_str}"
        try:
            candle = await redis.lindex(key, -1)
            if candle:
                candle = json.loads(candle)
                atr_value = candle.get('atr14')
            else:
                logger.error(f"캔들 데이터를 찾을 수 없습니다: {key}")
        except Exception as e:
            logger.error(f"Redis에서 ATR 데이터 가져오기 실패: {str(e)}")

        entry_success = False

        # 롱 진입
        if settings['direction'] in ['롱숏', '롱']:
            should_check_trend = settings.get('use_trend_logic', True)
            trend_condition = (current_state != -2) if should_check_trend else True
            if rsi_signals['is_oversold'] and trend_condition:
                try:
                    request = OpenPositionRequest(
                        user_id=user_id,
                        symbol=symbol,
                        direction="long",
                        size=contracts_amount,  # 달러 금액 대신 실제 계약 수량 전달
                        leverage=settings['leverage'],
                        take_profit=None,
                        stop_loss=None,
                        order_concept='',
                        is_DCA=False,
                        is_hedge=False,
                        hedge_tp_price=None,
                        hedge_sl_price=None
                    )
                    
                    
                        # 타임프레임 잠금 확인 - 현재 타임프레임에 대한 잠금이 있는지 확인
                    timeframe_lock_long_key = f"user:{user_id}:position_lock:{symbol}:long:{timeframe_str}"
                    timeframe_lock_short_key = f"user:{user_id}:position_lock:{symbol}:short:{timeframe_str}"
                    locked_direction = None
                    try:
                        is_locked = await redis.exists(timeframe_lock_long_key)
                        locked_direction = "long"
                        if not is_locked:
                            is_locked = await redis.exists(timeframe_lock_short_key)
                            locked_direction = "short"
                    except Exception as e:
                        is_locked = False
                    if is_locked:
                        if locked_direction == "long":  
                            remaining_time = await redis.ttl(timeframe_lock_long_key)
                        else:
                            remaining_time = await redis.ttl(timeframe_lock_short_key)
                        logger.info(f"[{user_id}] Position is locked for {symbol} with timeframe {timeframe_str}. Remaining time: {remaining_time}s")
                        return  # 잠금이 있으면 포지션을 열지 않고 리턴
                                
                    position = await open_position_endpoint(request)
                    
                    # 포지션이 실제로 성공적으로 열렸는지 확인
                    if position is None:
                        logger.warning(f"[{user_id}] 롱 포지션 생성 실패 - position이 None")
                        raise ValueError(f"포지션 생성 실패: position 객체가 None입니다")
                    
                    # margin_blocked이나 기타 에러 상태 확인
                    if hasattr(position, 'order_id') and position.order_id == "margin_blocked":
                        logger.warning(f"[{user_id}] 롱 포지션 생성 실패 - margin_blocked")
                        raise ValueError(f"포지션 생성 실패: 마진이 부족합니다 (margin_blocked)")
                    
                    # 포지션 크기가 유효한지 확인
                    if not hasattr(position, 'size') or position.size <= 0:
                        logger.warning(f"[{user_id}] 롱 포지션 생성 실패 - 유효하지 않은 포지션 크기")
                        raise ValueError(f"포지션 생성 실패: 유효하지 않은 포지션 크기 ({getattr(position, 'size', None)})")
                    
                    # 실제 진입 가격이 있는지 확인
                    if not hasattr(position, 'entry_price') or position.entry_price <= 0:
                        logger.warning(f"[{user_id}] 롱 포지션 생성 실패 - 유효하지 않은 진입 가격")
                        raise ValueError(f"포지션 생성 실패: 유효하지 않은 진입 가격 ({getattr(position, 'entry_price', None)})")
                    
                    print(f"﹗사이즈 점검! : position.size: {position.size},contracts_amount: {contracts_amount}")
                    short_dca_key = f"user:{user_id}:position:{symbol}:short:dca_levels"
                    dca_count_key = f"user:{user_id}:position:{symbol}:long:dca_count"
                    dual_side_count_key = f"user:{user_id}:{symbol}:dual_side_count"
                    await redis.set(dca_count_key, "1")
                    await redis.delete(short_dca_key)
                    await redis.set(dual_side_count_key, "0")
                    long_dca_key = f"user:{user_id}:position:{symbol}:long:dca_levels"
                    await redis.delete(long_dca_key)
                    
                    # initial_size와 last_entry_size 필드 추가
                    position_key = f"user:{user_id}:position:{symbol}:long"
                    
                    await redis.hset(position_key, "initial_size", contracts_amount)
                    await redis.hset(position_key, "last_entry_size", contracts_amount)
                    # 백업 키에도 초기 저장 (동기화/클린업 시 대비)
                    await redis.set(f"user:{user_id}:position:{symbol}:long:initial_size", contracts_amount)
                    #포지션 진입 후, 강제로, 해당 타임프레임이 끝날 때까지는 최소한 진입하지 않도록 레디스 키 설정
                    next_candle_time = await calculate_next_candle_time(timeframe)
                    tf_str = get_timeframe(timeframe)
                    timeframe_lock_key = f"user:{user_id}:position_lock:{symbol}:long:{tf_str}"
                    # 다음 캔들 시작 시간까지 잠금 설정 (expire time은 초 단위)
                    current_time = int(datetime.now().timestamp())
                    expire_seconds = next_candle_time - current_time
                    if expire_seconds > 0:
                        await redis.set(timeframe_lock_key, "locked", ex=expire_seconds)
                        logger.info(f"[{user_id}] 포지션 진입 후 롱 포지션 잠금 설정 완료. {symbol} {timeframe} until next candle at {next_candle_time}")
                    
                    try:
                        await position_manager.update_position_state(
                            user_id=user_id,
                            symbol=symbol,
                            entry_price=position.entry_price,
                            contracts_amount_delta=contracts_amount,  # 계약 수량 사용
                            side="long",
                            operation_type="new_position"
                        )
                    except Exception as e:
                        logger.error(f"포지션 정보 업데이트 실패: {str(e)}")
                        
                    
                    # 포지션이 성공적으로 열렸으므로 메시지 전송
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
                    await redis.set(f"user:{user_id}:position:{symbol}:long:dca_count", 1)
                    await record_trade_entry(
                        user_id=user_id,
                        symbol=symbol,
                        entry_price=position.entry_price,
                        current_price=current_price,
                        size=contracts_amount,  # 계약 수량 사용
                        side="long",
                        is_DCA=False
                    )
                    
                    tp_data_key = f"user:{user_id}:position:{symbol}:long:tp_data"
                    await redis.set(tp_data_key, json.dumps(position.tp_prices))
                    entry_success = True
                    await redis.delete(entry_fail_count_key)

                except Exception as e:
                    if "직전 주문 종료 후 쿨다운 시간이 지나지 않았습니다." in str(e):
                        pass
                    else:
                        error_logger.error("롱 포지션 진입 실패", exc_info=True)

                        traceback.print_exc()
                        error_msg = map_exchange_error(e)
                        if not entry_success:
                            fail_count += 1
                        await redis.set(entry_fail_count_key, fail_count)
                        
                        await send_telegram_message(f"[{user_id}]⚠️ 롱 포지션 주문 실패\n"f"━━━━━━━━━━━━━━━\n"f"{error_msg}\n"f"재시도 횟수: {fail_count}/3",1709556958)
            elif rsi_signals['is_oversold'] and not trend_condition:
                alert_key = f"user:{user_id}:{symbol}:trend_signal_alert"
                is_alerted = await redis.get(alert_key)
                if not is_alerted:
                    await send_telegram_message(    f"⚠️ 롱 포지션 진입 조건 불충족\n"    f"━━━━━━━━━━━━━━━\n"f"RSI가 과매수 상태이지만 트랜드 조건이 맞지 않아 진입을 유보합니다.",user_id)
                    await redis.set(alert_key, "true", ex=7200)
                    logger.info(f"[{user_id}] 롱 포지션 진입 조건 불충족 알림 전송 완료. {symbol} {timeframe}")

        # 숏 진입 로직도 동일하게 수정...
        if settings['direction'] in ['롱숏', '숏']:
            timeframe_lock_long_key = f"user:{user_id}:position_lock:{symbol}:long:{timeframe_str}"
            timeframe_lock_short_key = f"user:{user_id}:position_lock:{symbol}:short:{timeframe_str}"
            try:
                is_locked = await redis.exists(timeframe_lock_long_key)
                if not is_locked:
                    is_locked = await redis.exists(timeframe_lock_short_key)
                    if is_locked:
                        timeframe_lock_key = timeframe_lock_short_key
                    else:
                        timeframe_lock_key = timeframe_lock_long_key
                else:
                    timeframe_lock_key = timeframe_lock_long_key
            except Exception as e:
                is_locked = False
                timeframe_lock_key = timeframe_lock_long_key
            if is_locked:
                remaining_time = await redis.ttl(timeframe_lock_key)
                logger.info(f"[{user_id}] Position is locked for {symbol} with timeframe {timeframe_str}. Remaining time: {remaining_time}s")
                return  # 잠금이 있으면 포지션을 열지 않고 리턴

            should_check_trend = settings.get('use_trend_logic', True)
            trend_condition = (current_state != 2) if should_check_trend else True
            print(f"[{user_id}] 숏 진입 조건1 - is_overbought: {rsi_signals['is_overbought']}, trend_condition: {trend_condition}, current_state: {current_state}")
            if rsi_signals['is_overbought'] and trend_condition:
                try:
                    print("2번")
                    request = OpenPositionRequest(
                        user_id=user_id,
                        symbol=symbol,
                        direction="short",
                        size=contracts_amount,  # 달러 금액 대신 실제 계약 수량 전달
                        leverage=settings['leverage'],
                        take_profit=None,
                        stop_loss=None,
                        order_concept='',
                        is_DCA=False,
                        is_hedge=False,
                        hedge_tp_price=None,
                        hedge_sl_price=None
                    )
                    position = await open_position_endpoint(request)
                    
                    # 포지션이 실제로 성공적으로 열렸는지 확인
                    if position is None:
                        logger.warning(f"[{user_id}] 숏 포지션 생성 실패 - position이 None")
                        raise ValueError(f"포지션 생성 실패: position 객체가 None입니다")
                    
                    # margin_blocked이나 기타 에러 상태 확인
                    if hasattr(position, 'order_id') and position.order_id == "margin_blocked":
                        logger.warning(f"[{user_id}] 숏 포지션 생성 실패 - margin_blocked")
                        raise ValueError(f"포지션 생성 실패: 마진이 부족합니다 (margin_blocked)")
                    
                    # 포지션 크기가 유효한지 확인
                    if not hasattr(position, 'size') or position.size <= 0:
                        logger.warning(f"[{user_id}] 숏 포지션 생성 실패 - 유효하지 않은 포지션 크기")
                        raise ValueError(f"포지션 생성 실패: 유효하지 않은 포지션 크기 ({getattr(position, 'size', None)})")
                    
                    # 실제 진입 가격이 있는지 확인
                    if not hasattr(position, 'entry_price') or position.entry_price <= 0:
                        logger.warning(f"[{user_id}] 숏 포지션 생성 실패 - 유효하지 않은 진입 가격")
                        raise ValueError(f"포지션 생성 실패: 유효하지 않은 진입 가격 ({getattr(position, 'entry_price', None)})")
                    
                    dca_long_key = f"user:{user_id}:position:{symbol}:long:dca_levels"
                    dca_count_key = f"user:{user_id}:position:{symbol}:short:dca_count"
                    dual_side_count_key = f"user:{user_id}:{symbol}:dual_side_count"
                    await redis.set(dca_count_key, "1")
                    await redis.delete(dca_long_key)
                    await redis.set(dual_side_count_key, "0")
                    
                    # initial_size와 last_entry_size 필드 추가
                    position_key = f"user:{user_id}:position:{symbol}:short"
                    await redis.hset(position_key, "initial_size", contracts_amount)
                    await redis.hset(position_key, "last_entry_size", contracts_amount)
                    await redis.set(f"user:{user_id}:position:{symbol}:short:initial_size", contracts_amount)
                    #$await send_telegram_message(f"[{user_id}] 숏 포지션 진입 완료. 초기 크기: {contracts_amount}, 마지막 진입 크기: {contracts_amount}", user_id, debug = True)
                    
                    #포지션 진입 후, 강제로, 해당 타임프레임이 끝날 때까지는 최소한 진입하지 않도록 레디스 키 설정
                    next_candle_time = await calculate_next_candle_time(timeframe)
                    tf_str = get_timeframe(timeframe)
                    
                    timeframe_lock_key = f"user:{user_id}:position_lock:{symbol}:short:{tf_str}"
                    # 다음 캔들 시작 시간까지 잠금 설정 (expire time은 초 단위)
                    current_time = int(datetime.now().timestamp())
                    expire_seconds = next_candle_time - current_time
                    if expire_seconds > 0:
                        await redis.set(timeframe_lock_key, "locked", ex=expire_seconds)
                        logger.info(f"[{user_id}] 포지션 진입 후 숏 포지션 잠금 설정 완료. {symbol} {timeframe} until next candle at {next_candle_time}")
                    
                    # 포지션이 성공적으로 열렸으므로 메시지 전송
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
                    await position_manager.update_position_state(user_id, symbol, current_price, contracts_amount, "short", operation_type="new_position")
                    await redis.set(f"user:{user_id}:position:{symbol}:short:dca_count", 1)

                    tp_data_key = f"user:{user_id}:position:{symbol}:short:tp_data"
                    await redis.set(tp_data_key, json.dumps(position.tp_prices))
                    await record_trade_entry(
                        user_id=user_id,
                        symbol=symbol,
                        entry_price=position.entry_price,
                        current_price=current_price,
                        size=contracts_amount,  # 계약 수량 사용
                        side="short"
                    )
                    entry_success = True
                    await redis.delete(entry_fail_count_key)  # 성공시 카운트 리셋

                except Exception as e:
                    if "직전 주문 종료 후 쿨다운 시간이 지나지 않았습니다." in str(e):
                        pass
                    else:
                        error_msg = map_exchange_error(e)
                        error_logger.error("숏 포지션 진입 실패", exc_info=True)

                        # 진입 실패 시 카운트 증가
                        if not entry_success:
                            fail_count += 1
                            await redis.set(entry_fail_count_key, fail_count)
                            
                        await send_telegram_message(f"[{user_id}]⚠️ 숏 포지션 주문 실패\n"f"━━━━━━━━━━━━━━━\n"f"{error_msg}\n"f"재시도 횟수: {fail_count}/5",user_id, debug=True)
            elif rsi_signals['is_overbought'] and not trend_condition:
                alert_key = f"user:{user_id}:{symbol}:trend_signal_alert"
                is_alerted = await redis.get(alert_key)
                if not is_alerted:
                    await send_telegram_message(f"⚠️ 숏 포지션 진입 조건 불충족\n"f"━━━━━━━━━━━━━━━\n"f"RSI가 과매수 상태이지만 트랜드 조건이 맞지 않아 진입을 유보합니다.",user_id)
                    await redis.set(alert_key, "true", ex=7200)
                    logger.info(f"[{user_id}] 숏 포지션 진입 조건 불충족 알림 전송 완료. {symbol} {timeframe}")
            if fail_count >= 3:
                # 심볼별 상태 관리
                await redis.set(f"user:{user_id}:symbol:{symbol}:status", "stopped")
                await send_telegram_message(f"⚠️[{user_id}] {symbol} 상태를 Stopped로 강제 변경.5", user_id, debug=True)
                await send_telegram_message(f"트레이딩 자동 종료\n""─────────────────────\n"f"{symbol}: 3회 연속 진입 실패로 트레이딩이 종료되었습니다.",user_id, debug=True)
                await redis.delete(entry_fail_count_key)

    except Exception as e:
        import traceback
        error_msg = map_exchange_error(e)
        error_logger.error(f"[{user_id}]:포지션 진입 오류", exc_info=True)
        print(f"[{user_id}] ❌❌❌ EXCEPTION CAUGHT at line 508: {e}", flush=True)
        print(f"[{user_id}] Exception type: {type(e)}", flush=True)
        print(f"[{user_id}] Traceback:", flush=True)
        traceback.print_exc()
        await send_telegram_message(f"⚠️ 포지션 진입 오류:\n{error_msg}\n\nException: {e}", user_id, debug=True)
        
        

# ======== (B) 포지션이 있는 경우 ========
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
    이미 포지션이 있을 때:
    - DCA/피라미딩 추가 진입
    - TP/SL 모니터링
    - 브레이크이븐
    - 청산 조건
    """
    redis = await get_redis_client()

    korean_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    position_manager = PositionStateManager(trading_service)
    current_price = await get_current_price(symbol, timeframe)
    if side == "any":
        print("[⚠️] 포지션 방향이 없습니다. 포지션 방향을 찾아서 설정합니다.")
        main_position_direction_key = f"user:{user_id}:position:{symbol}:main_position_direction"
        side = await redis.get(main_position_direction_key)
        if side is None or side == "any":
            side = current_position.side
            await redis.set(main_position_direction_key, side)
    size = current_position.size
    entry_price = current_position.entry_price
    
    position_key = f"user:{user_id}:position:{symbol}:{side}"
    initial_position_size = await redis.hget(position_key, "initial_size")
    
    initial_investment = float(settings.get('investment', 0))
    if symbol == "BTC-USDT-SWAP":
        initial_investment = float(settings.get('btc_investment', 20))
    elif symbol == "ETH-USDT-SWAP":
        initial_investment = float(settings.get('eth_investment', 10))
    elif symbol == "SOL-USDT-SWAP":
        initial_investment = float(settings.get('sol_investment', 10))
    else:
        initial_investment = float(settings.get('investment', 0))
    
    if initial_position_size is None:
        initial_position_size = await redis.get(f"user:{user_id}:position:{symbol}:{side}:initial_size")
        if initial_position_size is None:
            try:
                # 초기 진입 로직 재사용하여 계약 정보 조회
                contract_info = await trading_service.get_contract_info(
            symbol=symbol,
            user_id=user_id,
                    size_usdt=initial_investment,
                    leverage=settings['leverage'],
                    current_price=current_price
                )
                # 실제 계약 수량 계산
                initial_position_size = contract_info['contracts_amount']
                # Redis에 저장
                await redis.set(f"user:{user_id}:position:{symbol}:{side}:initial_size", initial_position_size)
                await redis.hset(f"user:{user_id}:position:{symbol}:{side}", "initial_size", initial_position_size)
                print(f"[{user_id}] 초기 계약 수량 재계산 및 저장 완료: {initial_position_size}")
            except Exception as e:
                logger.error(f"초기 계약 수량 계산 실패: {str(e)}")
                initial_position_size = float(size)
                print(f"[{user_id}] 초기 계약 수량 계산 실패, 현재 크기로 대체: {initial_position_size}")
                await redis.set(f"user:{user_id}:position:{symbol}:{side}:initial_size", initial_position_size)
                await redis.hset(f"user:{user_id}:position:{symbol}:{side}", "initial_size", initial_position_size)
    use_dual_side_settings = await redis.hget(f"user:{user_id}:dual_side", "use_dual_side_entry")
    trend_close_enabled = await redis.hget(f"user:{user_id}:dual_side", "dual_side_trend_close")
    print(f"[{user_id}]시간:{korean_time} ✅포지션이 있는 경우. 평단 : {entry_price}, 포지션 수량(amount) : {size}, 포지션 방향 : {side}")
    tf_str = get_timeframe(timeframe)
    key = f"candles_with_indicators:{symbol}:{tf_str}"
    candle = await redis.lindex(key, -1)
    if candle:
        candle = json.loads(candle)
        atr_value = max(candle.get('atr14'), current_price*0.1*0.01)
    else:
        atr_value = current_price*0.01*0.1
        logger.error(f"캔들 데이터를 찾을 수 없습니다: {key}")
    trading_status = await redis.get(f"user:{user_id}:symbol:{symbol}:status")
    main_position_direction = await redis.get(f"user:{user_id}:position:{symbol}:main_position_direction")
    

    if not entry_price or not size:
        # 거래소 최신 정보로 재동기화
        exch_pos = await trading_service.get_current_position(user_id, symbol, side)
        if exch_pos is None:
            # mismatch => Redis 정리
            await position_manager.cleanup_position_data(user_id, symbol, side)
            await send_telegram_message(f"[{user_id}]❌ 포지션 정보 불일치: Redis 초기화", user_id, debug=True)
            return current_position
        else:
            entry_price = exch_pos.entry_price
            size = exch_pos.size
            await position_manager.update_position_state(user_id, symbol, entry_price, size, side, operation_type="add_position")
            print("포지션 정보 동기화 완료")
            
    pyramiding_limit = settings.get('pyramiding_limit', 1)
    use_check_DCA_with_price = settings.get('use_check_DCA_with_price', True)
    #print(f"pyramiding limit", pyramiding_limit)
     # ─── (1) DCA/피라미딩 추가 진입  ─────────────────────────
    cooldown_key = f"user:{user_id}:cooldown:{symbol}:{side}"
    is_cooldown = await redis.get(cooldown_key)
    left_time = await redis.ttl(cooldown_key)
    tf_str = get_timeframe(timeframe)
    timeframe_lock_key = f"user:{user_id}:position_lock:{symbol}:{side}:{tf_str}"
    is_locked = await redis.exists(timeframe_lock_key)
    if is_locked:
        remaining_time = await redis.ttl(timeframe_lock_key)
        logger.info(f"[{user_id}] 포지션 {symbol}의 {side}방향 진입 잠금 중입니다. 남은 시간: {remaining_time}s")
        return current_position  # 잠금이 있으면 포지션을 열지 않고 리턴
    if is_cooldown:
        print(f"[{user_id}] 쿨다운 중입니다. {symbol}의 {side}방향 종목에 대해서는 진입을 하지 않습니다. 남은 시간: {left_time}초")
        return current_position
    if pyramiding_limit > 1:
        position_key = f"user:{user_id}:position:{symbol}:{side}"
        position_info = await redis.hgetall(position_key)
        # DCA 레벨 가져오기 또는 새로 계산
        dca_key = f"user:{user_id}:position:{symbol}:{side}:dca_levels"
        dca_levels = await redis.lrange(dca_key, 0, -1)
        
        if True : #not dca_levels:  # DCA 레벨이 없으면 새로 계산 <-- 항상 계산이 되어야 맞다. 
            entry_price = position_info.get('entry_price', str(current_price))
            # 'None' 문자열인 경우 current_price를 사용
            if entry_price == 'None' or entry_price == None:
                initial_entry_price = float(current_price)
            else:
                initial_entry_price = float(entry_price)
            
            last_filled_price_raw = position_info.get('last_filled_price', str(initial_entry_price))
            if last_filled_price_raw == 'None' or last_filled_price_raw == None:
                last_filled_price = float(initial_entry_price)
            else:
                last_filled_price = float(last_filled_price_raw)
            
            print(f"1. [{user_id}] initial_entry_price : {initial_entry_price}, last_filled_price : {last_filled_price}")
            dca_levels = await calculate_dca_levels(initial_entry_price, last_filled_price, settings, side, atr_value, current_price, user_id)
            await update_dca_levels_redis(user_id, symbol, dca_levels, side)

        dca_levels = await redis.lrange(dca_key, 0, -1)
        current_price = float(current_price)
        # 첫 번째 DCA 레벨이 있는 경우에만 진행
        if dca_levels and len(dca_levels) > 0:
            first_dca_level = float(dca_levels[0])  # 첫 번째 DCA 레벨
            # DCA 조건 체크 (롱/숏에 따라 다른 조건 적용)
            if use_check_DCA_with_price:
                dca_condition = (current_price <= first_dca_level if side == "long" 
                                else current_price >= first_dca_level)
            else:
                dca_condition = True
            print(f"[{user_id}] Current Price: {current_price}, First DCA Level: {first_dca_level}, Side: {side}, DCA Condition: {dca_condition}")

        check_dca_condition_result = await check_dca_condition(current_price, dca_levels, side, use_check_DCA_with_price)
        if check_dca_condition_result:
            dca_order_count_key = f"user:{user_id}:position:{symbol}:{side}:dca_count"
            dca_order_count = await redis.get(dca_order_count_key)
            print(f"[{user_id}] dca_order_count: {dca_order_count}")
            if dca_order_count is None:
                dca_order_count = 1
                await redis.set(dca_order_count_key, 1)
            else:
                dca_order_count = int(dca_order_count)
            use_trailing_stop = settings.get('trailing_stop_active', False)
            trailing_start_point = settings.get('trailing_start_point', 'tp3')
            position_key = f"user:{user_id}:position:{symbol}:{side}"
            position_info = await redis.hgetall(position_key)
            position_size = float(position_info.get('size', 0))
            entry_price = float(position_info.get('entry_price', current_price))
            last_entry_size = float(position_info.get('last_entry_size', 0))
            if last_entry_size == 0 and dca_order_count > 1:
                # 백업 계산: initial_size * (dca_count - 1) * multiplier
                try:
                    initial_size = float(position_info.get('initial_size', 0))
                    if initial_size == 0:
                        initial_size_str = await redis.get(f"user:{user_id}:position:{symbol}:{side}:initial_size")
                        if initial_size_str is None:
                            initial_size = 0
                        else:
                            initial_size = float(initial_size_str)
                except Exception as e:
                    initial_size = 0
                    await send_telegram_message(f"[{user_id}] initial_size가 없습니다. 초기화 중입니다. 오류를 확인해주세요", user_id, debug=True)
                    
                scale = settings.get('entry_multiplier', 0.5)
                if initial_size > 0:
                    calculated_last_entry_size = initial_size * (scale ** (dca_order_count - 1))
                    last_entry_size = calculated_last_entry_size
                    await redis.hset(position_key, "last_entry_size", str(calculated_last_entry_size))
                    await send_telegram_message(f"[{user_id}] last_entry_size가 0이어서 재계산했습니다: {calculated_last_entry_size}", user_id, debug=True)
                else:
                    await send_telegram_message(f"[{user_id}] last_entry_size가 0이고 initial_size도 없습니다. 초기화 중입니다. 오류를 확인해주세요", user_id, debug=True)
                    return current_position
            scale = settings.get('entry_multiplier', 0.5)
            manual_calculated_initial_size: float = 0.0

            try:
                investment = 0.0
                if symbol == "BTC-USDT-SWAP":
                    investment = settings['btc_investment']
                elif symbol == "SOL-USDT-SWAP":
                    investment = settings['sol_investment']
                elif symbol == "ETH-USDT-SWAP":
                    investment = settings['eth_investment']
                else:
                    investment = settings['investment']

                new_investment = float(investment) * (scale ** dca_order_count)
                # 계약 정보 조회
                contract_info = await trading_service.get_contract_info(
            symbol=symbol,
            user_id=user_id,
                    size_usdt=new_investment,
                    leverage=settings['leverage'],
                    current_price=current_price
                )
                # 실제 계약 수량 계산
                new_entry_contracts_amount = contract_info['contracts_amount']  # 이미 최소 주문 수량 등이 고려된 값
            except Exception as e:

                print(f"[{user_id}] scale : {scale}")
                manual_calculated_initial_size_raw = await redis.get(f"user:{user_id}:position:{symbol}:{side}:initial_size")

                if dca_order_count == 1:
                    manual_calculated_initial_size = float(position_size)
                elif dca_order_count > 1:
                    # Check if manual_calculated_initial_size_raw is valid
                    if manual_calculated_initial_size_raw is None or manual_calculated_initial_size_raw == "None" or manual_calculated_initial_size_raw == "0":
                        manual_calculated_initial_size = float(position_size) / float(dca_order_count)
                    else:
                        try:
                            manual_calculated_initial_size = float(manual_calculated_initial_size_raw)
                            if manual_calculated_initial_size == 0:
                                manual_calculated_initial_size = float(position_size) / float(dca_order_count)
                        except (ValueError, TypeError):
                            manual_calculated_initial_size = float(position_size) / float(dca_order_count)
                new_entry_contracts_amount = float(manual_calculated_initial_size) * float(scale) * float(dca_order_count)
                await send_telegram_message(f"⛔️[{user_id}] : 뭔가 이상한 상황! 초기진입사이즈 : {manual_calculated_initial_size}, 배율 : {scale}, DCA횟수 : {dca_order_count}, 총 진입사이즈 : {new_entry_contracts_amount}", user_id, debug=True)


                
            

            initial_size = float(position_info.get('initial_size', manual_calculated_initial_size))
            # 초기진입 진입 크기를 기준으로 DCA 진입 크기 계산
            

            new_position_entry_contract_size = new_entry_contracts_amount
            if new_entry_contracts_amount == 0 or new_entry_contracts_amount is None:
                new_position_entry_contract_size = float(last_entry_size*scale)
            logger.info(f"[{user_id}] new_position_entry_contract_size : {new_position_entry_contract_size}, initial_size : {initial_size}, scale : {scale}")
            if side == "long":
                should_check_trend = settings.get('use_trend_logic', True)
                trend_condition = True
                if should_check_trend and current_state == -2:
                    trend_condition = False
                    
                rsi_long_signals_condition = False
                if settings.get('use_rsi_with_pyramiding', True):
                    rsi_long_signals_condition = rsi_signals['is_oversold']
                else:
                    rsi_long_signals_condition = True
                print(f"[{user_id}] rsi_signals['is_oversold'] : {rsi_signals['is_oversold']}, trend_condition : {trend_condition}, dca_order_count : {dca_order_count}, pyramiding_limit : {settings.get('pyramiding_limit', 1)}")
                if dca_order_count + 1 <= settings.get('pyramiding_limit', 1) and rsi_long_signals_condition:
                    if (trend_condition):
                        try:
                            print("3번")
                                        
            
                            new_position_entry_qty = await trading_service.contract_size_to_qty(user_id, symbol, new_position_entry_contract_size)
                            initial_entry_qty = await trading_service.contract_size_to_qty(user_id, symbol, initial_size)
                            await send_telegram_message(f"[{user_id}] 새로진입크기 : {new_position_entry_qty}, 초기진입사이즈 : {initial_entry_qty}, 배율 : {scale}, DCA횟수 : {dca_order_count}\n USDT계산 : {float(new_position_entry_qty) * current_price:,.2f}USDT", user_id, debug=True)
                            logger.info(f"[{user_id}] new_position_entry_qty : {new_position_entry_contract_size}")
                            request = OpenPositionRequest(
                                user_id=user_id,
                                symbol=symbol,
                                direction="long",
                                size=new_position_entry_contract_size,
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
                                position = await open_position_endpoint(request)
                                
                                # 포지션이 실제로 성공적으로 열렸는지 확인
                                if position is None:
                                    logger.warning(f"[{user_id}] DCA 롱 포지션 생성 실패 - position이 None")
                                    raise ValueError(f"DCA 포지션 생성 실패: position 객체가 None입니다")
                                
                                # 포지션 크기가 유효한지 확인
                                if not hasattr(position, 'size') or position.size <= 0:
                                    logger.warning(f"[{user_id}] DCA 롱 포지션 생성 실패 - 유효하지 않은 포지션 크기")
                                    raise ValueError(f"DCA 포지션 생성 실패: 유효하지 않은 포지션 크기 ({getattr(position, 'size', None)})")
                                
                                # 실제 진입 가격이 있는지 확인
                                if not hasattr(position, 'entry_price') or position.entry_price <= 0:
                                    logger.warning(f"[{user_id}] DCA 롱 포지션 생성 실패 - 유효하지 않은 진입 가격")
                                    raise ValueError(f"DCA 포지션 생성 실패: 유효하지 않은 진입 가격 ({getattr(position, 'entry_price', None)})")
                                
                                # margin_blocked 상태인 경우 DCA 카운트를 증가시키지 않음
                                if hasattr(position, 'order_id') and position.order_id == "margin_blocked":
                                    logger.warning(f"[{user_id}] {symbol} long 포지션 DCA 주문이 거부되어 카운트를 증가시키지 않습니다. order_id: {position.order_id}")
                                    raise ValueError(f"DCA 포지션 생성 실패: 마진이 부족합니다 (margin_blocked)")
                                
                                # 포지션이 성공적으로 열렸으므로 DCA 카운트 증가
                                dca_count_key = f"user:{user_id}:position:{symbol}:long:dca_count"
                                dca_order_count = await redis.get(dca_count_key)
                                dca_order_count = int(dca_order_count) + 1
                                await redis.set(dca_count_key, dca_order_count)
                                
                                # last_entry_size 업데이트
                                await redis.hset(f"user:{user_id}:position:{symbol}:long", "last_entry_size", new_position_entry_contract_size)
                                
                            except Exception as e:
                                error_logger.error(f"[{user_id}]:DCA 롱 주문 실패", exc_info=True)
                                await send_telegram_message(f"⚠️ DCA 추가진입 실패 (롱)\n"f"━━━━━━━━━━━━━━━\n"f"{e}\n", okx_uid=user_id,debug=True)
                                
                                
                                next_candle_time = await calculate_next_candle_time(timeframe)
                                tf_str = get_timeframe(timeframe)
                                timeframe_lock_key = f"user:{user_id}:position_lock:{symbol}:long:{tf_str}"
                                # 다음 캔들 시작 시간까지 잠금 설정 (expire time은 초 단위)
                                current_time = int(datetime.now().timestamp())
                                expire_seconds = next_candle_time - current_time
                                if expire_seconds > 0:
                                    await redis.set(timeframe_lock_key, "locked", ex=expire_seconds)
                                    logger.info(f"[{user_id}] 포지션 진입 후 숏 포지션 잠금 설정 완료. {symbol} {timeframe} until next candle at {next_candle_time}")
                                else:
                                    logger.info(f"Next candle time is in the past for user {user_id} on {symbol} with timeframe {timeframe}")

                                return current_position
                            
                            dca_key = f"user:{user_id}:position:{symbol}:long:dca_levels"
                            new_entry_price = position.entry_price
                            try:
                                new_position_contract_size = position.size
                                new_position_qty = await trading_service.contract_size_to_qty(user_id, symbol, new_position_contract_size)
                            except Exception as e:
                                send_telegram_message(f"롱 추가진입 실패 오류: {e}", user_id, debug=True)
                                print("롱 추가진입 실패 오류: ", e)
                                return current_position
                            new_avg, new_size = await position_manager.update_position_state(user_id, symbol, current_price, contracts_amount_delta=new_position_contract_size, position_qty_delta=new_position_qty, side = "long", operation_type="add_position", new_entry_exact_price=new_entry_price, new_exact_contract_size=new_position_contract_size)
                            new_total_position_qty = await trading_service.contract_size_to_qty(user_id, symbol, new_position_contract_size)
                            print("총 포지션 수량 제대로 나오는지 꼭 확인!~!!!!!1", new_total_position_qty)
                            
                            new_position_qty_size_from_redis = await redis.hget(f"user:{user_id}:position:{symbol}:long", "position_qty")
                            position_avg_price = await trading_service.get_position_avg_price(user_id, symbol, side)
                            tp_prices = await redis.hget(f"user:{user_id}:position:{symbol}:long", "tp_prices")
                            use_tp1 = settings.get('use_tp1', True)
                            use_tp2 = settings.get('use_tp2', True)
                            use_tp3 = settings.get('use_tp3', True)
                            # TP 가격 문자열 처리
                            tp_prices_str = ""
                            if tp_prices:
                                try:
                                    if tp_prices.startswith('[') and tp_prices.endswith(']'):
                                        # JSON 형식인 경우 (리스트 형태)
                                        tp_list = json.loads(tp_prices)
                                        if tp_list and len(tp_list) > 0:
                                            tp_prices_str = "\n🎯 목표가격\n"
                                            if use_tp1  :
                                                tp_prices_str += f"TP1: {float(tp_list[0]):,.2f} $"
                                            if len(tp_list) > 1 and use_tp2 and not ((trailing_start_point == 'tp1') and use_trailing_stop) :
                                                tp_prices_str += f"\nTP2: {float(tp_list[1]):,.2f} $"
                                            if len(tp_list) > 2 and use_tp3 and not ((trailing_start_point == 'tp1' or trailing_start_point == 'tp2') and use_trailing_stop) :
                                                tp_prices_str += f"\nTP3: {float(tp_list[2]):,.2f} $"
                                    else:
                                        # 쉼표로 구분된 문자열인 경우
                                        tp_list = tp_prices.split(',')
                                        if tp_list and len(tp_list) > 0:
                                            tp_prices_str = "\n🎯 목표가격\n"
                                            if use_tp1:
                                                tp_prices_str += f"TP1: {float(tp_list[0]):,.2f} $"
                                            if len(tp_list) > 1 and use_tp2 and not ((trailing_start_point == 'tp1') and use_trailing_stop) :
                                                tp_prices_str += f"\nTP2: {float(tp_list[1]):,.2f} $"
                                            if len(tp_list) > 2 and use_tp3 and not ((trailing_start_point == 'tp1' or trailing_start_point == 'tp2') and use_trailing_stop) :
                                                tp_prices_str += f"\nTP3: {float(tp_list[2]):,.2f} $"
                                except (json.JSONDecodeError, ValueError) as e:
                                    logger.error(f"TP 가격 파싱 오류: {e}")
                                    tp_prices_str = f"원본 데이터: {tp_prices}"

                            # 다음 DCA 진입 가능 레벨 정보 가져오기
                            next_dca_level_str = ""
                            dca_levels_key = f"user:{user_id}:position:{symbol}:long:dca_levels"
                            dca_levels = await redis.lrange(dca_levels_key, 0, 0)  # 첫 번째 값만 가져오기
                            if dca_levels and len(dca_levels) > 0:
                                try:
                                    next_dca_level = float(dca_levels[0])
                                    next_dca_level_str = f"다음 진입가능 가격: {next_dca_level:,.2f}"
                                except ValueError as e:
                                    logger.error(f"DCA 레벨 파싱 오류: {e}")

                            telegram_message = "🔼 추가진입 (롱)"
                            telegram_message += "━━━━━━━━━━━━━━━\n"
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
                            telegram_message += "━━━━━━━━━━━━━━━"
                            asyncio.create_task(send_telegram_message(telegram_message, user_id))
                            try:
                                await record_trade_entry(
                                    user_id=user_id,
                                    symbol=symbol,
                                    entry_price=current_price,
                                    current_price=current_price,
                                    size=new_position_contract_size,
                                    side="long",
                                    is_DCA=True,  # DCA 여부 표시
                                    dca_count=dca_order_count
                                )
                                                    #포지션 진입 후, 강제로, 해당 타임프레임이 끝날 때까지는 최소한 진입하지 않도록 레디스 키 설정
                                next_candle_time = await calculate_next_candle_time(timeframe)
                                tf_str = get_timeframe(timeframe)
                                timeframe_lock_key = f"user:{user_id}:position_lock:{symbol}:long:{tf_str}"
                                # 다음 캔들 시작 시간까지 잠금 설정 (expire time은 초 단위)
                                current_time = int(datetime.now().timestamp())
                                expire_seconds = next_candle_time - current_time
                                if expire_seconds > 0:
                                    await redis.set(timeframe_lock_key, "locked", ex=expire_seconds)
                                    logger.info(f"[{user_id}] 포지션 진입 후 롱 포지션 잠금 설정 완료2. {symbol} {timeframe} until next candle at {next_candle_time}")
                                else:
                                    logger.info(f"Next candle time is in the past for user {user_id} on {symbol} with timeframe {timeframe}")
                        
                            except Exception as e:
                                error_logger.error(f"[{user_id}]:롱 주문 실패", exc_info=True)
                                await send_telegram_message(f"⚠️ 추가진입 로깅 실패 (롱)\n"f"━━━━━━━━━━━━━━━\n"f"{e}\n", okx_uid=user_id,debug=True)
                            print("😍😍use dual side entry : ", use_dual_side_settings)
                            if use_dual_side_settings:
                                print("😍4번")
                                print("="*100)
                                try:
                                    await manage_dual_side_entry(
                                        user_id=user_id,
                                        symbol=symbol,
                                        current_price=current_price,
                                        dca_order_count=dca_order_count,
                                        main_position_side=side,
                                        settings=settings,
                                        trading_service=trading_service,
                                        exchange=trading_service.client
                                        )
                                except Exception as e:
                                    error_logger.error(f"[{user_id}]:양방향 롱 진입 실패", exc_info=True)
                                    await send_telegram_message(f"⚠️ 추가진입 실패 (롱)\n"f"━━━━━━━━━━━━━━━\n"f"{e}\n", okx_uid=user_id,debug=True)
                                await record_trade_entry(
                                    user_id=user_id,
                                    symbol=symbol,
                                    entry_price=current_price,
                                    current_price=current_price,
                                    size=new_position_contract_size,
                                    side=side,
                                    is_DCA=True,  # DCA 여부 표시
                                    dca_count=dca_order_count
                                )
                        except Exception as e:
                            error_msg = map_exchange_error(e)
                            error_logger.error(f"[{user_id}]:롱 주문 실패", exc_info=True)
                            #await send_telegram_message(
                            #    f"⚠️ 추가진입 실패 (롱)\n"
                            #    f"━━━━━━━━━━━━━━━\n"
                            #    f"현재가격: {current_price}\n"
                            #    f"시도한 추가물량: {new_position_qty}",
                            #    user_id
                            #)
                            await send_telegram_message(f"⚠️[{user_id}] 추가진입 실패 (롱)\n"f"━━━━━━━━━━━━━━━\n"f"{error_msg}\n"f"현재가격: {current_price}\n"f"시도한 추가물량: {new_position_qty}\n"f"시도한 추가 계약: {new_position_contract_size}",user_id, debug=True)
                    else:
                        print("하락 트랜드이므로 추가 진입을 하지 않습니다.")
                        alert_key = f"user:{user_id}:{symbol}:trend_signal_alert"
                        is_alerted = await redis.get(alert_key)
                        if not is_alerted:
                            await send_telegram_message(f"⚠️ 롱 추가진입 진입 조건 불충족\n"f"━━━━━━━━━━━━━━━\n"f"추가 진입 조건에는 부합하지만 트랜드 조건이 맞지 않아 진입을 유보합니다.",user_id)
                            await redis.set(alert_key, "true", ex=7200)
                            next_candle_time = await calculate_next_candle_time(timeframe)
                            tf_str = get_timeframe(timeframe)
                            timeframe_lock_key = f"user:{user_id}:position_lock:{symbol}:long:{tf_str}"
                            # 다음 캔들 시작 시간까지 잠금 설정 (expire time은 초 단위)
                            current_time = int(datetime.now().timestamp())
                            expire_seconds = next_candle_time - current_time
                            if expire_seconds > 0:
                                await redis.set(timeframe_lock_key, "locked", ex=expire_seconds)
                                logger.info(f"[{user_id}] 포지션 진입 후 롱 포지션 잠금 설정 완료. {symbol} {timeframe} until next candle at {next_candle_time}")
                            else:
                                logger.info(f"Next candle time is in the past for user {user_id} on {symbol} with timeframe {timeframe}")
                        

                    
            elif side == "short":
                should_check_trend = settings.get('use_trend_logic', True)
                trend_condition = True
                if should_check_trend and current_state == 2:
                    trend_condition = False
                rsi_short_signals_condition = False
                if settings.get('use_rsi_with_pyramiding', True):
                    rsi_short_signals_condition = rsi_signals['is_overbought']
                else:
                    rsi_short_signals_condition = True
                print(f"[{user_id}] rsi short signals condition : {rsi_short_signals_condition}, trend_condition : {trend_condition}, dca_order_count : {dca_order_count}, new_size : {new_position_entry_contract_size}")
                if (rsi_short_signals_condition and trend_condition) and dca_order_count + 1 <= settings.get('pyramiding_limit', 1):
                    print("피라미딩 숏 진입 호출")
                    try:

                        request = OpenPositionRequest(
                            user_id=user_id,
                            symbol=symbol,
                            direction="short",
                            size=new_position_entry_contract_size,
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
                            position = await open_position_endpoint(request)
                            
                            # 포지션이 실제로 성공적으로 열렸는지 확인
                            if position is None:
                                logger.warning(f"[{user_id}] DCA 숏 포지션 생성 실패 - position이 None")
                                raise ValueError(f"DCA 포지션 생성 실패: position 객체가 None입니다")
                            
                            # 포지션 크기가 유효한지 확인
                            if not hasattr(position, 'size') or position.size <= 0:
                                logger.warning(f"[{user_id}] DCA 숏 포지션 생성 실패 - 유효하지 않은 포지션 크기")
                                raise ValueError(f"DCA 포지션 생성 실패: 유효하지 않은 포지션 크기 ({getattr(position, 'size', None)})")
                            
                            # 실제 진입 가격이 있는지 확인
                            if not hasattr(position, 'entry_price') or position.entry_price <= 0:
                                logger.warning(f"[{user_id}] DCA 숏 포지션 생성 실패 - 유효하지 않은 진입 가격")
                                raise ValueError(f"DCA 포지션 생성 실패: 유효하지 않은 진입 가격 ({getattr(position, 'entry_price', None)})")
                            
                            # margin_blocked 상태인 경우 DCA 카운트를 증가시키지 않음
                            if hasattr(position, 'order_id') and position.order_id == "margin_blocked":
                                logger.warning(f"[{user_id}] {symbol} short 포지션 DCA 주문이 거부되어 카운트를 증가시키지 않습니다. order_id: {position.order_id}")
                                raise ValueError(f"DCA 포지션 생성 실패: 마진이 부족합니다 (margin_blocked)")
                            
                            # 포지션이 성공적으로 열렸으므로 DCA 카운트 증가
                            dca_count_key = f"user:{user_id}:position:{symbol}:short:dca_count"
                            dca_order_count = await redis.get(dca_count_key)
                            dca_order_count = int(dca_order_count) + 1
                            await redis.set(dca_count_key, dca_order_count)

                            #포지션 진입 후, 강제로, 해당 타임프레임이 끝날 때까지는 최소한 진입하지 않도록 레디스 키 설정
                            next_candle_time = await calculate_next_candle_time(timeframe)
                            tf_str = get_timeframe(timeframe)
                            timeframe_lock_key = f"user:{user_id}:position_lock:{symbol}:short:{tf_str}"
                            # 다음 캔들 시작 시간까지 잠금 설정 (expire time은 초 단위)
                            current_time = int(datetime.now().timestamp())
                            expire_seconds = next_candle_time - current_time
                            if expire_seconds > 0:
                                await redis.set(timeframe_lock_key, "locked", ex=expire_seconds)
                                logger.info(f"[{user_id}] 포지션 {symbol}의 {side}방향 진입 잠금을 설정했습니다. 남은 시간: {expire_seconds}s")

                            await redis.hset(f"user:{user_id}:position:{symbol}:short", "last_entry_size", new_position_entry_contract_size)
                        except Exception as e:
                            error_logger.error(f"[{user_id}]:DCA 숏 주문 실패1", exc_info=True)
                            await send_telegram_message(f"⚠️ 추가진입 실패 (숏)\n"f"━━━━━━━━━━━━━━━\n"f"{e}\n", okx_uid=user_id,debug=True)
                                                    #포지션 진입 후, 강제로, 해당 타임프레임이 끝날 때까지는 최소한 진입하지 않도록 레디스 키 설정
                            next_candle_time = await calculate_next_candle_time(timeframe)
                            tf_str = get_timeframe(timeframe)
                            timeframe_lock_key = f"user:{user_id}:position_lock:{symbol}:short:{tf_str}"
                            # 다음 캔들 시작 시간까지 잠금 설정 (expire time은 초 단위)
                            current_time = int(datetime.now().timestamp())
                            expire_seconds = next_candle_time - current_time
                            if expire_seconds > 0:
                                await redis.set(timeframe_lock_key, "locked", ex=expire_seconds)
                                logger.info(f"[{user_id}] 포지션 {symbol}의 {side}방향 진입 잠금을 설정했습니다. 남은 시간: {expire_seconds}s")

                            await redis.hset(f"user:{user_id}:position:{symbol}:short", "last_entry_size", new_position_entry_contract_size)

                            return current_position
                        if use_dual_side_settings:
                            print("😍4번")
                            print("="*100)
                            try:
                                await manage_dual_side_entry(
                                    
                                    user_id=user_id,
                                    symbol=symbol,
                                    current_price=current_price,
                                    dca_order_count=dca_order_count,
                                    main_position_side=side,
                                    settings=settings,
                                    trading_service=trading_service,
                                    exchange=trading_service.client
                                    )
                            except Exception as e:
                                error_logger.error(f"[{user_id}]: 양방향 숏 진입 실패 ", exc_info=True)
                                await send_telegram_message(f"⚠️ 추가진입 실패 (숏)\n"f"━━━━━━━━━━━━━━━\n"f"{e}\n", okx_uid=user_id,debug=True)
                        dca_key = f"user:{user_id}:position:{symbol}:short:dca_levels"
                        await redis.lpop(dca_key)
                        new_entry_price = position.entry_price
                        try:
                            new_total_contract_size = position.size
                            new_position_contract_size = position.size
                            new_position_qty = await trading_service.contract_size_to_qty(user_id, symbol, new_position_entry_contract_size)
                        except Exception as e:
                            send_telegram_message(f"숏 추가진입 실패 오류: {e}", user_id, debug=True)
                            print("숏 추가진입 실패 오류: ", e)
                            return current_position
                        
                        
                        new_total_position_qty = await trading_service.contract_size_to_qty(user_id, symbol, new_total_contract_size)
                        await position_manager.update_position_state(user_id, symbol, current_price, contracts_amount_delta=new_position_entry_contract_size, position_qty_delta=new_position_qty, side = "short", operation_type="add_position", new_entry_exact_price=new_entry_price, new_exact_contract_size=new_total_contract_size)
                        
                        initial_entry_qty = await trading_service.contract_size_to_qty(user_id, symbol, initial_size)
                        new_position_entry_qty = await trading_service.contract_size_to_qty(user_id, symbol, new_position_entry_contract_size)
                        await send_telegram_message(f"[{user_id}] 새로진입크기 : {new_position_entry_qty}, 초기진입사이즈 : {initial_entry_qty}, 배율 : {scale}, DCA횟수 : {dca_order_count}\n USDT계산 : {float(new_position_entry_qty) * current_price:,.2f}USDT", user_id, debug=True)
                        
                        await record_trade_entry(
                                user_id=user_id,
                                symbol=symbol,
                                entry_price=current_price,
                                current_price=current_price,
                                size=new_position_contract_size,
                                side=side,
                                is_DCA=True,  # DCA 여부 표시
                                dca_count=dca_order_count 
                            )             
                        total_position_qty = await redis.hget(f"user:{user_id}:position:{symbol}:{side}", "position_qty")
                        position_avg_price = await trading_service.get_position_avg_price(user_id, symbol, side)
                        
                        # TP 가격 문자열 처리
                        tp_prices = await redis.hget(f"user:{user_id}:position:{symbol}:short", "tp_prices")
                        use_tp1 = settings.get('use_tp1', True)
                        use_tp2 = settings.get('use_tp2', True) and not (settings.get('trailing_stop_active', False) and (settings.get('trailing_start_point', 'tp3') == 'tp1'))
                        use_tp3 = settings.get('use_tp3', True) and not (settings.get('trailing_stop_active', False) and (settings.get('trailing_start_point', 'tp3') == 'tp1') or settings.get('trailing_start_point', 'tp3') == 'tp2')
                        tp_prices_str = ""
                        if tp_prices:
                            try:
                                if tp_prices.startswith('[') and tp_prices.endswith(']'):
                                    # JSON 형식인 경우 (리스트 형태)
                                    tp_list = json.loads(tp_prices)
                                    if tp_list and len(tp_list) > 0:
                                        tp_prices_str = "\n🎯 목표가격\n"
                                        if use_tp1:
                                            tp_prices_str += f"TP1: {float(tp_list[0]):,.2f} $"
                                        if len(tp_list) > 1 and use_tp2:
                                            tp_prices_str += f"\nTP2: {float(tp_list[1]):,.2f} $"
                                        if len(tp_list) > 2 and use_tp3:
                                            tp_prices_str += f"\nTP3: {float(tp_list[2]):,.2f} $"
                                else:
                                    # 쉼표로 구분된 문자열인 경우
                                    tp_list = tp_prices.split(',')
                                    if tp_list and len(tp_list) > 0:
                                        tp_prices_str = "\n🎯 목표가격\n"
                                        if use_tp1:
                                            tp_prices_str += f"TP1: {float(tp_list[0]):,.2f} $"
                                        if len(tp_list) > 1 and use_tp2:
                                            tp_prices_str += f"\nTP2: {float(tp_list[1]):,.2f} $"
                                        if len(tp_list) > 2 and use_tp3:
                                            tp_prices_str += f"\nTP3: {float(tp_list[2]):,.2f} $"
                            except (json.JSONDecodeError, ValueError) as e:
                                logger.error(f"TP 가격 파싱 오류: {e}")
                                tp_prices_str = f"원본 데이터: {tp_prices}"
                        
                        # 다음 DCA 진입 가능 레벨 정보 가져오기
                        next_dca_level_str = ""
                        dca_levels_key = f"user:{user_id}:position:{symbol}:short:dca_levels"
                        dca_levels = await redis.lrange(dca_levels_key, 0, 0)  # 첫 번째 값만 가져오기
                        print(f"[{user_id}] DCA 레벨 키: {dca_levels_key}")
                        print(f"[{user_id}] DCA 레벨 값: {dca_levels}")
                        entry_price = position_info.get('entry_price', str(current_price))
                        # DCA 레벨이 비어있으면 재계산
                        if not dca_levels or len(dca_levels) == 0:
                            print(f"[{user_id}] DCA 레벨이 비어있어 재계산을 시도합니다.")
                            try:
                                position_key = f"user:{user_id}:position:{symbol}:short"
                                position_info = await redis.hgetall(position_key)
                                entry_price = position_info.get('entry_price', str(current_price))
                                # 'None' 문자열인 경우 current_price를 사용
                                if entry_price == 'None' or entry_price == None:
                                    initial_entry_price = float(current_price)
                                else:
                                    initial_entry_price = float(entry_price)
                                
                                last_filled_price_raw = position_info.get('last_filled_price', str(initial_entry_price))
                                if last_filled_price_raw == 'None' or last_filled_price_raw == None:
                                    last_filled_price = float(initial_entry_price)
                                else:
                                    last_filled_price = float(last_filled_price_raw)
                                
                                print(f"2. [{user_id}][{symbol}] initial_entry_price : {initial_entry_price}, last_filled_price : {last_filled_price}")
                                dca_levels = await calculate_dca_levels(
                                    initial_entry_price, 
                                    last_filled_price, 
                                    settings, 
                                    "short", 
                                    atr_value, 
                                    current_price, 
                                    user_id
                                )
                                await update_dca_levels_redis(user_id, symbol, dca_levels, "short")
                                print(f"[{user_id}][{symbol}] DCA 레벨 재계산 완료: {dca_levels}")
                            except Exception as e:
                                print(f"[{user_id}][{symbol}] DCA 레벨 재계산 실패: {e}")
                                logger.error(f"DCA 레벨 재계산 실패: {e}")
                        
                        if dca_levels and len(dca_levels) > 0:
                            try:
                                next_dca_level = float(dca_levels[0])
                                next_dca_level_str = f"다음 진입가능 가격: {next_dca_level:,.2f}"
                                print(f"[{user_id}][{symbol}] 다음 DCA 레벨 문자열: {next_dca_level_str}")
                            except ValueError as e:
                                logger.error(f"DCA 레벨 파싱 오류: {e}")
                                print(f"[{user_id}][{symbol}] DCA 레벨 파싱 오류: {e}")
                        
                        telegram_message = "🔽 추가진입 (숏)"
                        telegram_message += "━━━━━━━━━━━━━━━\n"
                        telegram_message += f"[{symbol}]\n"
                        telegram_message += f"📊 숏 {dca_order_count}회차 진입\n\n"
                        telegram_message += f"💲 진입 가격 : {current_price:,.2f}\n"
                        telegram_message += f"📈 수량: +{new_position_qty}\n"
                        telegram_message += f"(USDT 기준 : {float(new_position_qty) * current_price:,.2f}USDT)\n"
                        telegram_message += f"💰 새 평균가: {position_avg_price:,.2f}\n"
                        telegram_message += f"📝 총 포지션: {float(total_position_qty):.3f}\n"
                        if tp_prices_str :
                            telegram_message += f"\n{tp_prices_str}\n"
                        if next_dca_level_str != "":
                            telegram_message += f"\n📍 {next_dca_level_str}\n"
                        else:
                            print("next_dca_level_str 없음!!")
                        telegram_message += "━━━━━━━━━━━━━━━"
                        await send_telegram_message(telegram_message, user_id)
                    except Exception as e:
                        error_msg = map_exchange_error(e)
                        error_logger.error(f"[{user_id}]:DCA 숏 주문 실패3", exc_info=True)
                        await send_telegram_message(f"숏 주문 실패(숏)\n"f"━━━━━━━━━━━━━━━\n"f"현재가격: {current_price}\n"f"시도한 추가물량: {new_position_qty}",user_id                        )
                        await send_telegram_message(f"⚠️ 추가진입 실패 (숏)\n"f"━━━━━━━━━━━━━━━\n"f"{error_msg}\n"f"현재가격: {current_price}\n"f"시도한 추가물량: {new_position_qty}\n"f"시도한 추가 계약: {new_position_contract_size}",user_id, debug=True)
                                                    #포지션 진입 후, 강제로, 해당 타임프레임이 끝날 때까지는 최소한 진입하지 않도록 레디스 키 설정
                        next_candle_time = await calculate_next_candle_time(timeframe)
                        tf_str = get_timeframe(timeframe)
                        timeframe_lock_key = f"user:{user_id}:position_lock:{symbol}:short:{tf_str}"
                        # 다음 캔들 시작 시간까지 잠금 설정 (expire time은 초 단위)
                        current_time = int(datetime.now().timestamp())
                        expire_seconds = next_candle_time - current_time
                        if expire_seconds > 0:
                            await redis.set(timeframe_lock_key, "locked", ex=expire_seconds)
                            logger.info(f"[{user_id}] 포지션 {symbol}의 {side}방향 진입 잠금을 설정했습니다. 남은 시간: {expire_seconds}s")
                        await redis.hset(f"user:{user_id}:position:{symbol}:short", "last_entry_size", new_position_entry_contract_size)
                      
                        
                        
                elif (rsi_short_signals_condition and not trend_condition) and dca_order_count + 1 <= settings.get('pyramiding_limit', 1):
                    print("상승 트랜드이므로 진입을 하지 않습니다.")
                    alert_key = f"user:{user_id}:{symbol}:trend_signal_alert"
                    is_alerted = await redis.get(alert_key)
                    if not is_alerted:
                        await send_telegram_message(f"⚠️ 숏 추가진입 진입 조건 불충족\n"f"━━━━━━━━━━━━━━━\n"f"추가 진입 조건에는 부합하지만 트랜드 조건이 맞지 않아 진입을 유보합니다.",user_id)
                        await redis.set(alert_key, "true", ex=7200)
                                                #포지션 진입 후, 강제로, 해당 타임프레임이 끝날 때까지는 최소한 진입하지 않도록 레디스 키 설정
                        next_candle_time = await calculate_next_candle_time(timeframe)
                        tf_str = get_timeframe(timeframe)
                        timeframe_lock_key = f"user:{user_id}:position_lock:{symbol}:short:{tf_str}"
                        # 다음 캔들 시작 시간까지 잠금 설정 (expire time은 초 단위)
                        current_time = int(datetime.now().timestamp())
                        expire_seconds = next_candle_time - current_time
                        if expire_seconds > 0:
                            await redis.set(timeframe_lock_key, "locked", ex=expire_seconds)
                            logger.info(f"[{user_id}] 포지션 {symbol}의 {side}방향 진입 잠금을 설정했습니다. 남은 시간: {expire_seconds}s")

                        await redis.hset(f"user:{user_id}:position:{symbol}:short", "last_entry_size", new_position_entry_contract_size)
                    

            else:
                print("side가 없습니다. side : ", side)
    
    # 포지션 정보 조회 (함수 끝 부분에서 사용되는 변수들 초기화)
    position_key = f"user:{user_id}:position:{symbol}:{side}"
    position_info = await redis.hgetall(position_key)
    # tp_data는 현재 사용되지 않으므로 주석 처리
 
    # (4) 청산 조건(트랜드 반전 등)
    should_close_with_trend = settings.get('use_trend_close', True)
    if should_close_with_trend:
        try:
            if (side == "long" and current_state == -2) or (side == "short" and current_state == 2):
                try:
                    dual_side = None
                    
                    if side == "long":
                        dual_side = "short"
                    else:
                        dual_side = "long"
                    
                    
                    print("청산 반전")
                    print("7번")
                    await trading_service.close_position(
                        user_id=user_id,
                        symbol=symbol,
                        side=side,
                        reason="트랜드 반전 포지션 종료"
                    )
                    
                    
                    
                    if use_dual_side_settings == "true" and trend_close_enabled == "true":
                        await trading_service.close_position(
                            user_id=user_id,
                            symbol=symbol,
                            side=dual_side,
                            reason="트랜드 반전으로 인한 양방향 포지션 종료"
                        )
                        
                    
                    try:
                        pnl = size * (current_price - float(entry_price)) if side == "long" else size * (float(entry_price) - current_price)

                        position_qty = await contracts_to_qty(symbol, int(size))
                        if position_qty is None:
                            position_qty = 0.0

                        # Get DCA count and leverage from Redis
                        dca_count_key = f"user:{user_id}:position:{symbol}:{side}:dca_count"
                        dca_count_str = await redis.get(dca_count_key)
                        dca_count = int(dca_count_str) if dca_count_str else 0
                        leverage = int(position_info.get("leverage", 1)) if position_info.get("leverage") else 1

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
                            close_type='trend_reversal',
                            leverage=leverage,
                            dca_count=dca_count,
                            avg_entry_price=float(position_info.get("avg_entry_price", entry_price)) if position_info.get("avg_entry_price") else None,
                        )
                    except Exception as e:
                        error_logger.error(f"[{user_id}]: 포지션 청산 통계 업데이트 실패", exc_info=True)
                        await send_telegram_message(f"⚠️ 포지션 청산 통계 업데이트 실패: {str(e)}", user_id, debug=True)
                    try:
                                    # Redis 포지션/평균가 등 초기화
                        await redis.delete(f"user:{user_id}:position:{symbol}:entry_price")
                        await redis.delete(f"user:{user_id}:position:{symbol}:long:dca_count")
                        await redis.delete(f"user:{user_id}:position:{symbol}:short:dca_count")
                        await redis.delete(f"user:{user_id}:position:{symbol}:long:dca_levels")
                        await redis.delete(f"user:{user_id}:position:{symbol}:short:dca_levels")
                        await redis.delete(f"user:{user_id}:position:{symbol}:{side}")
                        await init_user_position_data(user_id, symbol, side)
                    except Exception as e:
                        error_logger.error(f"[{user_id}]: REDIS 포지션 초기화 실패", exc_info=True)
                        await send_telegram_message(f"⚠️ REDIS 포지션 초기화 실패: {str(e)}", user_id, debug=True)

                except Exception as e:
                    traceback.print_exc()
                    error_logger.error(f"[{user_id}]:트랜드 반전 청산 실패", exc_info=True)
                    await send_telegram_message(f"⚠️ 트랜드 반전 청산 실패: {str(e)}", user_id, debug=True) 
                

        except Exception as e:
            error_logger.error(f"[{user_id}]:포지션 청산 실패", exc_info=True)
            await send_telegram_message(f"⚠️ 포지션 청산 실패: {str(e)}", user_id, debug=True)
    return current_position
