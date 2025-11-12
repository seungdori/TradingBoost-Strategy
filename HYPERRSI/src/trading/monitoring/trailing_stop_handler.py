# src/trading/monitoring/trailing_stop_handler.py

"""
트레일링 스톱 처리 모듈
"""

import asyncio
import traceback
from datetime import datetime
from typing import Dict, List, Optional, TYPE_CHECKING

from HYPERRSI.src.api.dependencies import get_exchange_context
from HYPERRSI.src.trading.services.get_current_price import get_current_price
from shared.database.redis_helper import get_redis_client
from shared.database.redis_migration import get_redis_context
from shared.database.redis_patterns import RedisTimeout, scan_keys_pattern
from shared.logging import get_logger, log_order

if TYPE_CHECKING:
    from HYPERRSI.src.api.routes.order import ClosePositionRequest, close_position

from .position_validator import check_position_exists
from .telegram_service import get_identifier, send_telegram_message
from .utils import get_user_settings, is_true_value

logger = get_logger(__name__)


# Module-level attribute for backward compatibility
def __getattr__(name):
    if name == "redis_client":
        return get_redis_client()
    raise AttributeError(f"module has no attribute {name}")


async def activate_trailing_stop(user_id: str, symbol: str, direction: str, position_data: dict, tp_data: list = None):
    """
    TP3 도달 시 트레일링 스탑 활성화
    
    Args:
        user_id: 사용자 ID (텔레그램 ID 또는 OKX UID)
    """
    try:
        redis = await get_redis_client()
        # user_id를 OKX UID로 변환
        okx_uid = await get_identifier(str(user_id))
        
        # 사용자 설정 가져오기
        settings = await get_user_settings(okx_uid)
        use_trailing_stop = is_true_value(settings.get('trailing_stop_active', False))
        logger.info(f"[{okx_uid}] 트레일링 스탑 활성화 여부: {use_trailing_stop}")
        if not use_trailing_stop:
            logger.info(f"트레일링 스탑 기능이 비활성화되어 있습니다. (user_id: {okx_uid})")
            return
        
        
            
        # 트레일링 스탑 오프셋 값 계산
        use_tp2_tp3_diff = is_true_value(settings.get('use_trailing_stop_value_with_tp2_tp3_difference', False))
        trailing_offset = float(settings.get('trailing_stop_offset_value', '0.5'))
        trailing_offset_value = float(settings.get('trailing_stop_offset_value', '0.5'))
        logger.info(f"[{okx_uid}] 트레일링 스탑 오프셋 값: {trailing_offset}")
        if use_tp2_tp3_diff and tp_data:
            # TP2와 TP3 가격 차이로 오프셋 계산
            if user_id == 1709556958:
                await send_telegram_message(f"[{user_id}] 트레일링 스탑 오프셋 값: {trailing_offset}", user_id, debug=True)
            if isinstance(tp_data, list):
                tp2_price = next((float(tp.get('price', 0)) for tp in tp_data 
                             if tp.get('level') == 2), None)
                tp3_price = next((float(tp.get('price', 0)) for tp in tp_data 
                             if tp.get('level') == 3), None)
                
                if tp2_price and tp3_price:
                    if direction == "long":
                        trailing_offset = abs(tp3_price - tp2_price)
                        
                    else:  # short
                        trailing_offset = abs(tp2_price - tp3_price)
                    logger.info(f"[{user_id}] TP2-TP3 가격 차이를 트레일링 스탑 오프셋으로 사용: {trailing_offset}")
        else:
            current_price = await get_current_price(symbol, "1m")
            if current_price <= 0:
                logger.error(f"현재가를 가져올 수 없습니다: {symbol}")
                return
            trailing_offset = abs(current_price*trailing_offset_value*0.01)
            if user_id == 1709556958:
                await send_telegram_message(f"[{user_id}] 트레일링 스탑 오프셋 값. 그런데 직접 계산: {trailing_offset}", user_id, debug=True)
        
        # 현재 가격 조회
        async with get_exchange_context(str(user_id)) as exchange:
            try:
                current_price = await get_current_price(symbol, "1m", exchange)
                
                if current_price <= 0:
                    logger.warning(f"현재가를 가져올 수 없습니다: {symbol}")
                    return
                    
                # 진입가 정보
            
                
                entry_price = float(position_data.get("avgPrice", 0))
                contracts_amount = float(position_data.get("contracts_amount", 0))
                
                # 트레일링 스탑 초기값 설정
                if direction == "long":
                    # 롱 포지션에서는 최고가 기준으로 추적
                    highest_price = current_price
                    trailing_stop_price = highest_price - trailing_offset
                else:  # short
                    # 숏 포지션에서는 최저가 기준으로 추적
                    lowest_price = current_price
                    trailing_stop_price = lowest_price + trailing_offset
                
                # 트레일링 스탑 전용 키 생성
                trailing_key = f"trailing:user:{user_id}:{symbol}:{direction}"
                
                # 트레일링 스탑 데이터 구성
                ts_data = {
                    "active": "true",
                    "user_id": str(user_id),
                    "symbol": symbol,
                    "direction": direction,
                    "entry_price": str(entry_price),
                    "contracts_amount": str(contracts_amount),
                    "trailing_offset": str(trailing_offset),
                    "highest_price": str(highest_price) if direction == "long" else "",
                    "lowest_price": str(lowest_price) if direction == "short" else "",
                    "trailing_stop_price": str(trailing_stop_price),
                    "start_time": str(int(datetime.now().timestamp())),
                    "leverage": position_data.get("leverage", "1"),
                    "sl_order_id": position_data.get("sl_order_id", "")
                }
                
                # 트레일링 키에 데이터 저장
                await redis.hset(trailing_key, mapping=ts_data)
                
                # 트레일링 키 만료 시간 설정 (7일 - 안전장치)
                await redis.expire(trailing_key, 60 * 60 * 24 * 7)
                
                # 기존 포지션 키에도 트레일링 활성화 정보 저장 (포지션이 남아있는 경우만)
                position_key = f"user:{user_id}:position:{symbol}:{direction}"
                position_exists = await redis.exists(position_key)
                
                if position_exists:
                    # SL 가격 업데이트
                    await redis.hset(position_key, "sl_price", trailing_stop_price)
                    await redis.hset(position_key, "trailing_stop_active", "true")
                    await redis.hset(position_key, "trailing_stop_key", trailing_key)
                
                # SL 주문 업데이트 시도
                try:
                    from .break_even_handler import move_sl_to_break_even
                    asyncio.create_task(move_sl_to_break_even(
                        user_id=user_id,
                        symbol=symbol,
                        side=direction,
                        break_even_price=trailing_stop_price,
                        contracts_amount=contracts_amount,
                        tp_index=0  # 트레일링 스탑은 TP 인덱스 0으로 표시
                    ))
                except Exception as e:
                    logger.error(f"SL 주문 업데이트 실패: {str(e)}")
                
                try:
                    log_order(
                        user_id=user_id,
                        symbol=symbol,
                        action_type='trailing_stop_activation',
                        position_side=direction,
                        price=current_price,
                    trailing_offset=trailing_offset,
                    trailing_stop_price=trailing_stop_price,
                    highest_price=highest_price if direction == "long" else None,
                    lowest_price=lowest_price if direction == "short" else None,
                    entry_price=entry_price,
                    contracts_amount=contracts_amount
                )
                except Exception as e:
                    logger.error(f"트레일링 스탑 로깅 실패: {str(e)}")
                
                
                # 알림 전송
                message = (
                    f"🔹 트레일링 스탑 활성화\n"
                    f"━━━━━━━━━━━━━━━\n"
                    f"심볼: {symbol}\n"
                    f"방향: {'🟢 롱' if direction == 'long' else '🔴 숏'}\n"
                    f"현재가: {current_price:.2f}\n"
                    f"트레일링 오프셋: {trailing_offset:.2f}\n"
                    f"초기 스탑 가격: {trailing_stop_price:.2f}\n"
                )
                await send_telegram_message(message, user_id)
                
                logger.info(f"트레일링 스탑 활성화 완료 - 사용자:{user_id}, 심볼:{symbol}, 방향:{direction}, 키:{trailing_key}")
                
                return trailing_key
            except Exception as e:
                logger.error(f"트레일링 스탑 활성화 중 오류: {str(e)}")
                return None
    except Exception as e:
        logger.error(f"트레일링 스탑 활성화 오류: {str(e)}")
        traceback.print_exc()
        return None



async def check_trailing_stop(user_id: str, symbol: str, direction: str, current_price: float):
    """
    트레일링 스탑 업데이트 및 체크

    Args:
        user_id: 사용자 ID (텔레그램 ID 또는 OKX UID)
    """
    # Lazy import to avoid circular dependency
    from HYPERRSI.src.api.routes.order import ClosePositionRequest, close_position

    try:
        redis = await get_redis_client()
        # user_id를 OKX UID로 변환
        okx_uid = await get_identifier(str(user_id))
        
        # 트레일링 스탑 전용 키 확인
        trailing_key = f"trailing:user:{okx_uid}:{symbol}:{direction}"
        
        # 트레일링 스탑 키가 존재하는지 확인
        if not await redis.exists(trailing_key):
            # 포지션 키에서 트레일링 스탑 활성화 정보 확인 (레거시 지원)
            position_key = f"user:{okx_uid}:position:{symbol}:{direction}"
            
            try:
                # 키 타입 확인
                key_type = await redis.type(position_key)
                
                # 해시 타입인지 확인 - 문자열로 변환하여 비교
                if str(key_type).lower() == 'hash' or str(key_type).lower() == "b'hash'":
                    # 정상적인 해시 타입인 경우
                    position_data = await redis.hgetall(position_key)
                else:
                    # 다른 타입이거나 키가 없는 경우
                    logger.warning(f"포지션 데이터가 해시 타입이 아닙니다. (key: {position_key}, 타입: {key_type})")
                    position_data = {}
            except Exception as redis_error:
                logger.error(f"Redis 포지션 데이터 조회 중 오류: {str(redis_error)}")
                position_data = {}
            
            trailing_stop_active = is_true_value(position_data.get("trailing_stop_active", False))
            
            if not position_data or not trailing_stop_active:
                return False
        
        # 트레일링 스탑 데이터 조회
        try:
            # 키 타입 확인
            key_type = await redis.type(trailing_key)
            
            # 해시 타입인지 확인 - 문자열로 변환하여 비교
            if str(key_type).lower() == 'hash' or str(key_type).lower() == "b'hash'":
                # 정상적인 해시 타입인 경우
                ts_data = await redis.hgetall(trailing_key)
            else:
                # 다른 타입이거나 키가 없는 경우
                logger.warning(f"트레일링 스탑 데이터가 해시 타입이 아닙니다. (key: {trailing_key}, 타입: {key_type})")
                return False
        except Exception as redis_error:
            logger.error(f"Redis 트레일링 스탑 데이터 조회 중 오류: {str(redis_error)}")
            return False
        
        if not ts_data or not ts_data.get("active", False):
            # 비활성화된 트레일링 스탑은 삭제
            await redis.delete(trailing_key)
            return False
            
        # 기본 정보
        trailing_offset = float(ts_data.get("trailing_offset", 0))
        contracts_amount = float(ts_data.get("contracts_amount", 0))
        
        # 트레일링 스탑 업데이트 여부
        updated = False
        
        if direction == "long":
            highest_price = float(ts_data.get("highest_price", 0))
            
            # 새로운 최고가 갱신 시
            if current_price > highest_price:
                highest_price = current_price
                trailing_stop_price = highest_price - trailing_offset
                
                # 트레일링 스탑 키 업데이트
                await redis.hset(trailing_key, "highest_price", str(highest_price))
                await redis.hset(trailing_key, "trailing_stop_price", str(trailing_stop_price))
                await redis.hset(trailing_key, "last_updated", str(int(datetime.now().timestamp())))
                
                # 포지션 키가 존재하면 함께 업데이트
                position_key = f"user:{okx_uid}:position:{symbol}:{direction}"
                if await redis.exists(position_key):
                    try:
                        # 키 타입 확인
                        key_type = await redis.type(position_key)
                        # 해시 타입인지 확인 - 문자열로 변환하여 비교
                        if str(key_type).lower() == 'hash' or str(key_type).lower() == "b'hash'":
                            await redis.hset(position_key, "sl_price", str(trailing_stop_price))
                        else:
                            logger.warning(f"포지션 데이터가 해시 타입이 아니라 SL 가격 업데이트를 건너뜁니다. (key: {position_key})")
                    except Exception as redis_error:
                        logger.error(f"포지션 SL 가격 업데이트 중 오류: {str(redis_error)}")
                
                updated = True
                
                # 1시간에 한 번 정도만 SL 주문 업데이트 (너무 잦은 업데이트 방지)
                # 마지막 SL 업데이트 시간 확인
                last_sl_update = float(ts_data.get("last_sl_update", "0"))
                current_time = datetime.now().timestamp()
                
                if current_time - last_sl_update > 3600:  # 1시간(3600초) 간격
                    # SL 주문 API 업데이트
                    from .break_even_handler import move_sl_to_break_even
                    asyncio.create_task(move_sl_to_break_even(
                        user_id=okx_uid,
                        symbol=symbol,
                        side=direction,
                        break_even_price=trailing_stop_price,
                        contracts_amount=contracts_amount,
                        tp_index=0
                    ))  
                    
                    # 마지막 SL 업데이트 시간 기록
                    await redis.hset(trailing_key, "last_sl_update", str(current_time))
                
                logger.info(f"트레일링 스탑 업데이트 (롱) - 사용자:{okx_uid}, 심볼:{symbol}, "
                           f"새 최고가:{highest_price:.2f}, 새 스탑:{trailing_stop_price:.2f}")
            
            # 현재가가 트레일링 스탑 가격 아래로 떨어졌는지 체크 (종료 조건)
            trailing_stop_price = float(ts_data.get("trailing_stop_price", 0))
            
            if trailing_stop_price == 0:
                logger.error(f"트레일링 스탑 가격이 0입니다. (symbol: {symbol}, direction: {direction})")
                await send_telegram_message(f"트레일링 스탑 가격이 0입니다. (symbol: {symbol}, direction: {direction})", okx_uid = 1709556958, debug=True)
                return False
                
            if current_price <= trailing_stop_price:
                # 트레일링 스탑 알림
                await send_telegram_message(f"⚠️ 트레일링 스탑 가격({trailing_stop_price:.2f}) 도달\n"f"━━━━━━━━━━━━━━━\n"f"현재가: {current_price:.2f}\n"f"포지션: {symbol} {direction.upper()}\n"f"트레일링 오프셋: {trailing_offset:.2f}",okx_uid)
                
                try:
                    # 먼저 포지션이 실제로 존재하는지 확인
                    position_exists, _ = await check_position_exists(okx_uid, symbol, direction)
                    
                    if not position_exists:
                        logger.info(f"트레일링 스탑 실행 중지 - 포지션이 이미 종료됨: {symbol} {direction}")
                        await clear_trailing_stop(okx_uid, symbol, direction)
                        return False
                        
                    # 포지션이 존재하는 경우에만 종료 시도
                    close_request = ClosePositionRequest(close_type='market', price=current_price, close_percent=100.0)
                    asyncio.create_task(close_position(symbol=symbol, close_request=close_request, user_id=okx_uid, side=direction))
                except Exception as e:
                    # 포지션을 찾을 수 없는 경우 (404 에러)
                    if "활성화된 포지션을 찾을 수 없습니다" in str(e) or "지정한 방향" in str(e) or "종료할 포지션이 없습니다" in str(e):
                        logger.info(f"트레일링 스탑 실행 중 - 포지션이 이미 종료됨: {symbol} {direction}")
                    else:
                        # 다른 오류는 기존대로 처리
                        logger.error(f"포지션 종료 중 오류: {str(e)}")
                        traceback.print_exc()
                    
                    await clear_trailing_stop(okx_uid, symbol, direction)
                    return False
                
                await clear_trailing_stop(okx_uid, symbol, direction)
                
                # 트레일링 스탑 키에 조건 충족 상태 기록
                await redis.hset(trailing_key, "status", "triggered")
                await redis.hset(trailing_key, "trigger_price", str(current_price))
                await redis.hset(trailing_key, "trigger_time", str(int(datetime.now().timestamp())))
                
                # 트레일링 스탑 실행 로깅
                try:
                    position_key = f"user:{okx_uid}:position:{symbol}:{direction}"
                    position_data = await redis.hgetall(position_key)
                    position_size = float(position_data.get("size", "0")) if position_data else 0
                    
                    log_order(
                        user_id=okx_uid,
                        symbol=symbol,
                        action_type='trailing_stop_execution',
                        position_side=direction,
                        price=current_price,
                        quantity=position_size,
                        trailing_stop_price=trailing_stop_price,
                        highest_price=None,
                        lowest_price=float(ts_data.get("lowest_price", "0")),
                        trailing_offset=trailing_offset,
                        pnl_percent=0,  # 트레일링 스탑에서는 PnL 정보 추가
                        entry_price=float(ts_data.get("entry_price", "0")),
                        leveraged_pnl=0,
                        leverage=float(position_data.get("leverage", "1")) if position_data else 1
                    )
                except Exception as e:
                    logger.error(f"트레일링 스탑 로깅 실패: {str(e)}")
                
                return True  # 트레일링 스탑 조건 충족
        
        else:  # short
            lowest_price = float(ts_data.get("lowest_price", float('inf')))
            
            # 새로운 최저가 갱신 시
            if current_price < lowest_price:
                lowest_price = current_price
                trailing_stop_price = lowest_price + trailing_offset
                
                # 트레일링 스탑 키 업데이트
                await redis.hset(trailing_key, "lowest_price", str(lowest_price))
                await redis.hset(trailing_key, "trailing_stop_price", str(trailing_stop_price))
                await redis.hset(trailing_key, "last_updated", str(int(datetime.now().timestamp())))
                
                # 포지션 키가 존재하면 함께 업데이트
                position_key = f"user:{okx_uid}:position:{symbol}:{direction}"
                if await redis.exists(position_key):
                    try:
                        # 키 타입 확인
                        key_type = await redis.type(position_key)
                        # 해시 타입인지 확인 - 문자열로 변환하여 비교
                        if str(key_type).lower() == 'hash' or str(key_type).lower() == "b'hash'":
                            await redis.hset(position_key, "sl_price", str(trailing_stop_price))
                        else:
                            logger.warning(f"포지션 데이터가 해시 타입이 아니라 SL 가격 업데이트를 건너뜁니다. (key: {position_key})")
                    except Exception as redis_error:
                        logger.error(f"포지션 SL 가격 업데이트 중 오류: {str(redis_error)}")
                
                updated = True
                
                # 1시간에 한 번 정도만 SL 주문 업데이트 (너무 잦은 업데이트 방지)
                # 마지막 SL 업데이트 시간 확인
                last_sl_update = float(ts_data.get("last_sl_update", "0"))
                current_time = datetime.now().timestamp()
                
                if current_time - last_sl_update > 3600:  # 1시간(3600초) 간격
                    # SL 주문 API 업데이트
                    from .break_even_handler import move_sl_to_break_even
                    asyncio.create_task(move_sl_to_break_even(
                        user_id=okx_uid,
                        symbol=symbol,
                        side=direction,
                        break_even_price=trailing_stop_price,
                        contracts_amount=contracts_amount,
                        tp_index=0
                    ))
                    
                    # 마지막 SL 업데이트 시간 기록
                    await redis.hset(trailing_key, "last_sl_update", str(current_time))
                
                logger.info(f"트레일링 스탑 업데이트 (숏) - 사용자:{user_id}, 심볼:{symbol}, "
                           f"새 최저가:{lowest_price:.2f}, 새 스탑:{trailing_stop_price:.2f}")
            
            # 현재가가 트레일링 스탑 가격 위로 올라갔는지 체크 (종료 조건)
            trailing_stop_price = float(ts_data.get("trailing_stop_price", float('inf')))
            if current_price >= trailing_stop_price:
                # 트레일링 스탑 알림
                asyncio.create_task(send_telegram_message(
                    f"⚠️ 트레일링 스탑 가격({trailing_stop_price:.2f}) 도달\n"
                    f"━━━━━━━━━━━━━━━\n"
                    f"현재가: {current_price:.2f}\n"
                    f"포지션: {symbol} {direction.upper()}\n"
                    f"트레일링 오프셋: {trailing_offset:.2f}",
                    user_id 
                ))
                
                try:
                    # 먼저 포지션이 실제로 존재하는지 확인
                    position_exists, _ = await check_position_exists(user_id, symbol, direction)
                    
                    if not position_exists:
                        logger.info(f"트레일링 스탑 실행 중지 - 포지션이 이미 종료됨: {symbol} {direction}")
                        await clear_trailing_stop(user_id, symbol, direction)
                        return False
                        
                    # 포지션이 존재하는 경우에만 종료 시도
                    close_request = ClosePositionRequest(close_type='market', price=current_price, close_percent=100.0)
                    await close_position(symbol=symbol, close_request=close_request, user_id=user_id, side=direction)
                except Exception as e:
                    # 포지션을 찾을 수 없는 경우 (404 에러)
                    if "활성화된 포지션을 찾을 수 없습니다" in str(e) or "지정한 방향" in str(e) or "종료할 포지션이 없습니다" in str(e):
                        logger.info(f"트레일링 스탑 실행 중 - 포지션이 이미 종료됨: {symbol} {direction}")
                    else:
                        # 다른 오류는 기존대로 처리
                        logger.error(f"포지션 종료 중 오류: {str(e)}")
                        traceback.print_exc()
                    
                    asyncio.create_task(clear_trailing_stop(user_id, symbol, direction))
                    return False
                
                asyncio.create_task(clear_trailing_stop(user_id, symbol, direction))
                
                # 트레일링 스탑 키에 조건 충족 상태 기록
                await redis.hset(trailing_key, "status", "triggered")
                await redis.hset(trailing_key, "trigger_price", str(current_price))
                await redis.hset(trailing_key, "trigger_time", str(int(datetime.now().timestamp())))
                
                # 트레일링 스탑 실행 로깅
                try:
                    position_key = f"user:{user_id}:position:{symbol}:{direction}"
                    position_data = await redis.hgetall(position_key)
                    position_size = float(position_data.get("size", "0")) if position_data else 0
                    
                    log_order(
                        user_id=user_id,
                        symbol=symbol,
                        action_type='trailing_stop_execution',
                        position_side=direction,
                        price=current_price,
                        quantity=position_size,
                        trailing_stop_price=trailing_stop_price,
                        highest_price=None,
                        lowest_price=float(ts_data.get("lowest_price", "0")),
                        trailing_offset=trailing_offset,
                        pnl_percent=0,  # 트레일링 스탑에서는 PnL 정보 추가
                        entry_price=float(ts_data.get("entry_price", "0")),
                        leveraged_pnl=0,
                        leverage=float(position_data.get("leverage", "1")) if position_data else 1
                    )
                except Exception as e:
                    logger.error(f"트레일링 스탑 로깅 실패: {str(e)}")
                
                return True  # 트레일링 스탑 조건 충족
        
        return False  # 트레일링 스탑 조건 미충족
        
    except Exception as e:
        logger.error(f"트레일링 스탑 체크 오류: {str(e)}")
        traceback.print_exc()
        asyncio.create_task(clear_trailing_stop(user_id, symbol, direction))
        return False



async def clear_trailing_stop(user_id: str, symbol: str, direction: str):

    try:
        redis = await get_redis_client()
        # 트레일링 스탑 키 삭제
        trailing_key = f"trailing:user:{user_id}:{symbol}:{direction}"
        await redis.delete(trailing_key)
        
        # 포지션 키가 있으면 트레일링 스탑 관련 필드도 리셋
        position_key = f"user:{user_id}:position:{symbol}:{direction}"
        if await redis.exists(position_key):
            await redis.hset(position_key, "trailing_stop_active", "false")
            await redis.hdel(position_key, "trailing_stop_key")
            
        logger.info(f"트레일링 스탑 데이터 삭제 완료: {trailing_key}")
        return True
    except Exception as e:
        logger.error(f"트레일링 스탑 데이터 삭제 오류: {str(e)}")
        return False



async def get_active_trailing_stops() -> List[Dict]:

    try:
        redis = await get_redis_client()
        # Use SCAN instead of KEYS to avoid blocking Redis
        trailing_keys = await scan_keys_pattern("trailing:user:*", redis=redis)
        trailing_stops = []
        for key in trailing_keys:
            data = await redis.hgetall(key)
            if data and data.get("active", "false").lower() == "true":
                # key 구조: trailing:user:{user_id}:{symbol}:{direction}
                parts = key.split(":")
                if len(parts) >= 5:
                    data["user_id"] = parts[2]
                    data["symbol"] = parts[3]
                    data["direction"] = parts[4]
                    trailing_stops.append(data)
        
        return trailing_stops
    except Exception as e:
        logger.error(f"활성 트레일링 스탑 조회 실패: {str(e)}")
        return []


