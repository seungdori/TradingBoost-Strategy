# src/trading/monitoring/position_validator.py

"""
포지션 검증 및 정리 모듈
"""

import asyncio
import json
import traceback
from typing import Tuple, Dict
from shared.logging import get_logger, log_order

from HYPERRSI.src.api.dependencies import get_exchange_context
from HYPERRSI.src.api.routes.order import close_position, ClosePositionRequest
from .telegram_service import get_identifier, send_telegram_message
from .utils import SUPPORTED_SYMBOLS, get_actual_order_type, add_recent_symbol, get_recent_symbols, convert_to_trading_symbol
from .order_monitor import check_order_status, update_order_status
from .break_even_handler import process_break_even_settings

logger = get_logger(__name__)

# Dynamic redis_client access
def _get_redis_client():
    """Get redis_client dynamically to avoid import-time errors"""
    from HYPERRSI.src.core import database as db_module
    return db_module.redis_client

redis_client = _get_redis_client()


# Module-level attribute for backward compatibility
def __getattr__(name):
    if name == "redis_client":
        return _get_redis_client()
    raise AttributeError(f"module has no attribute {name}")


async def check_position_exists(user_id: str, symbol: str, direction: str) -> tuple[bool, dict]:
    """
    특정 방향의 포지션이 존재하는지 확인하고 포지션 정보를 반환합니다.
    
    Args:
        user_id: 사용자 ID
        symbol: 심볼
        direction: 포지션 방향 ('long' 또는 'short')
        
    Returns:
        tuple: (포지션 존재 여부, 포지션 정보 딕셔너리)
    """
    try:
        from HYPERRSI.src.trading.trading_service import TradingService
        trading_service = TradingService()
        
        # 포지션 조회
        positions = await trading_service.fetch_okx_position(str(user_id), symbol, debug_entry_number=4)
        
        # 포지션 데이터 확인
        if not positions:
            logger.info(f"사용자 {user_id}의 {symbol} 포지션이 없습니다.")
            return False, {}
            
        # 특정 방향의 포지션이 있는지 확인
        for pos in positions.values() if isinstance(positions, dict) else [positions]:
            pos_side = pos.get('pos_side', '').lower()
            if pos_side == '':
                pos_side = pos.get('side', '').lower()
                
            if pos_side == direction:
                contracts = float(pos.get('contracts_amount', pos.get('size', '0')))
                if contracts > 0:
                    logger.info(f"사용자 {user_id}의 {symbol} {direction} 포지션 있음: {contracts} 계약")
                    # 포지션 정보 추가
                    position_info = {
                        'size': contracts,
                        'entry_price': float(pos.get('entry_price', '0')),
                        'timestamp': pos.get('creation_time', pos.get('timestamp', '')),
                        'position_id': pos.get('position_id', pos.get('id', '')),
                        'utime': pos.get('utime', pos.get('last_update_time', ''))
                    }
                    return True, position_info
                    
        # 해당 방향의 포지션이 없음
        logger.info(f"사용자 {user_id}의 {symbol} {direction} 포지션이 없습니다.")
        return False, {}
    except Exception as e:
        logger.error(f"포지션 확인 중 오류: {str(e)}")
        traceback.print_exc()
        # 오류 발생 시 기본값으로 포지션 있음 반환 (안전하게)
        return True, {}





async def verify_and_handle_position_closure(user_id: str, symbol: str, direction: str, closure_reason: str):
    """
    주문 체결 후 포지션이 실제로 종료되었는지 확인하고 적절한 조치를 취합니다.
    
    Args:
        user_id: 사용자 ID
        symbol: 심볼  
        direction: 포지션 방향
        closure_reason: 종료 원인 ('tp_complete', 'stop_loss', 'breakeven')
    """
    try:
        # 잠시 대기 (API 반영 시간 고려)
        await asyncio.sleep(2)
        
        # 포지션이 실제로 종료되었는지 확인
        position_exists, current_position_info = await check_position_exists(user_id, symbol, direction)
        
        if not position_exists:
            # 포지션이 정말 종료됨 - 종료 알림 전송
            logger.info(f"포지션 종료 확인됨: {user_id} {symbol} {direction} - {closure_reason}")
        else:
            # 포지션이 여전히 존재 - 강제 종료 후 종료 알림 전송
            remaining_size = current_position_info.get('size', 0)
            logger.warning(f"주문 체결 후에도 포지션 존재: {user_id} {symbol} {direction} - 남은 크기: {remaining_size}")
            logger.warning(f"종료 원인: {closure_reason}, 강제 종료를 시도합니다")
            
            # 남은 포지션 강제 종료 (break even 로직과 동일)
            try:
                from HYPERRSI.src.api.routes.order import close_position, ClosePositionRequest
                
                close_request = ClosePositionRequest(
                    close_type="market",
                    price=0,  # 마켓 주문이므로 가격 무관
                    close_percent=100
                )
                
                close_result = await close_position(
                    symbol=symbol,
                    close_request=close_request,
                    user_id=user_id,
                    side=direction
                )
                
                logger.info(f"{closure_reason} 후 남은 포지션 강제 종료 완료: {user_id} {symbol} {direction}")
                
                # 강제 종료 후에도 자연스러운 종료 알림 전송 (사용자는 내부 처리 과정 모름)
                
            except Exception as close_error:
                logger.error(f"남은 포지션 강제 종료 실패: {str(close_error)}")
                # 강제 종료 실패해도 dust면 종료로 간주 (사용자에게는 자연스러운 종료로 알림)
                if remaining_size < 0.001:
                    logger.info(f"Dust 포지션이므로 종료로 간주: {remaining_size}")
                    
    except Exception as e:
        logger.error(f"포지션 종료 확인 중 오류: {str(e)}")
        traceback.print_exc()



async def check_position_change(user_id: str, symbol: str, direction: str, current_position_info: dict):
    """
    포지션 변화를 감지하여 이전 포지션 종료 및 새 포지션 시작을 처리합니다.
    
    Args:
        user_id: 사용자 ID
        symbol: 심볼
        direction: 포지션 방향
        current_position_info: 현재 포지션 정보
    """
    try:
        import json
        
        # 메인 및 백업 키 설정
        position_tracking_key = f"user:{user_id}:position_tracking:{symbol}:{direction}"
        position_backup_key = f"user:{user_id}:position_backup:{symbol}:{direction}"
        
        # 이전 포지션 정보 조회 (메인 먼저, 없으면 백업)
        previous_position_str = await redis_client.get(position_tracking_key)
        backup_position_str = await redis_client.get(position_backup_key)
        
        # 현재 포지션 정보 저장
        current_position_str = json.dumps(current_position_info)
        
        # 메인 키 (24시간 TTL)
        await redis_client.set(position_tracking_key, current_position_str, ex=86400)
        # 백업 키 (TTL 없음 - 영구 보관)
        await redis_client.set(position_backup_key, current_position_str)
        
        # TTL 만료로 메인이 없지만 백업이 있는 경우
        if not previous_position_str and backup_position_str:
            backup_position_info = json.loads(backup_position_str)
            
            # 백업과 현재 포지션이 동일한지 확인 (크기와 진입가 기준)
            size_same = abs(current_position_info.get('size', 0) - backup_position_info.get('size', 0)) <= 0.001
            entry_price_same = abs(current_position_info.get('entry_price', 0) - backup_position_info.get('entry_price', 0)) <= 0.1
            
            if size_same and entry_price_same:
                # 동일 포지션 - 백업에서 복구
                logger.info(f"TTL 만료 후 동일 포지션 복구: {user_id} {symbol} {direction}")
                logger.info(f"크기={current_position_info.get('size')}, 진입가={current_position_info.get('entry_price')}")
                
                # 메인키를 다시 생성 (24시간 TTL로 추적 재개)
                await redis_client.set(position_tracking_key, current_position_str, ex=86400)
                logger.info(f"메인 추적키 복구 완료: {position_tracking_key}")
                return  # 추적 재개, 알림 없음
            else:
                # 다른 포지션 - 교체로 처리
                logger.info(f"TTL 만료 후 포지션 교체 감지: {user_id} {symbol} {direction}")
                logger.info(f"백업: 크기={backup_position_info.get('size')}, 진입가={backup_position_info.get('entry_price')}")
                logger.info(f"현재: 크기={current_position_info.get('size')}, 진입가={current_position_info.get('entry_price')}")
                
                # 포지션 교체 처리
                await handle_position_replacement(user_id, symbol, direction)
                return
        
        # 일반적인 포지션 변화 감지
        if previous_position_str:
            previous_position_info = json.loads(previous_position_str)
            
            # 포지션 변화 감지 조건들
            size_changed = abs(current_position_info.get('size', 0) - previous_position_info.get('size', 0)) > 0.001
            entry_price_changed = abs(current_position_info.get('entry_price', 0) - previous_position_info.get('entry_price', 0)) > 0.1
            timestamp_changed = current_position_info.get('timestamp', '') != previous_position_info.get('timestamp', '')
            utime_changed = current_position_info.get('utime', '') != previous_position_info.get('utime', '')
            
            # 포지션이 교체된 것으로 판단되는 경우
            if (size_changed and entry_price_changed) or timestamp_changed or utime_changed:
                logger.info(f"포지션 교체 감지: {user_id} {symbol} {direction}")
                logger.info(f"이전: 크기={previous_position_info.get('size')}, 진입가={previous_position_info.get('entry_price')}")
                logger.info(f"현재: 크기={current_position_info.get('size')}, 진입가={current_position_info.get('entry_price')}")
                
                # 포지션 교체 처리
                await handle_position_replacement(user_id, symbol, direction)
                
        else:
            # 첫 번째 포지션 추적 시작
            logger.info(f"포지션 추적 시작: {user_id} {symbol} {direction}")
            
    except Exception as e:
        logger.error(f"포지션 변화 확인 중 오류: {str(e)}")
        traceback.print_exc()



async def handle_position_replacement(user_id: str, symbol: str, direction: str):
    """
    포지션 교체 처리 - 이전 포지션 종료 알림 및 새 포지션 초기화
    
    Args:
        user_id: 사용자 ID
        symbol: 심볼
        direction: 포지션 방향
    """
    try:
        # 이전 포지션 종료 알림 전송
        closure_alert_key = f"closure_alert:user:{user_id}:{symbol}:{direction}"
        alert_sent = await redis_client.get(closure_alert_key)
        
        if not alert_sent:
            await redis_client.set(closure_alert_key, "1", ex=3600)
        
        # 새 포지션을 위한 데이터 초기화
        from HYPERRSI.src.api.routes.order import init_user_position_data
        await init_user_position_data(user_id, symbol, direction)
        
    except Exception as e:
        logger.error(f"포지션 교체 처리 중 오류: {str(e)}")
        traceback.print_exc()



async def check_and_cleanup_orders(user_id: str, symbol: str, direction: str):
    """
    포지션이 없을 때 해당 방향의 모든 주문을 확인하고 모니터링 데이터를 정리합니다.
    
    Args:
        user_id: 사용자 ID
        symbol: 심볼
        direction: 포지션 방향 ('long' 또는 'short')
    """
    try:
        # 포지션 존재 여부 및 정보 확인
        position_exists, current_position_info = await check_position_exists(user_id, symbol, direction)
        
        if position_exists:
            # 포지션이 있는 경우, 포지션 변화 감지
            await check_position_change(user_id, symbol, direction, current_position_info)
            return
            
        # 포지션 종료 알림 중복 방지 체크
        closure_alert_key = f"closure_alert:user:{user_id}:{symbol}:{direction}"
        alert_sent = await redis_client.get(closure_alert_key)
        
        if not alert_sent:
            # 포지션 종료 알림 전송
            # 중복 방지를 위해 1시간 동안 플래그 설정
            await redis_client.set(closure_alert_key, "1", ex=3600)
        
        # 포지션이 없으면 해당 방향의 모든 주문 확인
        logger.info(f"사용자 {user_id}의 {symbol} {direction} 포지션이 없어 모니터링 데이터 정리 시작")
        position_key = f"user:{user_id}:position:{symbol}:{direction}"

        # 1. 해당 방향의 모니터링 중인 모든 주문 가져오기
        pattern = f"monitor:user:{user_id}:{symbol}:order:*"
        order_keys = await redis_client.keys(pattern)
        orders_to_check = []
        
        for key in order_keys:
            order_data = await redis_client.hgetall(key)
            if not order_data:
                continue
                
            # 해당 방향의 주문만 필터링
            if order_data.get("position_side", "").lower() == direction.lower():
                # key에서 order_id 추출 - monitor:user:{user_id}:{symbol}:order:{order_id}
                parts = key.split(":")
                if len(parts) >= 6:
                    order_id = parts[5]
                    order_data["order_id"] = order_id
                    order_data["symbol"] = symbol
                    orders_to_check.append(order_data)
        
        # 주문이 없으면 트레일링 스탑만 정리
        if not orders_to_check:
            logger.info(f"사용자 {user_id}의 {symbol} {direction} 방향의 모니터링 주문이 없습니다.")
            # 트레일링 스탑 정리
            from .trailing_stop_handler import clear_trailing_stop
            await clear_trailing_stop(user_id, symbol, direction)
            return
            
        # 2. 각 주문의 상태 확인
        logger.info(f"사용자 {user_id}의 {symbol} {direction} 방향의 {len(orders_to_check)}개 주문 상태 확인")
        
        for order_data in orders_to_check:
            order_id = order_data.get("order_id")
            order_type = get_actual_order_type(order_data)
            
            # 주문이 이미 완료 상태면 건너뜀
            if order_data.get("status", "") != "open":
                continue
                
            # 주문 상태 확인
            order_status = await check_order_status(
                user_id=user_id,
                symbol=symbol,
                order_id=order_id,
                order_type=order_type
            )
            
            # 주문 상태 업데이트
            if isinstance(order_status, dict):
                status = "canceled"  # 기본값은 취소됨
                filled_sz = "0"
                
                # OrderResponse 형식 (get_order_detail 결과)
                if 'status' in order_status:
                    if order_status['status'] in ['FILLED', 'CLOSED', 'filled', 'closed']:
                        status = 'filled'
                        filled_sz = order_status.get('filled_amount', order_status.get('amount', '0'))
                    elif order_status['status'] in ['CANCELED', 'canceled']:
                        status = 'canceled'
                        filled_sz = order_status.get('filled_amount', '0')
                    else:
                        status = 'canceled'  # 포지션이 없으므로 남은 주문은 취소로 처리
                        filled_sz = order_status.get('filled_amount', '0')
                # OKX API 응답 (알고리즘 주문)
                elif 'state' in order_status:
                    state = order_status.get('state')
                    filled_sz = order_status.get('accFillSz', '0')
                    
                    # 상태 매핑
                    status_mapping = {
                        'filled': 'filled',
                        'effective': 'canceled',  # 포지션이 없으므로 활성 주문도 취소로 처리
                        'canceled': 'canceled',
                        'order_failed': 'failed'
                    }
                    status = status_mapping.get(state, 'canceled')
                
                # TP 주문이 체결된 경우 먼저 체결 알림 후 브레이크이븐 처리
                if status == 'filled' and (order_type.startswith('tp') or order_type.startswith('take_profit')):
                    logger.info(f"[{user_id}] TP 주문 체결됨: {order_id}({order_type})")
                    
                    # TP 중복 처리 방지 체크
                    tp_level = order_type.replace('tp', '').replace('take_profit', '')
                    if tp_level.isdigit():
                        tp_flag_key = f"user:{user_id}:position:{symbol}:{direction}:get_tp{tp_level}"
                        tp_already_processed = await redis_client.get(tp_flag_key)
                        
                        if tp_already_processed == "true":
                            logger.info(f"TP{tp_level} 이미 처리됨, 중복 처리 방지: {user_id} {symbol} {direction}")
                            continue
                    
                    # 1. 먼저 TP 체결 알림 전송
                    await update_order_status(
                        user_id=user_id,
                        symbol=symbol,
                        order_id=order_id,
                        status=status,
                        filled_amount=str(filled_sz)
                    )
                    
                    # 2. 그 다음 브레이크이븐/트레일링스탑 처리
                    try:
                        await process_break_even_settings(
                            user_id=user_id,
                            symbol=symbol,
                            order_type=order_type,
                            position_data=order_data
                        )
                    except Exception as be_error:
                        logger.error(f"브레이크이븐/트레일링스탑 처리 실패: {str(be_error)}")
                else:
                    # TP 주문이 아닌 경우에만 비동기로 주문 상태 업데이트
                    asyncio.create_task(update_order_status(
                        user_id=user_id,
                        symbol=symbol,
                        order_id=order_id,
                        status=status,
                        filled_amount=str(filled_sz)
                    ))
                
                
                
                # SL 주문이 체결된 경우, 관련 트레일링 스탑 데이터 정리
                if status == 'filled' and order_type == 'sl':
                    logger.info(f"[{user_id}] SL 주문 체결됨: {order_id}({order_type})")
                    from .trailing_stop_handler import clear_trailing_stop
                    asyncio.create_task(clear_trailing_stop(user_id, symbol, direction))
                    
                    # SL 주문 체결 로깅
                    price = float(order_data.get("price", "0"))
                    filled_amount = float(filled_sz) if filled_sz else 0
                    
                    # SL 주문 체결 로깅
                    try:
                        log_order(
                            user_id=user_id,
                            symbol=symbol,
                            action_type='sl_execution',
                            position_side=direction,
                            price=price,
                        quantity=filled_amount,
                            order_id=order_id,
                            current_price=price
                        )
                    except Exception as e:
                        logger.error(f"SL 주문 체결 로깅 실패: {str(e)}")
                
                # 체결됐으면 알림 발송
                if status == 'filled':
                    logger.info(f"포지션이 없지만 주문 {order_id}({order_type})이 체결됨을 발견")
            else:
                # 상태를 알 수 없는 경우 취소로 처리
                status = 'canceled'
                filled_sz = '0'
                
                # 주문 상태 업데이트
                asyncio.create_task(update_order_status(
                    user_id=user_id,
                    symbol=symbol,
                    order_id=order_id,
                    status=status,
                    filled_amount=str(filled_sz)
                ))
        
        # 3. 트레일링 스탑 정리
        from .trailing_stop_handler import clear_trailing_stop
        asyncio.create_task(clear_trailing_stop(user_id, symbol, direction))
        
        # 4. 포지션 데이터 정리
        position_key = f"user:{user_id}:position:{symbol}:{direction}"
        if await redis_client.exists(position_key):
            logger.info(f"포지션이 없어 Redis에서 포지션 데이터 삭제: {position_key}")
            await redis_client.delete(position_key)
            
        logger.info(f"사용자 {user_id}의 {symbol} {direction} 모니터링 데이터 정리 완료")
        await asyncio.sleep(1)
    except Exception as e:
        logger.error(f"주문 정리 중 오류: {str(e)}")
        traceback.print_exc()



async def cancel_algo_orders_for_no_position_sides(user_id: str):
    """
    포지션이 없는 방향에 대해 알고리즘 주문을 취소하는 함수
    
    Args:
        user_id: 사용자 ID (텔레그램 ID 또는 OKX UID)
    """
    try:
        # user_id를 OKX UID로 변환
        okx_uid = await get_identifier(str(user_id))
        
        logger.info(f"사용자 {okx_uid}의 포지션 없는 방향 알고리즘 주문 확인")
        # 거래소 컨텍스트 얻기
        async with get_exchange_context(str(okx_uid)) as exchange:
            # 현재 보유 중인 모든 포지션 확인
            try:
                positions = await exchange.fetch_positions()
                
                # 각 심볼별 포지션 방향 저장
                symbol_positions = {}
                
                for position in positions:
                    if not position or not isinstance(position, dict):
                        print(f"유효하지 않은 포지션 형식: {position}")
                        continue
                    
                    # 포지션 정보 추출
                    original_symbol = position.get("symbol", "")
                    symbol = original_symbol
                    
                    # 심볼에서 CCXT 형식(:USDT 등)을 제거
                    if ":" in symbol:
                        symbol = symbol.split(":")[0]
                    
                    # "-" 제거
                    symbol = symbol.replace("-", "")
                    
                    side = position.get("side", "")
                    contracts = position.get("contracts", 0)
                    size = position.get("size", 0)
                    size_value = float(position.get("contracts", position.get("size", 0)))
                    
                    print(f"포지션 세부 정보: 원본 심볼={original_symbol}, 변환 심볼={symbol}, 방향={side}, contracts={contracts}, size={size}, 최종 size_value={size_value}")
                    
                    # 유효한 포지션만 처리
                    if not (symbol and side):
                        print(f"심볼 또는 방향이 없음: {symbol}, {side}")
                        continue
                    
                    if size_value <= 0:
                        print(f"포지션 크기가 0 이하: {size_value}")
                        continue
                    
                    # 포지션 방향 정규화 (long/short)
                    normalized_side = "long" if side.lower() in ["buy", "long"] else "short"
                    
                    # 심볼별 포지션 방향 저장
                    if symbol not in symbol_positions:
                        symbol_positions[symbol] = set()
                    symbol_positions[symbol].add(normalized_side)
                    
                    # 활성 포지션이 있는 심볼은 최근 거래 심볼로 추가 (만료 시간 갱신)
                    await add_recent_symbol(okx_uid, symbol)
                
                # API 키 가져오기 (TriggerCancelClient 사용)
                try:
                    from HYPERRSI.src.api.dependencies import get_user_api_keys
                    from HYPERRSI.src.trading.cancel_trigger_okx import TriggerCancelClient
                    
                    api_keys = await get_user_api_keys(str(okx_uid))
                    cancel_client = TriggerCancelClient(
                        api_key=api_keys.get('api_key'),
                        secret_key=api_keys.get('api_secret'),
                        passphrase=api_keys.get('passphrase')
                    )
                except Exception as e:
                    logger.error(f"알고리즘 주문 취소 클라이언트 생성 실패: {str(e)}")
                    return
                
                # 각 심볼에 대해 반대 방향 찾기
                for symbol, sides in symbol_positions.items():
                    missing_sides = set(["long", "short"]) - sides
                    
                    # 심볼 형식 복원 (-를 포함한 형식, 예: BTC-USDT-SWAP)
                    trading_symbol = convert_to_trading_symbol(symbol)
                    
                    # 지원하지 않는 심볼이면 스킵
                    if trading_symbol not in SUPPORTED_SYMBOLS:
                        logger.info(f"지원하지 않는 심볼 스킵: {okx_uid}:{symbol} -> {trading_symbol}")
                        continue
                    
                    # 포지션이 없는 방향이 있으면 처리
                    for missing_side in missing_sides:
                        # 반대 방향의 주문 취소
                        logger.info(f"포지션 없음 확인 (전체 검사): {okx_uid}:{trading_symbol}:{missing_side}")
                        
                        try:
                            # TriggerCancelClient를 사용하여 알고리즘 주문 취소
                            result = await cancel_client.cancel_all_trigger_orders(
                                inst_id=trading_symbol,
                                side=missing_side,
                                algo_type="trigger",
                                user_id=str(okx_uid)
                            )
                            
                            if result and result.get('code') == '0':
                                # 주문 취소 성공 또는 주문이 없는 경우
                                if 'No active orders to cancel' in result.get('msg', ''):
                                    logger.info(f"알고리즘 주문 없음: {trading_symbol} {missing_side}")
                                else:
                                    logger.info(f"알고리즘 주문 취소 성공: {result}")
                                    #await send_telegram_message(f"[{okx_uid}] 🗑️ 포지션 없음 - {trading_symbol} {missing_side} 방향 알고리즘 주문 자동 취소", okx_uid, debug=True)
                            else:
                                logger.error(f"알고리즘 주문 취소 실패: {result}")
                        except Exception as cancel_error:
                            logger.error(f"알고리즘 주문 취소 API 호출 오류: {str(cancel_error)}")
                
                # 포지션이 전혀 없는 심볼에 대해서도 확인 필요
                # 최근 거래한 심볼 목록 가져오기
                try:
                    # 수정된 함수 사용
                    recent_symbols = await get_recent_symbols(okx_uid)
                    
                    for symbol in recent_symbols:
                        # 이미 확인한 심볼은 스킵
                        if symbol in symbol_positions:
                            continue
                        
                        # 심볼 형식 복원 (-를 포함한 형식, 예: BTC-USDT-SWAP)
                        trading_symbol = convert_to_trading_symbol(symbol)
                        
                        # 지원하지 않는 심볼이면 스킵
                        if trading_symbol not in SUPPORTED_SYMBOLS:
                            logger.info(f"지원하지 않는 심볼 스킵: {okx_uid}:{symbol} -> {trading_symbol}")
                            continue
                            
                        logger.info(f"포지션 없는 심볼 확인: {okx_uid}:{symbol} -> {trading_symbol}")
                        
                        # long, short 방향 모두에 대해 알고리즘 주문 취소
                        for direction in ["long", "short"]:
                            try:
                                # TriggerCancelClient를 사용하여 알고리즘 주문 취소
                                result = await cancel_client.cancel_all_trigger_orders(
                                    inst_id=trading_symbol,
                                    side=direction,
                                    algo_type="trigger",
                                    user_id=str(okx_uid)
                                )
                                
                                if result and result.get('code') == '0':
                                    # 'No active orders to cancel' 메시지가 있는지 확인
                                    if 'No active orders to cancel' in result.get('msg', ''):
                                        logger.info(f"취소할 알고리즘 주문 없음: {trading_symbol} {direction}")
                                    else:
                                        # 실제로 취소된 주문이 있는 경우에만 텔레그램 메시지 전송
                                        logger.info(f"알고리즘 주문 취소 성공: {result}")
                                        #await send_telegram_message(f"[{okx_uid}]🗑️1 포지션 없음 - {trading_symbol} {direction} 방향 알고리즘 주문 자동 취소", okx_uid, debug=True)
                                else:
                                    logger.error(f"알고리즘 주문 취소 실패: {result}")
                            except Exception as cancel_error:
                                logger.error(f"알고리즘 주문 취소 API 호출 오류: {str(cancel_error)}")
                    
                except Exception as e:
                    logger.error(f"최근 심볼 조회 오류: {str(e)}")
                    
            except Exception as e:
                logger.error(f"포지션 조회 오류: {str(e)}")
                
    except Exception as e:
        logger.error(f"사용자 {okx_uid} 알고리즘 주문 취소 중 오류: {str(e)}")


