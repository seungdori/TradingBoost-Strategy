# src/trading/monitoring/order_monitor.py

"""
주문 상태 모니터링 모듈
"""

import asyncio
import json
import time
import traceback
from datetime import datetime
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from HYPERRSI.src.api.dependencies import get_exchange_context
from shared.database.redis_helper import get_redis_client

# Lazy imports to avoid circular dependencies
if TYPE_CHECKING:
    from HYPERRSI.src.api.routes.order.models import ClosePositionRequest
    from HYPERRSI.src.api.routes.order.order import (
        close_position,
        get_algo_order_info,
        get_order_detail,
    )
from shared.logging import get_logger, log_order
from shared.utils import contracts_to_qty

# Lazy import to avoid circular dependency - import at usage point
from .position_validator import (
    check_and_cleanup_orders,
    check_position_exists,
    verify_and_handle_position_closure,
)
from .telegram_service import get_identifier, send_telegram_message
from .utils import ORDER_STATUS_CACHE_TTL, get_actual_order_type, is_true_value, order_status_cache

logger = get_logger(__name__)


# Module-level attribute for backward compatibility
def __getattr__(name):
    if name == "redis_client":
        return get_redis_client()
    raise AttributeError(f"module has no attribute {name}")


async def check_missing_orders(user_id: str, symbol: str, current_orders: List) -> None:
    """
    사라진 주문들이 체결되었는지 확인하여 알림을 보냅니다.

    Args:
        user_id: 사용자 ID
        symbol: 거래 심볼
        current_orders: 현재 남아있는 주문 목록
    """
    try:
        redis = await get_redis_client()
        logger.info(f"사라진 주문 체크 시작: {user_id} {symbol}")
        
        # 현재 남아있는 주문 ID 목록
        current_order_ids = set(order_data.get("order_id") for order_data in current_orders)
        
        # 이전에 저장된 주문 ID 목록 조회
        prev_orders_key = f"prev_orders:{user_id}:{symbol}"
        prev_order_ids_str = await redis.get(prev_orders_key)
        
        if prev_order_ids_str:
            prev_order_ids = set(json.loads(prev_order_ids_str))
            
            # 사라진 주문 ID들 찾기
            missing_order_ids = prev_order_ids - current_order_ids
            
            if missing_order_ids:
                logger.info(f"사라진 주문 발견: {missing_order_ids}")
                
                # 각 사라진 주문의 실제 상태 확인
                for order_id in missing_order_ids:
                    try:
                        # 완료된 주문 저장소에서 먼저 확인
                        okx_uid = await get_identifier(str(user_id))
                        completed_key = f"completed:user:{okx_uid}:{symbol}:order:{order_id}"
                        completed_data = await redis.hgetall(completed_key)
                        
                        if completed_data:
                            # 이미 완료 저장소에 있으면 알림 이미 전송됨
                            logger.info(f"주문 {order_id}는 이미 완료 처리됨")
                            continue
                        
                        # 실제 거래소에서 주문 상태 확인
                        logger.info(f"사라진 주문 실제 상태 확인: {order_id}")
                        
                        # TP 주문은 일반 주문으로 확인
                        order_status = await check_order_status(
                            user_id=user_id,
                            symbol=symbol,
                            order_id=order_id,
                            order_type="tp"  # 기본값, 실제 타입은 API에서 반환
                        )
                        
                        if isinstance(order_status, dict) and 'status' in order_status:
                            status_value = str(order_status['status'].value) if hasattr(order_status['status'], 'value') else str(order_status['status'])
                            
                            if status_value.lower() in ['filled', 'closed']:
                                logger.info(f"사라진 주문 {order_id}가 체결되었음을 확인, 알림 전송")
                                
                                # 주문 타입 추정 (order_id에서 추출하거나 API 응답에서 확인)
                                filled_amount = order_status.get('filled_amount', order_status.get('amount', '0'))
                                
                                # update_order_status 호출하여 알림 전송
                                await update_order_status(
                                    user_id=user_id,
                                    symbol=symbol,
                                    order_id=order_id,
                                    status='filled',
                                    filled_amount=str(filled_amount),
                                    order_type='tp'  # 추정값
                                )
                            elif status_value.lower() in ['canceled']:
                                logger.info(f"사라진 주문 {order_id}가 취소되었음을 확인 (조용히 처리)")
                            else:
                                logger.warning(f"사라진 주문 {order_id}의 예상치 못한 상태: {status_value}")
                                
                    except Exception as order_error:
                        logger.error(f"사라진 주문 {order_id} 상태 확인 중 오류: {str(order_error)}")
                        continue
        else:
            # 첫 번째 실행이거나 이전 데이터가 없는 경우
            logger.debug(f"이전 주문 데이터 없음, 현재 주문 목록 저장: {current_order_ids}")
            
            # 주문 수가 감소했다면 최근 완료된 주문들을 확인
            current_order_count = len(current_orders)
            if current_order_count < 3:  # 정상적으로는 3개 주문이 있어야 함
                logger.info(f"주문 수 부족 감지 ({current_order_count}/3), 최근 완료된 주문 확인")
                asyncio.create_task(check_recent_filled_orders(user_id, symbol))
        
        # 현재 주문 ID 목록 저장 (다음 비교용)
        try:
            current_order_ids_str = json.dumps(list(current_order_ids))
            await redis.set(prev_orders_key, current_order_ids_str, ex=3600)  # 1시간 TTL
        except Exception as save_error:
            logger.error(f"주문 ID 목록 저장 중 오류: {str(save_error)}")
        
    except Exception as e:
        logger.error(f"사라진 주문 체크 중 오류: {str(e)}")
        traceback.print_exc()


async def check_recent_filled_orders(user_id: str, symbol: str) -> None:
    """
    최근 체결된 주문들을 확인하여 놓친 알림이 있는지 체크합니다.
    """
    try:
        redis = await get_redis_client()
        logger.info(f"최근 체결된 주문 확인 시작: {user_id} {symbol}")
        
        # 거래소에서 최근 체결된 주문들 조회
        async with get_exchange_context(str(user_id)) as exchange:
            # 최근 24시간 주문 내역 조회
            orders = await exchange.fetch_closed_orders(symbol, limit=50)
            
            # 최근 1시간 이내에 체결된 TP 주문들 찾기
            current_time = time.time() * 1000  # 밀리초 단위
            one_hour_ago = current_time - (60 * 60 * 1000)  # 1시간 전
            
            recent_tp_orders = []
            for order in orders:
                if (order.get('timestamp', 0) > one_hour_ago and 
                    order.get('status') == 'closed' and
                    order.get('clientOrderId', '').find('e847386590ce4dBC') != -1):  # 우리 주문 식별자
                    recent_tp_orders.append(order)
            
            logger.info(f"최근 1시간 내 체결된 주문 수: {len(recent_tp_orders)}")
            
            # 각 체결된 주문이 이미 알림 처리되었는지 확인
            okx_uid = await get_identifier(str(user_id))
            for order in recent_tp_orders:
                order_id = order.get('id')
                
                # 완료된 주문 저장소에서 확인
                completed_key = f"completed:user:{okx_uid}:{symbol}:order:{order_id}"
                completed_data = await redis.hgetall(completed_key)
                
                if not completed_data:
                    # 완료 저장소에 없다면 놓친 주문일 가능성
                    logger.warning(f"놓친 체결 주문 발견: {order_id}")
                    
                    # 주문 정보로부터 TP 레벨 추정
                    tp_level = "1"  # 기본값
                    if order.get('reduceOnly') and order.get('type') == 'limit':
                        # TP 주문으로 추정, 레벨은 가격으로 판단하거나 기본값 사용
                        
                        # 알림 전송
                        filled_amount = order.get('filled', order.get('amount', 0))
                        await update_order_status(
                            user_id=user_id,
                            symbol=symbol,
                            order_id=order_id,
                            status='filled',
                            filled_amount=str(filled_amount),
                            order_type=f'tp{tp_level}'
                        )
                        
                        logger.info(f"놓친 주문 {order_id} 알림 처리 완료")
                        
    except Exception as e:
        logger.error(f"최근 체결된 주문 확인 중 오류: {str(e)}")
        traceback.print_exc()


async def check_order_status(user_id: str, symbol: str, order_id: str, order_type: Optional[str] = None) -> Dict[Any, Any]:
    """
    거래소 API를 통해 주문 상태를 확인합니다.
    
    Args:
        user_id: 사용자 ID (텔레그램 ID 또는 OKX UID)
        symbol: 거래 심볼
        order_id: 주문 ID
        order_type: 주문 유형 ('tp1', 'tp2', 'tp3', 'sl' 등)
        
    Returns:
        Dict: 주문 상태 정보, 오류 발생 시 주문 취소 상태 반환
    """
    try:
        # user_id를 OKX UID로 변환
        okx_uid = await get_identifier(str(user_id))
        
        # 캐시 키 생성
        cache_key = f"{okx_uid}:{symbol}:{order_id}"
        current_time = time.time()
        
        # 캐시된 결과가 있으면 반환
        if cache_key in order_status_cache:
            cached_time, cached_result = order_status_cache[cache_key]
            if current_time - cached_time < ORDER_STATUS_CACHE_TTL:
                #logger.debug(f"캐시된 주문 상태 사용: {order_id} (캐시 유효 시간: {ORDER_STATUS_CACHE_TTL - (current_time - cached_time):.1f}초)")
                return dict(cached_result)
            
        # TP 주문(tp1, tp2, tp3)은 일반 리밋 주문으로 처리
        is_algo = True
        
        # 주문 유형에 따라 API 호출 방식 결정
        if order_type and (order_type.startswith('tp') or order_type.startswith('take_profit')):
            is_algo = False  # TP 주문은 일반 주문(limit)
            logger.debug(f"TP 주문({order_type}) 조회: {order_id}, 일반 주문 API 사용")
        else:
            # SL 주문 등은 알고리즘 주문
            is_algo = True
            logger.debug(f"SL 주문 조회: {order_id}, 알고리즘 주문 API 사용")
        
        try:
            # src/api/routes/order.py의 get_order_detail 함수 사용
            response: Any
            if is_algo:
                response = await get_algo_order_info(
                    user_id=str(okx_uid),
                    symbol=symbol,
                    order_id=order_id,
                    algo_type="trigger"
                )
            else:
                response = await get_order_detail(
                    order_id=order_id,
                    user_id=str(okx_uid),
                    symbol=symbol,
                    is_algo=is_algo,
                    algo_type=""
                )
            
            if response:
                # OrderResponse 모델을 딕셔너리로 변환
                if hasattr(response, "model_dump"):
                    result = response.model_dump()
                elif hasattr(response, "dict"):  # 하위 호환성 유지
                    result = response.dict()
                else:
                    result = dict(response)

                # 결과 캐싱
                order_status_cache[cache_key] = (current_time, result)
                return dict(result)
                
        except Exception as detail_error:
            # 404 오류이거나 '찾을 수 없음' 오류인 경우
            error_str = str(detail_error).lower()
            if "404" in error_str or "찾을 수 없습니다" in error_str or "not found" in error_str:
                logger.info(f"주문을 찾을 수 없음 (취소됨/만료됨): {order_id}, 오류: {str(detail_error)}")
                # 취소된 주문으로 처리
                result = {
                    "status": "canceled",
                    "order_id": order_id,
                    "symbol": symbol,
                    "filled_amount": "0",
                    "canceled_reason": "not_found_in_exchange"
                }
                # 결과 캐싱
                order_status_cache[cache_key] = (current_time, result)
                return result
            else:
                logger.warning(f"get_order_detail 호출 실패: {str(detail_error)}")
            
            # 직접 거래소 API 호출로 폴백
            try:
                async with get_exchange_context(str(okx_uid)) as exchange:
                    try:
                        if is_algo:
                            # 알고리즘 주문 조회 - 명시적으로 state 파라미터 추가
                            params = {
                                'ordType': 'conditional', 
                                'algoId': order_id,
                                'instId': symbol,
                                'state': 'live,effective,canceled,order_failed,filled'  # 모든 가능한 상태
                            }
                            
                            # API 호출 전 필요한 파라미터가 있는지 확인
                            if not order_id or not symbol:
                                logger.warning(f"알고리즘 주문 조회 필수 파라미터 누락: order_id={order_id}, symbol={symbol}")
                                result = {
                                    "status": "canceled",
                                    "order_id": order_id,
                                    "symbol": symbol,
                                    "filled_amount": "0",
                                    "canceled_reason": "missing_parameters"
                                }
                                # 결과 캐싱
                                order_status_cache[cache_key] = (current_time, result)
                                return result
                            
                            # 파라미터를 로깅하여 디버깅에 도움을 줌
                            logger.debug(f"알고리즘 주문 조회 파라미터: {params}")
                            
                            algo_orders = await exchange.privateGetTradeOrdersAlgoHistory(params)
                            
                            if algo_orders and 'data' in algo_orders and len(algo_orders['data']) > 0:
                                result = algo_orders['data'][0]
                                # 결과 캐싱
                                order_status_cache[cache_key] = (current_time, result)
                                return dict(result)
                            else:
                                # 주문이 없는 경우 취소된 것으로 처리
                                logger.info(f"알고리즘 주문이 존재하지 않음 (취소됨): {order_id}")
                                result = {
                                    "status": "canceled",
                                    "order_id": order_id,
                                    "symbol": symbol,
                                    "filled_amount": "0",
                                    "canceled_reason": "not_found_in_exchange"
                                }
                                # 결과 캐싱
                                order_status_cache[cache_key] = (current_time, result)
                                return result
                        else:
                            # 일반 주문 조회
                            try:
                                order_info = await exchange.fetch_order(order_id, symbol)
                                # 결과 캐싱
                                order_status_cache[cache_key] = (current_time, order_info)
                                return dict(order_info)
                            except Exception as fetch_error:
                                error_str = str(fetch_error).lower()
                                # 주문이 찾을 수 없는 경우 취소된 것으로 처리
                                if "not found" in error_str or "존재하지 않" in error_str or "찾을 수 없" in error_str:
                                    logger.info(f"일반 주문이 존재하지 않음 (취소됨): {order_id}")
                                    result = {
                                        "status": "canceled",
                                        "order_id": order_id,
                                        "symbol": symbol,
                                        "filled_amount": "0",
                                        "canceled_reason": "not_found_in_exchange"
                                    }
                                    # 결과 캐싱
                                    order_status_cache[cache_key] = (current_time, result)
                                    return result
                                raise
                    except Exception as api_error:
                        # API 호출 오류인 경우
                        error_str = str(api_error).lower()
                        if "50015" in error_str and "algoId or state is required" in error_str:
                            logger.info(f"알고리즘 주문 조회 파라미터 오류 - 주문이 이미 취소됨: {order_id}")
                            result = {
                                "status": "canceled",
                                "order_id": order_id,
                                "symbol": symbol,
                                "filled_amount": "0",
                                "canceled_reason": "api_parameter_error"
                            }
                            # 결과 캐싱
                            order_status_cache[cache_key] = (current_time, result)
                            return result
                        else:
                            logger.error(f"거래소 API 직접 호출 실패: {str(api_error)}")
                            raise
            except Exception as exchange_error:
                logger.error(f"거래소 컨텍스트 생성 중 오류: {str(exchange_error)}")
                # 장애 발생 시에도 안전하게 취소된 것으로 처리
                result = {
                    "status": "canceled",
                    "order_id": order_id,
                    "symbol": symbol,
                    "filled_amount": "0", 
                    "canceled_reason": "exchange_error"
                }
                # 결과 캐싱
                order_status_cache[cache_key] = (current_time, result)
                return result
            
        # 모든 방법을 시도했는데도 주문 정보를 가져오지 못한 경우
        result = {
            "status": "canceled",
            "order_id": order_id,
            "symbol": symbol,
            "filled_amount": "0",
            "canceled_reason": "all_retrieval_methods_failed"
        }
        # 결과 캐싱
        order_status_cache[cache_key] = (current_time, result)
        return result
    except Exception as e:
        logger.error(f"주문 상태 확인 중 예외 발생 (user_id:{okx_uid}, symbol:{symbol}, order_id:{order_id}, order_type:{order_type}): {str(e)}")
        traceback.print_exc()
        # 오류 발생 시 기본값으로 취소 상태 반환 (안전한 방식)
        result = {
            "status": "canceled", 
            "error": str(e),
            "order_id": order_id,
            "symbol": symbol,
            "filled_amount": "0",
            "canceled_reason": "exception"
        }
        # 결과 캐싱
        order_status_cache[cache_key] = (current_time, result)
        return result


async def update_order_status(user_id: str, symbol: str, order_id: str, status: str, filled_amount: str = "0", order_type: Optional[str] = None) -> None:
    """
    주문 상태를 업데이트합니다.
    
    Args:
        user_id: 사용자 ID (텔레그램 ID 또는 OKX UID)
        symbol: 거래 심볼
        order_id: 주문 ID
        status: 새 상태
        filled_amount: 체결된 수량
    """
    try:
        redis = await get_redis_client()
        # user_id를 OKX UID로 변환
        okx_uid = await get_identifier(str(user_id))
        
        monitor_key = f"monitor:user:{okx_uid}:{symbol}:order:{order_id}"
        order_data = await redis.hgetall(monitor_key)
        
        if not order_data:
            logger.warning(f"주문 데이터를 찾을 수 없음: {monitor_key}")
            await redis.delete(monitor_key)
            return
        
        # 이미 같은 상태면 업데이트 및 알림 건너뛰기
        current_status = order_data.get("status", "")
        if current_status == status:
            #logger.info(f"주문 상태가 이미 '{status}'입니다. 업데이트 및 알림 건너뛰기: {order_id}")
            return
            
        # 상태 업데이트
        now = datetime.now()
        kr_time = now 
        contracts_amount = float(order_data.get("contracts_amount", "0"))
        filled_contracts = float(filled_amount or "0")
        remain_contracts = max(0, contracts_amount - filled_contracts)
        
        update_data = {
            "status": status,
            "filled_contracts_amount": str(filled_contracts),
            "remain_contracts_amount": str(remain_contracts),
            "last_updated_time": str(int(now.timestamp())),
            "last_updated_time_kr": kr_time.strftime("%Y-%m-%d %H:%M:%S")
        }
        
        # 완료된 주문 처리 (체결, 취소, 실패 등)
        final_statuses = ["filled", "canceled", "failed"]
        if status in final_statuses:
            # 완료된 주문은 completed 키로 이동
            completed_key = f"completed:user:{okx_uid}:{symbol}:order:{order_id}"
            
            # 현재 모니터링 데이터에 업데이트 데이터 적용
            updated_order_data = {**order_data, **update_data}
            
            # 포지션 정보(진입가격 등)가 있다면 포함시키기
            position_side = order_data.get("position_side", "")
            if position_side:
                try:
                    position_key = f"user:{okx_uid}:position:{symbol}:{position_side}"
                    position_data = await redis.hgetall(position_key)
                    
                    # 포지션 정보가 있으면 주요 데이터 추가
                    if position_data:
                        entry_price = position_data.get("entry_price", "0")
                        leverage = position_data.get("leverage", "1")
                        is_hedge = is_true_value(position_data.get("is_hedge", "false"))
                        
                        # completed 주문 데이터에 포지션 정보 추가
                        updated_order_data["entry_price"] = entry_price
                        updated_order_data["leverage"] = leverage
                        updated_order_data["is_hedge"] = str(is_hedge)
                        
                        # 수익률 정보 계산 및 추가
                        if status == "filled":
                            try:
                                price = float(order_data.get("price", "0"))
                                entry_price_float = float(entry_price)
                                leverage_float = float(leverage)
                                
                                if entry_price_float > 0:
                                    if position_side == "long":
                                        pnl_percent = ((price / entry_price_float) - 1) * 100
                                    else:  # short
                                        pnl_percent = ((entry_price_float / price) - 1) * 100
                                    
                                    # 수익률 정보 저장
                                    updated_order_data["pnl_percent"] = str(pnl_percent)
                                    
                                    # 레버리지 적용 수익률
                                    if leverage_float > 1:
                                        leveraged_pnl = pnl_percent * leverage_float
                                        updated_order_data["leveraged_pnl_percent"] = str(leveraged_pnl)
                            except Exception as pnl_error:
                                logger.error(f"수익률 계산 중 오류: {str(pnl_error)}")
                except Exception as e:
                    logger.warning(f"포지션 정보 조회 중 오류 발생: {str(e)}")
            
            # completed 키에 데이터 저장
            await redis.hset(completed_key, mapping=updated_order_data)
            
            # 2주일(14일) TTL 설정
            await redis.expire(completed_key, 60 * 60 * 24 * 14)  # 14일 = 1,209,600초
            
            # 기존 모니터링 키 삭제 전 마지막 확인
            logger.info(f"주문 {order_id} 삭제 전 최종 상태 확인")
            try:
                # 삭제 직전 실제 거래소 상태 한 번 더 확인
                final_check_status = await check_order_status(
                    user_id=user_id,
                    symbol=symbol, 
                    order_id=order_id,
                    order_type=order_data.get("order_type", "")
                )
                
                if isinstance(final_check_status, dict) and 'status' in final_check_status:
                    final_status_value = str(final_check_status['status'].value) if hasattr(final_check_status['status'], 'value') else str(final_check_status['status'])
                    
                    if final_status_value.lower() in ['filled', 'closed'] and status != 'filled':
                        logger.warning(f"삭제 직전 체결 발견: {order_id}, Redis상태: {status}, 실제상태: {final_status_value}")
                        
                        # 체결된 주문이면 알림만 처리 (재귀 호출 방지)
                        filled_amount = final_check_status.get('filled_amount', final_check_status.get('amount', '0'))
                        logger.info(f"삭제 직전 체결 알림 직접 처리: {order_id}")
                        
                        # 알림 처리를 위한 필요한 정보 구성
                        order_type = get_actual_order_type(order_data)
                        
                        # 디버깅을 위한 상세 로깅
                        logger.info(f"주문 데이터 확인 - order_id: {order_id}, 실제 order_type: {order_type}")
                        logger.debug(f"Redis order_data - 원본 order_type: {order_data.get('order_type')}, order_name: {order_data.get('order_name')}")
                        if order_data.get('order_type') in ["limit", "market"]:
                            logger.info(f"주문 방식 {order_data.get('order_type')}에서 order_name으로 실제 타입 확인: {order_type}")
                        
                        # 그래도 unknown인 경우 가격으로 TP 레벨 추측
                        if order_type == "unknown" and "price" in order_data:
                            try:
                                order_price = float(order_data.get("price", "0"))
                                position_side = order_data.get("position_side", "unknown")
                                
                                # 포지션 정보에서 TP 가격들 가져오기
                                position_key = f"user:{okx_uid}:position:{symbol}:{position_side}"
                                position_data = await redis.hgetall(position_key)
                                
                                if position_data:
                                    tp1_price = float(position_data.get("tp1_price", "0"))
                                    tp2_price = float(position_data.get("tp2_price", "0"))
                                    tp3_price = float(position_data.get("tp3_price", "0"))
                                    
                                    # 가격 비교로 TP 레벨 결정 (소수점 둘째자리까지 비교)
                                    if abs(order_price - tp1_price) < 0.01:
                                        order_type = "tp1"
                                        logger.info(f"가격 비교로 TP1 확인: {order_price} ≈ {tp1_price}")
                                    elif abs(order_price - tp2_price) < 0.01:
                                        order_type = "tp2"
                                        logger.info(f"가격 비교로 TP2 확인: {order_price} ≈ {tp2_price}")
                                    elif abs(order_price - tp3_price) < 0.01:
                                        order_type = "tp3"
                                        logger.info(f"가격 비교로 TP3 확인: {order_price} ≈ {tp3_price}")
                            except Exception as e:
                                logger.error(f"TP 레벨 추측 중 오류: {str(e)}")
                        
                        position_side = order_data.get("position_side", "unknown")
                        price = float(order_data.get("price", "0"))
                        
                        # TP 알림의 경우 중복 방지 체크
                        if order_type and isinstance(order_type, str) and order_type.startswith("tp"):
                            # 15분 체크 (기존 로직과 동일)
                            current_time_ms = int(time.time() * 1000)
                            order_fill_time = None
                            for time_field in ['updated_at', 'lastUpdateTimestamp', 'lastTradeTimestamp', 'fillTime']:
                                if time_field in final_check_status:
                                    order_fill_time = final_check_status[time_field]
                                    break
                            
                            if order_fill_time:
                                if order_fill_time < 1000000000000:
                                    order_fill_time *= 1000
                                time_diff_minutes = (current_time_ms - order_fill_time) / 1000 / 60
                                if time_diff_minutes > 15:
                                    logger.warning(f"삭제 직전 TP{order_type[2:]} 체결이 {time_diff_minutes:.1f}분 전이므로 알림 스킵")
                                    return
                                else:
                                    logger.info(f"삭제 직전 TP{order_type[2:]} 체결 확인 - {time_diff_minutes:.1f}분 전 (15분 이내이므로 알림 전송)")
                            else:
                                logger.info(f"삭제 직전 TP{order_type[2:]} 체결 시간 정보 없음 - 알림 전송 진행")
                        
                        # 직접 알림 메시지 구성 및 전송
                        if order_type and isinstance(order_type, str) and order_type.startswith("tp"):
                            tp_level_str = order_type[2:] if len(order_type) > 2 else "1"
                            title = f"🟢 익절(TP{tp_level_str}) 체결 완료"
                        elif order_type == "sl":
                            title = f"🔴 손절(SL) 체결 완료"
                        else:
                            title = f"✅ 주문 체결 완료"
                        
                        message = (
                            f"{title}\n"
                            f"━━━━━━━━━━━━━━━\n"
                            f"심볼: {symbol}\n"
                            f"방향: {position_side.upper()}\n"
                            f"체결가격: {round(float(price), 3)}\n"
                        )
                        
                        await send_telegram_message(message, okx_uid=okx_uid)
                        logger.info(f"삭제 직전 체결 알림 직접 전송 완료: {order_id}")
                        
                    elif final_status_value.lower() in ['canceled']:
                        logger.info(f"삭제 직전 확인 - 취소된 주문: {order_id} (조용히 삭제)")
                        
            except Exception as final_check_error:
                logger.error(f"삭제 직전 최종 확인 중 오류: {order_id}, {str(final_check_error)}")
            
            # 기존 모니터링 키 삭제
            await redis.delete(monitor_key)
            
            logger.info(f"주문 {order_id}를 모니터링에서 제거하고 완료 저장소로 이동 (TTL: 14일)")
        else:
            # 진행 중인 주문은 모니터링 키 업데이트
            await redis.hset(monitor_key, mapping=update_data)
            
        logger.info(f"주문 상태 업데이트 완료: {order_id}, 상태: {status}")
        
        # 완전 체결 또는 취소된 경우 알림 발송
        if status in ["filled"]:
            order_type = get_actual_order_type(order_data)
            
            price = float(order_data.get("price", "0"))
            position_side = order_data.get("position_side", "unknown")
            
            # PnL 계산을 위한 추가 정보 가져오기
            position_key = f"user:{okx_uid}:position:{symbol}:{position_side}"
            position_data = await redis.hgetall(position_key)
            position_qty = f"{float(position_data.get('position_qty', '0')):.4f}"
            is_hedge = is_true_value(position_data.get("is_hedge", "false"))

            filled_qty = await contracts_to_qty(symbol=symbol, contracts=int(filled_contracts))
            
            # 메시지 구성 (주문 유형별 맞춤형 메시지)
            status_emoji = "✅" if status == "filled" else "❌"
            status_text = "체결 완료"
            
            # 주문 유형에 따른 메시지 제목 설정
            if status == "filled":
                if order_type == "break_even":
                    title = f"🟡 브레이크이븐 {status_text}"
                elif order_type == "sl":
                    if is_hedge == True:
                        title = f"🔴 반대포지션 손절 {status_text}"
                        position_exists, _ = await check_position_exists(okx_uid, symbol, position_side)

                        # 포지션이 존재한다면 직접 종료
                        
                        await send_telegram_message(f"[{okx_uid}] 반대 포지션 손절 후에 포지션 존재 여부: {position_exists}", okx_uid, debug = True)
                        if position_exists:
                            logger.error(f"반대포지션 손절 트리거 체결 이후에도 {symbol} {position_side} 포지션이 여전히 존재함. 직접 종료합니다.")

                            # Lazy import to avoid circular dependency
                            from HYPERRSI.src.api.routes.order.models import ClosePositionRequest
                            from HYPERRSI.src.api.routes.order.order import close_position

                            close_request = ClosePositionRequest(
                                close_type="market",
                                price=price,
                                close_percent=100
                            )
                            try:
                                close_result = await close_position(
                                    symbol=symbol,
                                    close_request=close_request,
                                    user_id=okx_uid,
                                    side=position_side
                                )
                                await send_telegram_message(
                                    f"🔒 Trigger 설정 후 {symbol} {position_side} 포지션을 직접 종료했습니다.(Trigger 발동 안함.)",
                                    okx_uid, debug = True
                                )

                                # 포지션 종료 후 관련 데이터 정리
                                await check_and_cleanup_orders(okx_uid, symbol, position_side)

                            except Exception as e:
                                await send_telegram_message(f"브레이크이븐 종료 오류!!!: {str(e)}", okx_uid, debug = True)
 
                    else:
                        title = f"🔴 손절(SL) {status_text}"
                elif order_type and isinstance(order_type, str) and order_type.startswith("tp"):
                    tp_level_str = order_type[2:] if len(order_type) > 2 else "1"
                    title = f"🟢 익절(TP{tp_level_str}) {status_text}"
                else:
                    title = f"{status_emoji} 주문 {status_text}"
            else:
                if order_type == "sl":
                    title = f"⚠️ 손절(SL) 주문 {status_text}"
                elif order_type and isinstance(order_type, str) and order_type.startswith("tp"):
                    tp_level_str = order_type[2:] if len(order_type) > 2 else "1"
                    title = f"⚠️ 익절(TP{tp_level_str}) 주문 {status_text}"
                else:
                    title = f"{status_emoji} 주문 {status_text}"
            
            # PnL 계산 (체결된 경우만)
            pnl_text = ""
            pnl_percent = 0
            leveraged_pnl = 0
            entry_price = 0
            leverage = 1
            
            if status == "filled" and position_data:
                try:
                    # 진입 가격 (평균 진입가)
                    entry_price = float(position_data.get("entry_price", 0))
                    
                    # PnL 계산
                    if entry_price > 0:
                        if position_side == "long":
                            pnl_percent = ((price / entry_price) - 1) * 100
                        else:  # short
                            pnl_percent = ((entry_price / price) - 1) * 100
                        
                        # PnL 아이콘 설정
                        pnl_icon = "📈" if pnl_percent > 0 else "📉"
                        
                        # PnL 텍스트 구성
                        pnl_text = f"\n{pnl_icon} 수익률: {pnl_percent:.2f}%"
                        
                        # 레버리지가 있는 경우 레버리지 적용 수익률도 표시
                        leverage = float(position_data.get("leverage", 1))
                        if leverage > 1:
                            leveraged_pnl = pnl_percent * leverage
                            pnl_text += f" (레버리지 x{leverage} 적용: {leveraged_pnl:.2f}%)"
                except Exception as pnl_error:
                    logger.error(f"PnL 계산 중 오류: {str(pnl_error)}")
                    pnl_text = "\n💡 PnL 계산 불가"
                
            message = (
                f"{title}\n"
                f"━━━━━━━━━━━━━━━\n"
                f"심볼: {symbol}\n"
                f"방향: {position_side.upper()}\n"
                f"체결가격: {round(float(price), 3)}\n"
            )

            # 체결수량이 0보다 클 때만 메시지에 추가
            if filled_qty is not None and float(filled_qty) > 0:
                message += f"체결수량: {round(float(filled_qty), 4)}{pnl_text}"


            should_send_message = True
            if order_type == "break_even":
                # 브레이크이븐 체결 시 포지션 종료 확인 후 알림 전송
                if status == "filled":
                    asyncio.create_task(verify_and_handle_position_closure(okx_uid, symbol, position_side, "breakeven"))
                
                break_even_key = f"break_even:notification:user:{okx_uid}:{symbol}:{position_side}"
                last_notification_time = await redis.get(break_even_key)
                
                if last_notification_time:
                    # 마지막 알림 시간과 현재 시간의 차이 계산 (초 단위)
                    time_diff = int(now.timestamp()) - int(last_notification_time)
                    if time_diff < 60:  # 1분(60초) 이내의 알림은 스킵
                        logger.info(f"브레이크이븐 알림 중복 방지: {okx_uid}, {symbol}, {position_side}, 마지막 알림으로부터 {time_diff}초 경과")
                        should_send_message = False
                
                # 현재 시간 저장 (중복 알림 방지용)
                await redis.set(break_even_key, str(int(now.timestamp())))
                await redis.expire(break_even_key, 300)  # 5분 TTL 설정
            
            # TP 체결 알림 순서 관리 로직 (개선된 버전)
            logger.debug(f"TP 큐 처리 확인 - order_type: '{order_type}', startswith_tp: {order_type.startswith('tp') if order_type else False}")
            
            if order_type and isinstance(order_type, str) and order_type.startswith("tp") and status == "filled":
                # 체결 시간 체크 (15분 이상 지난 주문은 알림 안 함)
                try:
                    # 주문 상태를 다시 조회하여 체결 시간 확인
                    order_detail = await check_order_status(user_id, symbol, order_id, order_type)
                    
                    if isinstance(order_detail, dict):
                        current_time_ms = int(time.time() * 1000)
                        
                        # 다양한 체결 시간 필드 확인
                        order_fill_time = None
                        for time_field in ['updated_at', 'lastUpdateTimestamp', 'lastTradeTimestamp', 'fillTime']:
                            if time_field in order_detail:
                                order_fill_time = order_detail[time_field]
                                break
                        
                        if order_fill_time:
                            # 타임스탬프가 초 단위인 경우 밀리초로 변환
                            if order_fill_time < 1000000000000:  # 2001년 이전이면 초 단위로 간주
                                order_fill_time *= 1000
                            
                            time_diff_minutes = (current_time_ms - order_fill_time) / 1000 / 60  # 분 단위
                            
                            if time_diff_minutes > 15:
                                logger.warning(f"TP{order_type[2:]} 체결이 {time_diff_minutes:.1f}분 전이므로 알림 스킵")
                                return  # 알림 보내지 않고 함수 종료
                            
                            logger.info(f"TP{order_type[2:]} 체결 시간 확인: {time_diff_minutes:.1f}분 전 (15분 이내 OK)")
                        else:
                            logger.debug(f"TP{order_type[2:]} 체결 시간 정보 없음, 알림 계속 진행")
                            
                except Exception as time_check_error:
                    logger.error(f"TP 체결 시간 확인 중 오류: {str(time_check_error)}, 알림 계속 진행")

                tp_level: int = int(order_type[2:]) if len(order_type) > 2 and order_type[2:].isdigit() else 1
                tp_queue_key = f"tp_queue:user:{okx_uid}:{symbol}:{position_side}"
                
                logger.info(f"TP{tp_level} 큐 처리 시작 - 큐 키: {tp_queue_key}")
                
                # TP 큐에 현재 TP 레벨과 메시지 저장
                tp_queue_data = {
                    "level": tp_level,
                    "message": message,
                    "timestamp": str(int(now.timestamp())),
                    "order_id": order_id,
                    "processed": False
                }
                
                # 대기열 추가
                await redis.hset(tp_queue_key, str(tp_level), json.dumps(tp_queue_data))
                await redis.expire(tp_queue_key, 300)  # 5분 TTL
                
                # TP1의 경우 즉시 알림 전송 (순서 관계없이)
                if tp_level == 1 and status == "filled":
                    logger.info(f"TP1 체결 감지 - 즉시 알림 전송")
                    await send_telegram_message(message, okx_uid=okx_uid)
                    tp_queue_data["processed"] = True
                    await redis.hset(tp_queue_key, str(tp_level), json.dumps(tp_queue_data))
                    should_send_message = False
                    
                    # TP1 체결 후 브레이크이븐 로직 처리
                    try:
                        position_key = f"user:{okx_uid}:position:{symbol}:{position_side}"
                        position_data = await redis.hgetall(position_key)
                        
                        if position_data:
                            use_break_even_tp1 = is_true_value(position_data.get("use_break_even_tp1", "false"))
                            entry_price = float(position_data.get("entry_price", "0"))
                            contracts_amount = float(position_data.get("contracts_amount", "0"))
                            
                            if use_break_even_tp1 and entry_price > 0 and contracts_amount > 0:
                                logger.info(f"TP1 체결: SL을 브레이크이븐({entry_price})으로 이동합니다.")
                                # Lazy import to avoid circular dependency
                                from .break_even_handler import move_sl_to_break_even
                                asyncio.create_task(move_sl_to_break_even(
                                    user_id=user_id,
                                    symbol=symbol,
                                    side=position_side,
                                    break_even_price=entry_price,
                                    contracts_amount=contracts_amount,
                                    tp_index=1,
                                ))
                    except Exception as e:
                        logger.error(f"TP1 브레이크이븐 처리 중 오류: {str(e)}")
                    
                    return  # TP1은 여기서 처리 완료
                
                # Redis에서 현재 완료된 모든 TP 확인
                completed_tps = []
                all_tp_data = await redis.hgetall(tp_queue_key)
                for tp_str, data_str in all_tp_data.items():
                    if tp_str.isdigit():
                        completed_tps.append(int(tp_str))
                
                completed_tps.sort()  # 오름차순 정렬
                logger.info(f"완료된 TP 레벨들: {completed_tps}")
                logger.info(f"현재 체결된 TP: TP{tp_level}")
                
                # 순서대로 처리 가능한 TP들 찾기
                expected_next = 1
                processable_tps: List[int] = []

                for tp_num in completed_tps:
                    if tp_num == expected_next:
                        processable_tps.append(tp_num)
                        expected_next += 1
                    else:
                        break  # 연속되지 않으면 중단
                
                logger.info(f"순서대로 처리 가능한 TP들: {processable_tps}")
                
                # TP 순서 문제로 알림이 막히는 경우 감지 및 해결
                if tp_level not in processable_tps:
                    logger.warning(f"TP{tp_level} 순서 문제 감지. 직접 알림 전송")
                    logger.warning(f"완료된 TP들: {completed_tps}, 처리 가능한 TP들: {processable_tps}")
                    
                    # 순서에 관계없이 현재 TP 직접 알림 전송
                    await send_telegram_message(message, okx_uid=okx_uid)
                    logger.info(f"TP{tp_level} 직접 알림 전송 완료 (순서 무시)")
                    should_send_message = False
                    
                    # 처리 완료 표시
                    tp_queue_data["processed"] = True
                    await redis.hset(tp_queue_key, str(tp_level), json.dumps(tp_queue_data))
                    
                    # 누락된 이전 TP들도 확인하고 알림 전송
                    for i in range(1, tp_level):
                        if i not in processable_tps and i in completed_tps:
                            tp_data_str = await redis.hget(tp_queue_key, str(i))
                            if tp_data_str:
                                tp_data = json.loads(tp_data_str)
                                if not tp_data.get("processed", False):
                                    logger.warning(f"누락된 TP{i} 발견, 알림 전송")
                                    await send_telegram_message(tp_data["message"], okx_uid=okx_uid)
                                    tp_data["processed"] = True
                                    await redis.hset(tp_queue_key, str(i), json.dumps(tp_data))
                
                # 처리 가능한 TP들을 순서대로 알림 전송
                should_send_message = False
                logger.info(f"처리 가능한 TP 개수: {len(processable_tps)}, 현재 TP: {tp_level}")
                for tp_num in processable_tps:
                    tp_data_str = await redis.hget(tp_queue_key, str(tp_num))
                    if tp_data_str:
                        tp_data = json.loads(tp_data_str)
                        if not tp_data.get("processed", False):
                            # 알림 전송
                            await send_telegram_message(tp_data["message"], okx_uid=okx_uid)
                            logger.info(f"TP{tp_num} 알림 전송 완료")
                            
                            # TP3 체결 시 포지션 종료 확인 후 알림 전송
                            if tp_num == 3 and status == "filled":
                                # TP3 체결 후 포지션이 실제로 종료되었는지 확인
                                asyncio.create_task(verify_and_handle_position_closure(okx_uid, symbol, position_side, "tp_complete"))
                            
                            # 처리 완료 표시
                            tp_data["processed"] = True
                            await redis.hset(tp_queue_key, str(tp_num), json.dumps(tp_data))
                            
                            # 현재 처리 중인 TP면 should_send_message를 False로 설정
                            if tp_num == tp_level:
                                should_send_message = False
            
            # 메시지 전송 (중복 방지나 순서 관리 조건을 통과한 경우에만)
            if should_send_message:
                await send_telegram_message(message, okx_uid=okx_uid)
            # 체결된 주문 로깅 (수익률 정보 포함)
            if status == "filled" and order_type:
                try:
                    tp_index = 0
                    if order_type.startswith("tp"):
                        tp_index = int(order_type[2:]) if len(order_type) > 2 and order_type[2:].isdigit() else 1
                    
                    action_type = f"{order_type}_execution"
                    if order_type == "break_even":
                        action_type = "break_even_execution"
                    elif order_type.startswith("tp"):
                        action_type = "tp_execution"
                    elif order_type == "sl":
                        action_type = "sl_execution"
                    
                    # 수익률 정보 포함해서 로깅
                    log_order(
                        user_id=okx_uid,
                        symbol=symbol,
                        action_type=action_type,
                        position_side=position_side,
                        price=price,
                        quantity=float(filled_qty) if filled_qty is not None else 0.0,
                        tp_index= 1 if tp_index == 1 else (int(tp_index)-1) if order_type.startswith("tp") else None,
                        is_hedge=is_true_value(is_hedge),
                        pnl_percent=pnl_percent,
                        leveraged_pnl=leveraged_pnl,
                        leverage=leverage,
                        entry_price=entry_price,
                        order_id=order_id
                    )
                except Exception as log_error:
                    logger.error(f"주문 로깅 중 오류: {str(log_error)}")
            
            if order_type == "break_even":
                # 브레이크이븐 설정 후 포지션이 아직 존재하는지 확인
                position_exists, _ = await check_position_exists(okx_uid, symbol, position_side)

                # 포지션이 존재한다면 직접 종료
                if position_exists:
                    logger.info(f"브레이크이븐 설정 후 {symbol} {position_side} 포지션이 여전히 존재함. 직접 종료합니다.")

                    # Lazy import to avoid circular dependency
                    from HYPERRSI.src.api.routes.order.models import ClosePositionRequest
                    from HYPERRSI.src.api.routes.order.order import close_position

                    close_request = ClosePositionRequest(
                        close_type="market",
                        price=price,
                        close_percent=100
                    )
                    try:
                        close_result = await close_position(
                            symbol=symbol,
                            close_request=close_request,
                            user_id=okx_uid,
                            side=position_side
                        )


                        #await send_telegram_message(
                        #    f"🔒 [{user_id}] 브레이크이븐 설정 후 {symbol} {position_side} 포지션을 직접 종료했습니다.(브레이크이븐이 발동 안함.)",
                        #    okx_uid, debug = True
                        #)

                        # 포지션 종료 후 관련 데이터 정리
                        asyncio.create_task(check_and_cleanup_orders(okx_uid, symbol, position_side))

                    except Exception as e:
                        await send_telegram_message(f"브레이크이븐 종료 오류!!!: {str(e)}", okx_uid, debug = True)
            # TP 주문이 체결된 경우 tp_state 업데이트
            if order_type and order_type.startswith("tp") and status == "filled":
                tp_level_str_update = order_type[2:] if len(order_type) > 2 else "1"
                if tp_level_str_update.isdigit() and int(tp_level_str_update) > 0:
                    await redis.hset(position_key, "tp_state", tp_level_str_update)
                    logger.info(f"tp_state 업데이트: {user_id} {symbol} TP{tp_level_str_update} 체결됨")
            
    
    except Exception as e:
        logger.error(f"주문 상태 업데이트 실패: {str(e)}")
        traceback.print_exc()


async def should_check_tp_order(order_data: Dict, current_price: float) -> bool:
    """
    TP 주문을 확인해야 하는지 결정합니다.
    Redis에 저장된 가격과 실제 주문 가격이 다를 수 있으므로,
    현재가가 TP 가격 근처(1% 이내)에 있으면 체크합니다.
    
    Args:
        order_data: 주문 데이터
        current_price: 현재 가격
        
    Returns:
        bool: 주문을 확인해야 하는 경우 True
    """
    order_type = order_data.get("order_type", "")
    position_side = order_data.get("position_side", "")
    tp_price = float(order_data.get("price", "0"))
    
    # 초기 값들 로깅
    logger.debug(f"TP 주문 체크 시작 - order_type: {order_type}, position_side: {position_side}, tp_price: {tp_price}, current_price: {current_price}")
    
    # 첫 번째 조건 체크: order_type이 tp로 시작하는지
    is_tp_order = order_type.startswith("tp")
    #logger.debug(f"order_type.startswith('tp') 체크: {is_tp_order} (order_type: {order_type})")
    
    # 두 번째 조건 체크: tp_price가 0보다 큰지
    is_valid_price = tp_price > 0
    #ogger.debug(f"tp_price > 0 체크: {is_valid_price} (tp_price: {tp_price})")
    
    if not is_tp_order or not is_valid_price:
        logger.debug(f"TP 주문 체크 종료 - 기본 조건 미충족 (is_tp_order: {is_tp_order}, is_valid_price: {is_valid_price})")
        return False
    
    # 가격 차이 허용 범위 (1%)
    price_tolerance = 0.01
    price_diff_ratio = abs(current_price - tp_price) / tp_price
    
    # Long 포지션: 현재가가 TP 근처(1% 이내)에 있거나 TP보다 높으면 확인
    if position_side == "long":
        # 기존 조건: 현재가가 TP 이상
        exact_condition = current_price >= tp_price
        # 관대한 조건: 현재가가 TP의 1% 이내
        near_condition = price_diff_ratio <= price_tolerance and current_price >= tp_price * (1 - price_tolerance)
        
        should_check = exact_condition or near_condition
        logger.debug(f"Long 포지션 TP 체크 - exact: {exact_condition}, near(1% 이내): {near_condition}, price_diff_ratio: {price_diff_ratio:.4f}")
        if should_check:
            logger.info(f"Long 포지션 TP 도달 또는 근처 - current_price: {current_price}, tp_price: {tp_price}, diff_ratio: {price_diff_ratio:.4f}")
        return should_check
    # Short 포지션: 현재가가 TP 근처(1% 이내)에 있거나 TP보다 낮으면 확인
    elif position_side == "short":
        # 기존 조건: 현재가가 TP 이하
        exact_condition = current_price <= tp_price
        # 관대한 조건: 현재가가 TP의 1% 이내
        near_condition = price_diff_ratio <= price_tolerance and current_price <= tp_price * (1 + price_tolerance)
        
        should_check = exact_condition or near_condition
        #logger.debug(f"Short 포지션 TP 체크 - exact: {exact_condition}, near(1% 이내): {near_condition}, price_diff_ratio: {price_diff_ratio:.4f}")
        #if should_check:
        #    logger.info(f"Short 포지션 TP 도달 또는 근처 - current_price: {current_price}, tp_price: {tp_price}, diff_ratio: {price_diff_ratio:.4f}")
        return should_check
        
    logger.debug(f"TP 주문 체크 종료 - 알 수 없는 position_side: {position_side}")
    return False


async def should_check_sl_order(order_data: Dict, current_price: float) -> bool:
    """
    SL 주문을 확인해야 하는지 결정합니다.
    
    Args:
        order_data: 주문 데이터
        current_price: 현재 가격
        
    Returns:
        bool: 주문을 확인해야 하는 경우 True
    """
    order_type = order_data.get("order_type", "")
    position_side = order_data.get("position_side", "")
    sl_price = float(order_data.get("price", "0"))
    
    if order_type != "sl" or sl_price <= 0:
        return False
        
    # Long 포지션: 현재가가 SL보다 낮으면 확인
    if position_side == "long" and current_price <= sl_price:
        return True
    # Short 포지션: 현재가가 SL보다 높으면 확인
    elif position_side == "short" and current_price >= sl_price:
        return True
        
    return False

