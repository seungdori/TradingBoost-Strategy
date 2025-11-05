# src/trading/monitoring/core.py

"""
모니터링 서비스 메인 코어 모듈
"""

import asyncio
import atexit
import gc
import os
import signal
import sys
import time
import traceback
from datetime import datetime
from typing import Any, Dict, List, TYPE_CHECKING

import psutil

from HYPERRSI.src.api.dependencies import get_exchange_context
from shared.database.redis import ping_redis as check_redis_connection, reconnect_redis

# Lazy imports to avoid circular dependencies
if TYPE_CHECKING:
    from HYPERRSI.src.api.routes.order.models import ClosePositionRequest
    from HYPERRSI.src.api.routes.order.order import close_position
from HYPERRSI.src.trading.services.get_current_price import get_current_price
from shared.database.redis_helper import get_redis_client
from shared.logging import get_logger, log_order

from .order_monitor import (
    check_missing_orders,
    check_order_status,
    check_recent_filled_orders,
    should_check_sl_order,
    should_check_tp_order,
    update_order_status,
)
from .position_validator import (
    cancel_algo_orders_for_no_position_sides,
    check_and_cleanup_orders,
    check_position_change,
    check_position_exists,
    verify_and_handle_position_closure,
)
from .redis_manager import (
    check_redis_connection_task,
    get_all_running_users,
    get_user_monitor_orders,
    perform_memory_cleanup,
)
from .telegram_service import get_identifier, send_telegram_message
from .trailing_stop_handler import (
    check_trailing_stop,
    clear_trailing_stop,
    get_active_trailing_stops,
)
from .utils import (
    MAX_MEMORY_MB,
    MAX_RESTART_ATTEMPTS,
    MEMORY_CLEANUP_INTERVAL,
    MONITOR_INTERVAL,
    ORDER_CHECK_INTERVAL,
    add_recent_symbol,
    get_actual_order_type,
    should_log,
)

logger = get_logger(__name__)


# Module-level attribute for backward compatibility
def __getattr__(name):
    if name == "redis_client":
        return get_redis_client()
    raise AttributeError(f"module has no attribute {name}")


async def monitor_orders_loop():
    """
    주문을 지속적으로 모니터링하는 무한 루프 함수
    """

    redis = await get_redis_client()
    logger.info("주문 모니터링 서비스 시작")
    last_order_check_time: float = 0.0  # 마지막 주문 상태 전체 확인 시간
    last_position_check_time: float = 0.0  # 마지막 포지션 확인 시간
    last_memory_cleanup_time: float = 0.0  # 마지막 메모리 정리 시간
    last_memory_check_time: float = 0.0    # 마지막 메모리 체크 시간
    last_algo_cancel_time: float = 0.0     # 마지막 알고리즘 주문 취소 시간
    last_redis_check_time: float = 0.0     # 마지막 Redis 연결 확인 시간
    POSITION_CHECK_INTERVAL = 60  # 포지션 확인 간격(초)
    MEMORY_CHECK_INTERVAL = 60    # 메모리 체크 간격(초)
    REDIS_CHECK_INTERVAL = 30     # Redis 연결 확인 간격(초)
    ALGO_ORDER_CANCEL_INTERVAL = 300  # 알고리즘 주문 취소 간격(초, 5분)
    consecutive_errors = 0  # 연속 오류 카운터
    
    # API 속도 제한 관리
    api_call_timestamps: List[float] = []
    
    # 루프 카운터 초기화
    loop_count = 0
    
    while True:
        try:
            # 루프 카운터 증가
            loop_count += 1
            current_time = time.time()
            
            # Redis 연결 상태 주기적 확인 (30초마다) - 비동기로 처리
            if current_time - last_redis_check_time >= REDIS_CHECK_INTERVAL:
                last_redis_check_time = current_time
                asyncio.create_task(check_redis_connection_task())
            
            # 메모리 사용량 체크 (1분마다)
            if current_time - last_memory_check_time >= MEMORY_CHECK_INTERVAL:
                last_memory_check_time = current_time
                process = psutil.Process()
                memory_info = process.memory_info()
                memory_usage_mb = memory_info.rss / 1024 / 1024
                logger.info(f"현재 메모리 사용량: {memory_usage_mb:.2f} MB")
                
                # 메모리 사용량이 임계치를 초과하면 강제 정리
                if memory_usage_mb > MAX_MEMORY_MB:
                    logger.warning(f"메모리 사용량({memory_usage_mb:.2f} MB)이 제한({MAX_MEMORY_MB} MB)을 초과하여 강제 정리 수행")
                    # 가비지 컬렉션 강제 실행
                    gc.collect()
                    # Redis 연결 초기화
                    await reconnect_redis()
                    # 메모리 사용량 다시 계산
                    memory_info = process.memory_info()
                    logger.info(f"메모리 정리 후 사용량: {memory_info.rss / 1024 / 1024:.2f} MB")
            
            # 활성 사용자 목록 가져오기
            try:
                # Redis 연결 상태 확인
                if not await check_redis_connection():
                    logger.warning("활성 사용자 조회 전 Redis 연결 상태 불량, 재연결 시도")
                    await reconnect_redis()
                    
                running_users = await get_all_running_users()
                last_active_users_num_logging = await redis.get(f"last_active_users_num_logging")
                if len(running_users) > 0 and last_active_users_num_logging is None:
                    logger.info(f"[활성 사용자 수: {len(running_users)}]")
                    await redis.set(f"last_active_users_num_logging", current_time)
                elif len(running_users) > 0 and last_active_users_num_logging is not None and abs(current_time - float(last_active_users_num_logging)) >= 60:
                    logger.info(f"[활성 사용자 수: {len(running_users)}]")
                    await redis.set(f"last_active_users_num_logging", current_time)
            except Exception as users_error:
                logger.error(f"running_users 조회 실패: {str(users_error)}")
                logger.error(f"에러 타입: {type(users_error).__name__}, 상세 내용: {traceback.format_exc()}")
                running_users = []
                
                # Redis 재연결 시도
                try:
                    logger.info("running_users 조회 실패 후 Redis 재연결 시도")
                    await reconnect_redis()
                except Exception as reconnect_error:
                    logger.error(f"Redis 재연결 실패: {str(reconnect_error)}")
            
            # 주문 강제 확인 여부 (15초마다)
            force_check_orders = current_time - last_order_check_time >= ORDER_CHECK_INTERVAL
            if force_check_orders:
                #logger.info(f"정기 주문 상태 확인 시작 (간격: {ORDER_CHECK_INTERVAL}초)")
                last_order_check_time = current_time
            
            # 포지션 확인 여부 (60초마다)
            force_check_positions = current_time - last_position_check_time >= POSITION_CHECK_INTERVAL
            if force_check_positions:
                #logger.info(f"정기 포지션 확인 시작 (간격: {POSITION_CHECK_INTERVAL}초)")
                last_position_check_time = current_time
            
            # 알고리즘 주문 취소 여부 (5분마다)
            force_cancel_algo_orders = current_time - last_algo_cancel_time >= ALGO_ORDER_CANCEL_INTERVAL
            if force_cancel_algo_orders:
                logger.info(f"알고리즘 주문 취소 확인 시작 (간격: {ALGO_ORDER_CANCEL_INTERVAL}초)")
                last_algo_cancel_time = current_time
                
                # 5분마다 모든 사용자에 대해 포지션 없는 방향의 알고리즘 주문 취소
                for user_id in running_users:
                    # 각 사용자에 대해 포지션이 없는 방향의 알고리즘 주문 취소 함수 호출
                    asyncio.create_task(cancel_algo_orders_for_no_position_sides(str(user_id)))
            
            # 먼저 모든 활성 트레일링 스탑 체크 (독립적인 트레일링 스탑)
            active_trailings = await get_active_trailing_stops()
            if len(active_trailings) > 0:
                logger.info(f"활성 트레일링 스탑 수: {len(active_trailings)}")
                for ts_data in active_trailings:
                    try:
                        user_id = str(ts_data.get("user_id", "0"))
                        symbol = ts_data.get("symbol", "")
                        direction = ts_data.get("direction", "")

                        if not (user_id and symbol and direction) or user_id not in running_users:
                            continue
                        
                        # 현재가 조회
                        async with get_exchange_context(str(user_id)) as exchange:
                            try:
                                current_price = await get_current_price(symbol, "1m", exchange)
                                
                                if current_price <= 0:
                                    logger.warning(f"[트레일링] 유효하지 않은 현재가: {current_price}, 심볼: {symbol}")
                                    continue
                                
                                # 트레일링 스탑 조건 체크
                                ts_hit = await check_trailing_stop(str(user_id), symbol, direction, current_price)
                                
                                # 트레일링 스탑 조건 충족 시
                                if ts_hit:
                                    # SL 주문 ID 확인

                                    # Lazy import to avoid circular dependency
                                    from HYPERRSI.src.api.routes.order.models import ClosePositionRequest
                                    from HYPERRSI.src.api.routes.order.order import close_position

                                    close_request = ClosePositionRequest(
                                        close_type="market",
                                        price=current_price,
                                        close_percent=100
                                    )

                                    await close_position(
                                        symbol=symbol,
                                        close_request=close_request,
                                        user_id=str(user_id),
                                        side=direction
                                    )
                                    
                                    sl_order_id = ts_data.get("sl_order_id", "")
                                    
                                    
                                    
                                    if sl_order_id:
                                        # SL 주문 상태 확인
                                        logger.info(f"[트레일링] SL 주문 상태 확인: {sl_order_id}")
                                        sl_status = await check_order_status(
                                            user_id=str(user_id),
                                            symbol=symbol,
                                            order_id=sl_order_id,
                                            order_type="sl"
                                        )

                                        # SL 주문이 체결되었는지 확인
                                        if isinstance(sl_status, dict) and sl_status.get('status') in ['FILLED', 'CLOSED', 'filled', 'closed']:
                                            logger.info(f"[트레일링] SL 주문 체결됨: {sl_order_id}")
                                            # 트레일링 스탑 데이터 삭제
                                            await clear_trailing_stop(str(user_id), symbol, direction)
                                        elif isinstance(sl_status, dict) and sl_status.get('status') in ['CANCELED', 'canceled']:
                                            # SL 주문이 취소된 경우 트레일링 스탑 데이터 삭제
                                            logger.info(f"[트레일링] SL 주문 취소됨: {sl_order_id}")
                                            await clear_trailing_stop(str(user_id), symbol, direction)
                                    else:
                                        # SL 주문 ID가 없는 경우 (포지션 자체 확인)
                                        position_exists, _ = await check_position_exists(str(user_id), symbol, direction)

                                        if not position_exists:
                                            # 포지션이 없으면 트레일링 스탑 데이터 삭제
                                            logger.info(f"[트레일링] 포지션 없음, 트레일링 스탑 삭제: {user_id}:{symbol}:{direction}")
                                            asyncio.create_task(clear_trailing_stop(str(user_id), symbol, direction))
                            except Exception as e:
                                logger.error(f"트레일링 스탑 현재가 조회 오류: {str(e)}")
                    except Exception as ts_error:
                        logger.error(f"트레일링 스탑 처리 중 오류: {str(ts_error)}")
                        traceback.print_exc()
            
            
            
                
            # 메모리 정리 실행 (10분마다) - 비동기로 처리하여 메인 루프 차단 방지
            force_memory_cleanup = current_time - last_memory_cleanup_time >= MEMORY_CLEANUP_INTERVAL
            if force_memory_cleanup:
                last_memory_cleanup_time = current_time
                # 메모리 정리를 별도 태스크로 실행 (메인 루프 차단하지 않음)
                asyncio.create_task(perform_memory_cleanup())
                
            # API 호출 속도 제한 관리
            current_time_ms = time.time()
            # 1초 이내의 API 호출만 유지
            api_call_timestamps = [t for t in api_call_timestamps if current_time_ms - t < 1.0]
            
            
            # 각 사용자의 주문 확인
            for user_id in running_users:
                try:
                    # 사용자의 모든 모니터링 주문 가져오기
                    user_orders = await get_user_monitor_orders(str(user_id))
                    if not user_orders:
                        continue
                        
                    # 사용자별 모니터링 주문 수 로깅 (5분마다)
                    user_monitor_log_key = f"user_monitor_{user_id}"
                    if should_log(user_monitor_log_key):
                        logger.info(f"사용자 {user_id}의 모니터링 주문 수: {len(user_orders)}")
                    
                    # 심볼별 주문 그룹화 (한 번만 현재가를 가져오기 위함)
                    symbol_orders: Dict[str, List[Dict[str, Any]]] = {}
                    
                    for order_id, order_data in user_orders.items():
                        symbol = order_data.get("symbol")
                        if symbol is None:
                            continue
                        if symbol not in symbol_orders:
                            symbol_orders[symbol] = []
                        symbol_orders[symbol].append(order_data)
                    
                    # 각 심볼에 대해 현재가 조회 및 주문 상태 확인

                    for symbol, orders in symbol_orders.items():
                        # 심볼별 주문 수 변화 감지
                        current_order_count = len(orders)
                        order_count_key = f"order_count:{user_id}:{symbol}"
                        previous_count = await redis.get(order_count_key)
                        
                        force_check_all_orders = False
                        if previous_count:
                            previous_count = int(previous_count)
                            if previous_count > current_order_count:
                                logger.warning(f"주문 수 감소 감지: {user_id} {symbol} {previous_count} -> {current_order_count}, 체결된 주문 있을 수 있음")
                                force_check_all_orders = True
                                
                                # 사라진 주문이 체결되었는지 확인하기 위해 별도 태스크 실행
                                asyncio.create_task(check_missing_orders(str(user_id), symbol, orders))

                                # 추가로 최근 체결된 주문도 확인
                                asyncio.create_task(check_recent_filled_orders(str(user_id), symbol))
                        
                        # 현재 주문 수 저장
                        await redis.set(order_count_key, current_order_count, ex=600)  # 10분 TTL
                        
                        position_sides = set(order_data.get("position_side", "") for order_data in orders)
                        try:
                            # 현재가 조회
                            async with get_exchange_context(str(user_id)) as exchange:
                                current_price = await get_current_price(symbol, "1m", exchange)
                                
                                if current_price <= 0:
                                    logger.warning(f"유효하지 않은 현재가: {current_price}, 심볼: {symbol}")
                                    continue
                                    
                                logger.info(f"심볼 {symbol}의 현재가: {current_price}")
                                
                                # 필요 시에만 포지션 정리 작업 수행 (5분마다로 대폭 축소)
                                extended_check_interval = 300  # 5분
                                if force_check_positions and (current_time % extended_check_interval < 60):
                                    # 모니터링되지 않는 고아 주문들 정리용으로만 사용
                                    position_sides = set(order_data.get("position_side", "") for order_data in orders)
                                    for direction in position_sides:
                                        if direction not in ["long", "short"]:
                                            continue
                                        
                                        # 포지션이 없는 경우에만 정리 작업 (API 호출 최소화)
                                        position_exists, _ = await check_position_exists(str(user_id), symbol, direction)
                                        if not position_exists:
                                            await check_and_cleanup_orders(str(user_id), symbol, direction)
                                
                                # 심볼별로 트레일링 스탑 활성화된 방향 확인
                                trailing_sides = set()
                                for direction in ["long", "short"]:
                                    ts_key = f"trailing:user:{user_id}:{symbol}:{direction}"
                                    if await redis.exists(ts_key):
                                        trailing_sides.add(direction)
                                
                                # 주문 정렬 (TP 주문은 tp1 → tp2 → tp3 순서로)
                                def sort_key(order_data):
                                    order_type = order_data.get("order_type", "")
                                    if order_type.startswith("tp"):
                                        # TP 주문: tp1, tp2, tp3 순서
                                        tp_num = order_type[2:] if len(order_type) > 2 else "1"
                                        return (0, int(tp_num) if tp_num.isdigit() else 999)
                                    elif order_type == "sl":
                                        # SL 주문: TP 이후
                                        return (1, 0)
                                    else:
                                        # 기타 주문: 마지막
                                        return (2, 0)
                                
                                sorted_orders = sorted(orders, key=sort_key)
                                
                                # 각 주문 확인 (정렬된 순서로)
                                for order_data in sorted_orders:
                                    order_id = str(order_data.get("order_id", ""))
                                    order_type = str(order_data.get("order_type", ""))
                                    position_side = str(order_data.get("position_side", ""))
                                    current_status = str(order_data.get("status", ""))
                                    
                                    # 모니터링되는 주문 로깅
                                    logger.debug(f"모니터링 주문: {order_id}, 타입: {order_type}, 포지션: {position_side}, 상태: {current_status}")
                                    
                                    # 이미 완료 처리된 주문은 스킵 (filled, canceled, failed)
                                    if current_status in ["filled", "canceled", "failed"]:
                                        continue
                                    
                                    # 주문 상태 변화 감지를 위한 이전 상태 확인
                                    status_key = f"order_status:{order_id}"
                                    previous_status = await redis.get(status_key)
                                    
                                    # 상태가 변경된 경우 강제 체크
                                    status_changed = previous_status and previous_status != current_status
                                    if status_changed:
                                        logger.info(f"주문 상태 변화 감지: {order_id}, {previous_status} -> {current_status}, 강제 체크")
                                    
                                    # 현재 상태를 Redis에 저장 (다음 비교용)
                                    await redis.set(status_key, current_status, ex=3600)  # 1시간 TTL
                                    
                                    # 트레일링 스탑이 활성화된 방향의 TP 주문은 스킵 (SL만 확인)
                                    if position_side in trailing_sides and order_type.startswith("tp"):
                                        logger.info(f"트레일링 스탑 활성화됨 ({position_side}), TP 주문 ({order_id}) 스킵")
                                        continue
                                    
                                    check_needed = False
                                    
                                    # 정기 확인 시간이면 강제로 확인
                                    if force_check_orders:
                                        check_needed = True
                                        #logger.info(f"정기 확인: {order_id}, 타입: {order_type}")
                                    # 주문 수 감소 감지 시 모든 주문 강제 체크
                                    elif force_check_all_orders:
                                        check_needed = True
                                        logger.info(f"주문 수 감소로 인한 강제 체크: {order_id}, 타입: {order_type}")
                                    # 주문 상태가 변경된 경우 강제 체크
                                    elif status_changed:
                                        check_needed = True
                                        logger.info(f"상태 변화로 인한 강제 체크: {order_id}, 타입: {order_type}")
                                    # open 상태 주문은 정기적으로 강제 체크 (실제 상태 확인)
                                    elif current_status == "open" and loop_count % 5 == 0:  # 5번에 1번씩 open 주문 강제 체크
                                        check_needed = True
                                        #logger.info(f"OPEN 주문 정기 체크: {order_id}, 타입: {order_type}")
                                    # TP 주문은 가격이 동적으로 변할 수 있으므로 정기적으로 무조건 체크
                                    elif order_type.startswith("tp") and loop_count % 2 == 0:  # 2번에 1번씩 TP 주문 무조건 체크
                                        check_needed = True
                                        #logger.info(f"TP 주문 정기 무조건 체크: {order_id}, 타입: {order_type} (가격 변동 가능성)")
                                    else:
                                        # TP 주문은 가격 조건 무시하고 더 자주 체크 (가격이 실시간 변할 수 있음)
                                        if order_type.startswith("tp"):
                                            # 가격 조건 무시하고 자주 체크
                                            if loop_count % 4 == 0:  # 4번에 1번씩 추가 체크
                                                check_needed = True
                                                logger.info(f"TP 주문 추가 체크: {order_id}, 타입: {order_type} (가격 조건 무시)")
                                            else:
                                                # 그래도 가격 조건도 확인 (참고용)
                                                check_needed = await should_check_tp_order(order_data, current_price)
                                                tp_price = float(order_data.get("price", "0"))
                                                #logger.debug(f"TP 주문 가격 조건 체크: {order_id}, tp_price: {tp_price}, current_price: {current_price}, check_needed: {check_needed}")
                                        # SL 주문 조건 확인
                                        elif order_type == "sl":
                                            check_needed = await should_check_sl_order(order_data, current_price)
                                            logger.info(f"SL 주문 체크 결과: {order_id}, check_needed: {check_needed}")
                                    
                                    # 주문 상태 확인이 필요한 경우
                                    if check_needed:
                                        # 주문 상태 확인 로깅도 5분마다 한번만
                                        order_log_key = f"order_status_{order_id}"
                                        if should_log(order_log_key):
                                            logger.info(f"주문 상태 확인: {order_id}, 타입: {order_type}")

                                        # 주문 상태 확인 전 포지션 정보 로깅 (5분마다 한번만)
                                        log_key = f"order_check_{user_id}_{symbol}_{position_side}"
                                        if should_log(log_key):
                                            logger.info(f"주문 확인 전 포지션 정보 - user_id: {user_id}, symbol: {symbol}, position_side: {position_side}")
                                            logger.info(f"주문 데이터: {order_data}")
                                        tp_index: int = 0
                                        if order_type.startswith("tp"):
                                            tp_index = int(order_type[2:])
                                        # 주문 확인 간 짧은 딜레이 추가 (서버 부하 방지)
                                        await asyncio.sleep(0.1)
                                        
                                        # order_type 매개변수를 추가하여 호출
                                        try:
                                            order_status = await check_order_status(
                                                user_id=str(user_id),
                                                symbol=symbol,
                                                order_id=order_id,
                                                order_type=order_type
                                            )

                                            # 디버깅을 위한 API 응답 로깅
                                            #logger.debug(f"주문 상태 API 응답: {order_id} -> {order_status}")

                                            # order_status가 None인 경우 체크
                                            if order_status is None:
                                                logger.warning(f"주문 상태 API가 None을 반환: {order_id}")
                                                continue
                                        except Exception as check_error:
                                            logger.error(f"주문 상태 확인 중 오류 발생: {order_id}, 오류: {str(check_error)}")
                                            traceback.print_exc()
                                            continue
                                        
                                        
                                        # API 응답 분석
                                        if isinstance(order_status, dict):
                                            # OrderResponse 형식 (get_order_detail 결과)
                                            if 'status' in order_status:
                                                # enum 객체를 문자열로 변환
                                                status_value = str(order_status['status'].value) if hasattr(order_status['status'], 'value') else str(order_status['status'])
                                                
                                                if status_value.lower() in ['filled', 'closed']:
                                                    status = 'filled'
                                                    filled_sz = order_status.get('filled_amount', order_status.get('amount', '0'))
                                                    
                                                    # TP 주문이 체결되면 브레이크이븐/트레일링스탑 처리는 process_break_even_settings에서 모두 담당
                                                elif status_value.lower() in ['canceled']:
                                                    status = 'canceled'
                                                    filled_sz = order_status.get('filled_amount', '0')
                                                else:
                                                    status = 'open'
                                                    filled_sz = order_status.get('filled_amount', '0')
                                                    
                                                # TP 주문이 체결된 경우 브레이크이븐/트레일링스탑 처리
                                                if status == 'filled' and (order_type.startswith('tp') or order_type.startswith('take_profit')):
                                                    try:
                                                        # position_key 정의
                                                        position_key = f"user:{user_id}:position:{symbol}:{position_side}"
                                                        
                                                        # TP 중복 처리 방지 체크
                                                        tp_already_processed = await redis.hget(position_key, f"get_tp{tp_index}")
                                                        
                                                        if tp_already_processed == "true":
                                                            logger.info(f"TP{tp_index} 이미 처리됨, 중복 처리 방지: {user_id} {symbol} {position_side}")
                                                            continue
                                                        
                                                        #get TP 업데이트
                                                        await redis.hset(position_key, f"get_tp{tp_index}", "true")
                                                        
                                                        # TP 주문 체결 로깅
                                                        price = float(order_data.get("price", "0"))
                                                        filled_amount = float(filled_sz) if filled_sz else 0
                                                        
                                                        # TP 주문 체결 로깅
                                                        try:
                                                            log_order(
                                                                user_id=user_id,
                                                                symbol=symbol,
                                                            action_type='tp_execution',
                                                            position_side=position_side,
                                                            price=price,
                                                            quantity=filled_amount,
                                                            tp_index=tp_index,
                                                                order_id=order_id,
                                                                current_price=current_price
                                                            )
                                                        except Exception as e:
                                                            logger.error(f"TP 주문 체결 로깅 실패: {str(e)}")

                                                        # Lazy import to avoid circular dependency
                                                        from .break_even_handler import process_break_even_settings

                                                        # 사용자 설정에 따른 브레이크이븐/트레일링스탑 처리
                                                        asyncio.create_task(process_break_even_settings(
                                                            user_id=str(user_id),
                                                            symbol=symbol,
                                                            order_type=order_type,
                                                            position_data=order_data
                                                        ))
                                                        
                                                    except Exception as be_error:
                                                        logger.error(f"브레이크이븐/트레일링스탑 처리 실패: {str(be_error)}")
                                                
                                                # 주문 상태 업데이트 (order_type 매개변수 추가)
                                                await update_order_status(
                                                    user_id=str(user_id),
                                                    symbol=symbol,
                                                    order_id=order_id,
                                                    status=status,
                                                    filled_amount=str(filled_sz),
                                                    order_type=order_type
                                                )

                                                # SL 주문이 체결된 경우, 관련 트레일링 스탑 데이터 정리
                                                if status == 'filled' and order_type == 'sl':
                                                    # SL 체결 후 포지션이 실제로 종료되었는지 확인
                                                    asyncio.create_task(verify_and_handle_position_closure(str(user_id), symbol, position_side, "stop_loss"))
                                                    asyncio.create_task(clear_trailing_stop(str(user_id), symbol, position_side))
                                                    
                                                    
                                                    # 알고리즘 주문 - SL 주문 체결 로깅
                                                    price = float(order_status.get('avgPx', order_status.get('px', 0)))
                                                    filled_amount = float(filled_sz) if filled_sz else 0
                                                    
                                                    try:
                                                        log_order(
                                                        user_id=user_id,
                                                        symbol=symbol,
                                                        action_type='sl_execution',
                                                        position_side=position_side,
                                                        price=price,
                                                        quantity=filled_amount,
                                                        order_id=order_id,
                                                            current_price=current_price,
                                                            api_type='okx_algo'
                                                        )
                                                    except Exception as e:
                                                        logger.error(f"SL 주문 체결 로깅 실패: {str(e)}")
                                                
                                                # TP 주문이 체결된 경우 로깅
                                                if status == 'filled' and (order_type.startswith('tp') or order_type.startswith('take_profit')):
                                                    try:
                                                        # TP 레벨 추출
                                                        tp_index = int(order_type[2:]) if len(order_type) > 2 and order_type[2:].isdigit() else 0
                                                        
                                                        # 가격 정보 추출
                                                        price = float(order_status.get('avgPx', order_status.get('px', 0)))
                                                        filled_amount = float(filled_sz) if filled_sz else 0
                                                        
                                                        # OKX API - TP 주문 체결 로깅
                                                        log_order(
                                                            user_id=user_id,
                                                            symbol=symbol,
                                                            action_type='tp_execution',
                                                            position_side=position_side,
                                                            price=price,
                                                            quantity=filled_amount,
                                                            tp_index=tp_index,
                                                            order_id=order_id,
                                                            current_price=current_price,
                                                            api_type='okx_algo'
                                                        )
                                                    except Exception as e:
                                                        logger.error(f"OKX TP 주문 체결 로깅 실패: {str(e)}")
                                            # OKX API 응답 (알고리즘 주문)
                                            elif 'state' in order_status:
                                                state = order_status.get('state', '')
                                                filled_sz = order_status.get('filled_amount', '0')
                                                if filled_sz == '0':
                                                    filled_sz = order_status.get('amount', '0')
                                                    if filled_sz == '0':
                                                        filled_sz = order_status.get('sz', '0')

                                                # 상태 매핑
                                                status_mapping: Dict[str, str] = {
                                                    'filled': 'filled',
                                                    'effective': 'open',
                                                    'canceled': 'canceled',
                                                    'order_failed': 'failed'
                                                }
                                                status = status_mapping.get(state, 'unknown')

                                                # 주문 상태 업데이트 (order_type 매개변수 추가)
                                                await update_order_status(
                                                    user_id=str(user_id),
                                                    symbol=symbol,
                                                    order_id=order_id,
                                                    status=status,
                                                    filled_amount=filled_sz,
                                                    order_type=order_type
                                                )

                                                # SL 주문이 체결된 경우, 관련 트레일링 스탑 데이터 정리
                                                if status == 'filled' and order_type == 'sl':
                                                    await clear_trailing_stop(str(user_id), symbol, position_side)
                                            else:
                                                # dict이지만 'status'나 'state' 키가 없는 경우
                                                logger.warning(f"주문 상태 응답에 'status' 또는 'state' 키가 없음: {order_id} -> {order_status}")
                                                # 기본적으로 canceled로 처리
                                                await update_order_status(
                                                    user_id=str(user_id),
                                                    symbol=symbol,
                                                    order_id=order_id,
                                                    status='canceled',
                                                    filled_amount='0',
                                                    order_type=order_type
                                                )
                                        else:
                                            # dict가 아니거나 예상하지 못한 형식인 경우
                                            logger.warning(f"예상하지 못한 주문 상태 형식: {order_id} -> {order_status}")
                                            # 기본적으로 canceled로 처리
                                            await update_order_status(
                                                user_id=str(user_id),
                                                symbol=symbol,
                                                order_id=order_id,
                                                status='canceled',
                                                filled_amount='0',
                                                order_type=order_type
                                            )
                        except Exception as symbol_error:
                            logger.error(f"심볼 {symbol} 처리 중 오류: {str(symbol_error)}")
                            traceback.print_exc()
                
                except Exception as user_error:
                    logger.error(f"사용자 {user_id} 처리 중 오류: {str(user_error)}")
                    traceback.print_exc()
            
            # 처리 간격 설정 (초)
            await asyncio.sleep(MONITOR_INTERVAL)
            
            # 연속 오류 카운터 초기화 (성공적인 반복)
            consecutive_errors = 0
            
        except Exception as loop_error:
            error_type = type(loop_error).__name__
            error_traceback = traceback.format_exc()
            logger.error(f"모니터링 루프 오류: {str(loop_error)}")
            logger.error(f"에러 타입: {error_type}, 상세 내용: {error_traceback}")
            
            # 연속 오류 증가
            consecutive_errors += 1
            
            # Redis 연결 복구 시도
            try:
                logger.info("Redis 연결 상태 확인 중...")
                if not await check_redis_connection():
                    logger.warning("Redis 연결 끊김 감지, 재연결 시도...")
                    # Redis 클라이언트 재연결
                    for retry in range(3):
                        try:
                            logger.info(f"Redis 재연결 시도 {retry+1}/3...")
                            if await reconnect_redis():
                                logger.info("Redis 재연결 성공")
                                break
                            await asyncio.sleep(1)
                        except Exception as retry_error:
                            logger.error(f"Redis 재연결 시도 {retry+1}/3 실패: {str(retry_error)}")
                            if retry < 2:  # 마지막 시도가 아니면 대기
                                await asyncio.sleep(2)
            except Exception as redis_error:
                logger.error(f"Redis 재연결 실패: {str(redis_error)}")
                logger.error(f"Redis 에러 상세: {traceback.format_exc()}")
            
            # 지수 백오프로 대기 시간 계산 (최대 60초까지)
            backoff_time = min(5 * 2 ** (consecutive_errors - 1), 60)
            logger.warning(f"연속 오류 {consecutive_errors}회 발생, {backoff_time}초 후 재시도")
            
            # 오류 발생 시 지수 백오프로 대기 후 재시도
            await asyncio.sleep(backoff_time)


async def start_monitoring():
    """
    모니터링 서비스를 시작합니다. 오류 발생 시 재시작 로직 포함.
    """
    restart_attempts = 0
    restart_delay = 5  # 초기 재시작 딜레이 (초)
    
    while restart_attempts < MAX_RESTART_ATTEMPTS:
        try:
            logger.info(f"모니터링 서비스 시작 (시도 {restart_attempts + 1}/{MAX_RESTART_ATTEMPTS})")
            
            # Redis 연결 상태 확인
            try:
                logger.info("Redis 서버 연결 확인 중...")
                # 직접 새로운 check_redis_connection 함수 사용
                redis_connected = False
                for retry in range(3):
                    try:
                        logger.info(f"Redis 연결 확인 시도 {retry+1}/3...")
                        if await check_redis_connection():
                            logger.info("Redis 연결 확인됨")
                            redis_connected = True
                            break
                        else:
                            logger.warning(f"Redis 연결 실패, 재연결 시도 {retry+1}/3...")
                            if await reconnect_redis():
                                logger.info("Redis 재연결 성공")
                                redis_connected = True
                                break
                        # 마지막 시도가 아니면 대기
                        if retry < 2:
                            await asyncio.sleep(2)
                    except Exception as retry_error:
                        logger.error(f"Redis 연결 확인 시도 {retry+1}/3 실패: {str(retry_error)}")
                        # 마지막 시도가 아니면 대기
                        if retry < 2:
                            await asyncio.sleep(2)
                
                if not redis_connected:
                    logger.warning("Redis 연결 시도 모두 실패, 계속 진행 시도")
            except Exception as redis_error:
                error_type = type(redis_error).__name__
                error_msg = str(redis_error)
                error_trace = traceback.format_exc()
                logger.error(f"Redis 연결 오류: {error_msg} (타입: {error_type})")
                logger.error(f"오류 상세 정보: {error_trace}")
                # Redis 연결 실패해도 계속 시도
            
            # 모니터링 루프 실행
            await monitor_orders_loop()
            
            # 여기에 도달하면 정상 종료된 것 (무한 루프이므로 일반적으로는 도달하지 않음)
            logger.info("모니터링 서비스 정상 종료")
            break
            
        except Exception as e:
            restart_attempts += 1
            error_type = type(e).__name__
            error_trace = traceback.format_exc()
            logger.error(f"모니터링 서비스 실패 ({restart_attempts}/{MAX_RESTART_ATTEMPTS}): {str(e)}")
            logger.error(f"에러 타입: {error_type}, 상세 정보:\n{error_trace}")
            
            # 다음 재시작 시도 전에 자원 정리
            try:
                # Redis 연결 정리 및 재연결
                for retry in range(3):
                    try:
                        logger.info(f"재시작 전 Redis 재연결 시도 {retry+1}/3...")
                        if await reconnect_redis():
                            logger.info("Redis 재연결 성공")
                            break
                        # 마지막 시도가 아니면 대기
                        if retry < 2:
                            await asyncio.sleep(2)
                    except Exception as retry_error:
                        logger.error(f"Redis 재연결 시도 {retry+1}/3 실패: {str(retry_error)}")
                        # 마지막 시도가 아니면 대기
                        if retry < 2:
                            await asyncio.sleep(2)
                
                # 가비지 컬렉션 강제 실행
                gc.collect()
                
                # 메모리 사용량 로깅
                process = psutil.Process()
                memory_info = process.memory_info()
                logger.info(f"재시작 전 메모리 사용량: {memory_info.rss / 1024 / 1024:.2f} MB")
                
                # 텔레그램으로 관리자에게 알림 (선택적)
                try:
                    await send_telegram_message(
                        message=f"⚠️ 모니터링 서비스 오류 발생\n재시작 시도: {restart_attempts}/{MAX_RESTART_ATTEMPTS}\n오류: {str(e)}\n타입: {error_type}\n서버 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                        okx_uid="1709556958",
                        debug=True
                    )
                except Exception as telegram_error:
                    logger.error(f"텔레그램 알림 전송 실패: {str(telegram_error)}")
            except Exception as cleanup_error:
                logger.error(f"재시작 전 자원 정리 오류: {str(cleanup_error)}")
                logger.error(f"자원 정리 오류 상세: {traceback.format_exc()}")
            
            # 지수 백오프 방식으로 대기 시간 증가 (최대 5분까지)
            restart_delay = min(restart_delay * 2, 300)
            logger.info(f"{restart_delay}초 후 서비스 재시작 시도...")
            await asyncio.sleep(restart_delay)
    
    # 최대 재시작 시도 횟수 초과
    if restart_attempts >= MAX_RESTART_ATTEMPTS:
        logger.critical(f"최대 재시작 시도 횟수({MAX_RESTART_ATTEMPTS})를 초과하여 모니터링 서비스를 종료합니다.")
        # 마지막 텔레그램 알림
        try:
            await send_telegram_message(
                message=f"🚨 모니터링 서비스 강제 종료\n최대 재시작 시도 횟수({MAX_RESTART_ATTEMPTS})를 초과했습니다.\n수동 개입이 필요합니다.\n서버 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                okx_uid="1709556958",
                debug=True
            )
        except Exception as final_error:
            logger.error(f"최종 텔레그램 알림 전송 실패: {str(final_error)}")
        
        # 프로세스 종료 코드
        sys.exit(1)


def exit_handler():
    """
    프로그램 종료 시 정리 작업을 수행합니다.
    """
    logger.info("프로그램 종료, 자원 정리 중...")
    try:
        # 여기에 필요한 정리 로직 추가
        logger.info("자원 정리 완료, 프로그램 종료")
    except Exception as e:
        logger.error(f"종료 처리 중 오류: {str(e)}")


if __name__ == "__main__":
    """
    독립 실행 시 엔트리포인트
    """
    import atexit
    import signal

    # 종료 핸들러 등록
    atexit.register(exit_handler)
    
    # 시그널 핸들러 설정
    def signal_handler(sig, frame):
        logger.info(f"시그널 {sig} 수신, 프로그램 종료...")
        # 여기서 cleanup 로직이나 종료 알림 등을 추가할 수 있음
        sys.exit(0)
    
    # SIGINT(Ctrl+C), SIGTERM 핸들러 등록
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # 필수 라이브러리 가져오기
    import sys

    import psutil

    # 프로세스 우선순위 설정 (선택적)
    try:
        import os
        if hasattr(os, 'nice'):
            os.nice(10)  # 낮은 우선순위 설정 (Linux/Mac)
    
    except Exception as e:
        logger.warning(f"프로세스 우선순위 설정 실패: {str(e)}")
    
    # 메모리 제한 설정 (선택적)
    try:
        if sys.platform != 'win32':  # Unix/Linux/Mac
            import resource

            # 메모리 제한 설정
            rsrc = resource.RLIMIT_AS
            soft, hard = resource.getrlimit(rsrc)
            
            # 하드 제한이 무제한(-1)인 경우 2GB로 설정
            if hard == -1:
                hard = 2 * 1024 * 1024 * 1024
            
            # 소프트 제한을 하드 제한의 80%로 설정 (또는 최대 2GB)
            target_soft = min(hard, 2 * 1024 * 1024 * 1024)
            target_soft = int(target_soft * 0.8)  # 하드 제한의 80%
            
            # 현재 소프트 제한이 이미 더 낮은 경우 변경하지 않음
            if soft == -1 or soft > target_soft:
                resource.setrlimit(rsrc, (target_soft, hard))
                logger.info(f"메모리 제한 설정: {target_soft / (1024 * 1024 * 1024):.2f}GB (소프트 제한), {hard / (1024 * 1024 * 1024):.2f}GB (하드 제한)")
            else:
                logger.info(f"현재 메모리 제한 유지: {soft / (1024 * 1024 * 1024):.2f}GB (소프트 제한), {hard / (1024 * 1024 * 1024):.2f}GB (하드 제한)")
    except Exception as e:
        logger.warning(f"메모리 제한 설정 실패: {str(e)}")
        
    # 기본 모니터링 정보 출력
    process = psutil.Process()
    logger.info(f"시작 시 메모리 사용량: {process.memory_info().rss / 1024 / 1024:.2f} MB")
    logger.info(f"CPU 코어: {psutil.cpu_count()} / 논리 코어: {psutil.cpu_count(logical=True)}")
    
    # 메인 루프 시작
    try:
        asyncio.run(start_monitoring())
    except KeyboardInterrupt:
        logger.info("사용자가 프로그램을 중단함 (KeyboardInterrupt)")
    except Exception as e:
        logger.critical(f"프로그램 실행 중 치명적인 오류 발생: {str(e)}")
        traceback.print_exc()

