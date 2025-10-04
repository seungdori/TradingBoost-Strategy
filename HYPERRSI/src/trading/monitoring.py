# src/trading/monitoring.py

import asyncio
import json
from datetime import datetime, timedelta
import traceback
from typing import Dict, List, Optional, Set, Tuple
import time
import gc
import sys
import os
import telegram

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))
from HYPERRSI.src.helpers.order_helper import contracts_to_qty
import signal
import atexit
import psutil
from HYPERRSI.src.core.logger import get_logger, log_order
from HYPERRSI.src.core.database import redis_client, check_redis_connection, reconnect_redis
from HYPERRSI.src.trading.services.get_current_price import get_current_price
from HYPERRSI.src.api.dependencies import  get_exchange_context
# 순환 참조 제거
# from HYPERRSI.src.bot.telegram_message import send_telegram_message
from HYPERRSI.src.core.error_handler import log_error
from HYPERRSI.src.api.routes.order import close_position, get_order_detail, update_stop_loss_order, get_algo_order_info, ClosePositionRequest
from HYPERRSI.src.trading.dual_side_entry import get_user_dual_side_settings

# 지원하는 거래 심볼 목록 (추후 확장 가능)
SUPPORTED_SYMBOLS = ["BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP"]

# 텔레그램 메시지 전송 함수 직접 구현
async def send_telegram_message(message, okx_uid, debug=False):
    """
    텔레그램 메시지를 전송합니다.
    
    Args:
        message: 전송할 메시지
        okx_uid: 사용자 ID
        debug: 디버그 모드 여부
    """
    try:
        # 메시지 큐에 추가
        message_data = {
            "type": "text",
            "message": message,
            "okx_uid": okx_uid,
            "debug": debug
        }
        
        if debug == True:
            okx_uid = str(587662504768345929)
        
        # 메시지 큐에 추가
        queue_key = MESSAGE_QUEUE_KEY.format(okx_uid=okx_uid)
        await redis_client.rpush(queue_key, json.dumps(message_data))
        
        # 메시지 처리 플래그 설정
        processing_flag = MESSAGE_PROCESSING_FLAG.format(okx_uid=okx_uid)
        await redis_client.set(processing_flag, "1", ex=60)  # 60초 후 만료
        if debug:
            okx_uid = str(587662504768345929)
        # 메시지 처리 태스크 시작
        asyncio.create_task(process_telegram_messages(okx_uid))
        
    except Exception as e:
        logger.error(f"텔레그램 메시지 전송 중 오류 발생: {str(e)}")
        traceback.print_exc()

# 메시지 큐 관련 키 형식
MESSAGE_QUEUE_KEY = "telegram:message_queue:{okx_uid}"
MESSAGE_PROCESSING_FLAG = "telegram:processing_flag:{okx_uid}"

# 불리언 값 또는 문자열을 안전하게 처리하는 함수
def is_true_value(value):
    if isinstance(value, bool):
        return value
    elif isinstance(value, str):
        return value.lower() == 'true'
    return False

def get_actual_order_type(order_data: dict) -> str:
    """
    실제 order_type을 결정합니다. order_type이 없거나 불명확한 경우 order_name을 확인합니다.
    
    Args:
        order_data: Redis에서 가져온 주문 데이터
        
    Returns:
        str: 실제 order_type (tp1, tp2, tp3, sl, break_even 등)
    """
    if not isinstance(order_data, dict):
        logger.warning(f"get_actual_order_type: order_data가 dict가 아님: {type(order_data)}")
        return "unknown"
    
    order_type = order_data.get("order_type", "unknown")
    order_name = order_data.get("order_name", "")
    
    # order_type이 제대로 설정되어 있으면 그대로 사용
    # limit, market은 주문 방식이지 주문 목적이 아니므로 order_name 확인 필요
    if order_type not in ["unknown", "limit", "market", "", None]:
        return order_type
    
    # order_name이 있고 유효한 경우 사용
    if order_name and isinstance(order_name, str):
        # tp로 시작하는 경우 (tp1, tp2, tp3)
        if order_name.startswith("tp") and len(order_name) >= 3:
            # tp1, tp2, tp3만 허용
            if order_name in ["tp1", "tp2", "tp3"]:
                return order_name
        # sl인 경우
        elif order_name == "sl":
            return "sl"
        # break_even인 경우
        elif order_name == "break_even":
            return "break_even"
    
    # 둘 다 없으면 unknown 반환
    return "unknown"

# 시스템 특정 모듈 (조건부 임포트)
try:
    import resource  # Unix 전용
except ImportError:
    resource = None




MONITOR_INTERVAL = 2
ORDER_CHECK_INTERVAL = 10  # 주문 상태를 확인하는 간격(초)

# 모니터링 서비스 설정
MAX_RESTART_ATTEMPTS = 5  # 최대 재시작 횟수 
MAX_MEMORY_MB = 2048     # 최대 메모리 사용량 (MB)
MEMORY_CLEANUP_INTERVAL = 600  # 메모리 정리 간격 (10분)
CONNECTION_TIMEOUT = 30  # API 연결 타임아웃 (초)
API_RATE_LIMIT = 5       # 초당 최대 API 호출 수

# 상태 캐시 추가 (최근 체크한 주문 상태를 단시간 캐싱)
order_status_cache = {}
ORDER_STATUS_CACHE_TTL = 5  # 5초 캐시 유지

# 로깅 시간 추적 딕셔너리 (5분마다 로깅 제한)
last_log_times = {}
LOG_INTERVAL_SECONDS = 300  # 5분 = 300초

async def get_user_settings(user_id: str) -> dict:
    """
    사용자의 설정 정보를 가져옵니다.
    
    Args:
        user_id (int): 사용자 ID
        
    Returns:
        dict: 사용자 설정 정보
    """
    try:
        settings_key = f"user:{user_id}:settings"
        settings_data = await redis_client.get(settings_key)
        
        if settings_data:
            return json.loads(settings_data)
        else:
            # 기본 설정값
            return {
                'use_sl': True,
                'use_break_even': False,
                'use_break_even_tp2': False,
                'use_break_even_tp3': False
            }
    except Exception as e:
        logger.error(f"Error getting settings for user {user_id}: {str(e)}")
        return {
            'use_sl': True,
            'use_break_even': False,
            'use_break_even_tp2': False,
            'use_break_even_tp3': False
        }


logger = get_logger(__name__)

def should_log(log_key: str, interval_seconds: int = LOG_INTERVAL_SECONDS) -> bool:
    """
    지정된 키에 대해 로깅을 해야 하는지 확인합니다.
    
    Args:
        log_key: 로그 타입을 구분하는 키
        interval_seconds: 로깅 간격 (기본 5분)
        
    Returns:
        bool: 로깅을 해야 하면 True, 아니면 False
    """
    current_time = time.time()
    last_logged = last_log_times.get(log_key, 0)
    
    if current_time - last_logged >= interval_seconds:
        last_log_times[log_key] = current_time
        return True
    return False

async def get_telegram_id_from_okx_uid(okx_uid: str):
    try:
        # 모든 사용자 키를 검색하기 위한 패턴
        pattern = "user:*:okx_uid"
        keys = await redis_client.keys(pattern)
        
        valid_telegram_ids = []
        
        for key in keys:
            # Redis 키에서 저장된 OKX UID 값 가져오기
            stored_uid = await redis_client.get(key)
            
            # stored_uid 값 처리 (bytes일 수도 있고 str일 수도 있음)
            stored_uid_str = stored_uid.decode() if isinstance(stored_uid, bytes) else stored_uid
            
            # 요청된 OKX UID와 일치하는 경우
            if stored_uid and stored_uid_str == okx_uid:
                # user:123456789:okx_uid 형식에서 user_id(텔레그램 ID) 추출
                user_key = key.decode() if isinstance(key, bytes) else key
                user_id = user_key.split(':')[1]
                
                # 숫자로 시작하는 텔레그램 ID만 추가 (OKX UID는 일반적으로 매우 긴 숫자)
                if user_id.isdigit() and len(user_id) < 15:
                    # 최근 활동 시간 확인 (가능한 경우)
                    last_activity = 0
                    try:
                        stats = await redis_client.hgetall(f"user:{user_id}:stats")
                        if stats and b'last_trade_date' in stats:
                            last_trade_date = stats[b'last_trade_date'] if isinstance(stats[b'last_trade_date'], bytes) else stats[b'last_trade_date'].encode()
                            last_activity = int(last_trade_date.decode() or '0')
                    except Exception as e:
                        print(f"통계 정보 가져오기 오류: {str(e)}")
                        pass
                    
                    valid_telegram_ids.append({
                        "telegram_id": int(user_id),
                        "last_activity": last_activity
                    })
        
        if valid_telegram_ids:
            # 최근 활동순으로 정렬
            valid_telegram_ids.sort(key=lambda x: x["last_activity"], reverse=True)
            
            # 모든 가능한 텔레그램 ID 반환 (최근 활동순)
            return {
                "primary_telegram_id": valid_telegram_ids[0]["telegram_id"],
                "all_telegram_ids": [id_info["telegram_id"] for id_info in valid_telegram_ids],
                "okx_uid": okx_uid
            }
        
        # 일치하는 OKX UID가 없는 경우
    except Exception as e:
        logger.error(f"OKX UID를 텔레그램 ID로 변환 중 오류: {str(e)}")
        return None
        


async def get_okx_uid_from_telegram_id(telegram_id: str) -> str:
    """
    텔레그램 ID를 OKX UID로 변환하는 함수
    
    Args:
        telegram_id: 텔레그램 ID
        
    Returns:
        str: OKX UID
    """
    try:
        # 텔레그램 ID로 OKX UID 조회
        okx_uid = await redis_client.get(f"user:{telegram_id}:okx_uid")
        if okx_uid:
            return okx_uid.decode() if isinstance(okx_uid, bytes) else okx_uid
        return None
    except Exception as e:
        logger.error(f"텔레그램 ID를 OKX UID로 변환 중 오류: {str(e)}")
        return None

async def get_identifier(user_id: str) -> str:
    """
    입력된 식별자가 텔레그램 ID인지 OKX UID인지 확인하고 적절한 OKX UID를 반환
    
    Args:
        user_id: 텔레그램 ID 또는 OKX UID
        
    Returns:
        str: OKX UID
    """
    # 11글자 이하면 텔레그램 ID로 간주하고 변환
    if len(str(user_id)) <= 11:
        okx_uid = await get_okx_uid_from_telegram_id(user_id)
        if not okx_uid:
            logger.error(f"텔레그램 ID {user_id}에 대한 OKX UID를 찾을 수 없습니다")
            return str(user_id)  # 변환 실패 시 원래 ID 반환
        return okx_uid
    # 12글자 이상이면 이미 OKX UID로 간주
    return str(user_id)

async def get_all_running_users() -> List[int]:
    """
    현재 'running' 상태인 모든 user_id를 조회
    """
    # 최대 재시도 횟수
    max_retry = 3
    retry_count = 0
    
    while retry_count < max_retry:
        try:
            # Redis 연결 상태 확인
            if not await check_redis_connection():
                logger.warning(f"Redis 연결 상태 불량, 재연결 시도 ({retry_count+1}/{max_retry})")
                await reconnect_redis()
                
            status_keys = await redis_client.keys("user:*:trading:status")
            running_users = []
            
            for key in status_keys:
                status = await redis_client.get(key)
                if status == "running":
                    # key 구조: user:{user_id}:trading:status
                    parts = key.split(":")
                    user_id = parts[1]
                    # OKX UID로 변환
                    okx_uid = await get_identifier(user_id)
                    running_users.append(int(okx_uid))
            
            return running_users
        except Exception as e:
            retry_count += 1
            logger.error(f"running_users 조회 실패 (시도 {retry_count}/{max_retry}): {str(e)}")
            logger.error(f"Error details: {traceback.format_exc()}")
            
            # 마지막 시도가 아니면 Redis 재연결 후 재시도
            if retry_count < max_retry:
                logger.info(f"Redis 재연결 후 {retry_count+1}번째 재시도 중...")
                try:
                    await reconnect_redis()
                    await asyncio.sleep(1)  # 잠시 대기
                except Exception as reconnect_error:
                    logger.error(f"Redis 재연결 실패: {str(reconnect_error)}")
    
    # 모든 재시도 실패
    logger.error(f"running_users 조회 최대 재시도 횟수({max_retry}) 초과")
    return []

async def perform_memory_cleanup():
    """
    메모리 정리 작업을 별도 태스크로 수행하여 메인 모니터링 루프를 차단하지 않습니다.
    """
    try:
        logger.info(f"메모리 정리 시작 (간격: {MEMORY_CLEANUP_INTERVAL}초)")
        
        # 메모리 사용량 로깅
        process = psutil.Process()
        memory_info = process.memory_info()
        logger.info(f"현재 메모리 사용량: {memory_info.rss / 1024 / 1024:.2f} MB")
        
        # 가비지 컬렉션 강제 실행
        gc.collect()
        
        # Redis 연결 풀 정리
        await reconnect_redis()
        
        # 주문 상태 캐시 정리
        current_time_cleanup = time.time()
        expired_keys = [k for k, (t, _) in order_status_cache.items() if current_time_cleanup - t > ORDER_STATUS_CACHE_TTL]
        for key in expired_keys:
            del order_status_cache[key]
        logger.info(f"주문 상태 캐시 정리 완료: {len(expired_keys)}개 항목 제거, 현재 {len(order_status_cache)}개 항목 유지")
        
        # 추가 메모리 정리: 만료된 거래 데이터 정리
        try:
            # Redis 연결 상태 확인
            if not await check_redis_connection():
                logger.warning("메모리 정리 중 Redis 연결 상태 불량, 재연결 시도")
                await reconnect_redis()
            
            # 2주 이상 지난 완료된 주문 데이터 삭제
            two_weeks_ago = int((datetime.now() - timedelta(days=14)).timestamp())
            pattern = "completed:user:*:order:*"
            old_order_keys = await redis_client.keys(pattern)
            
            for key in old_order_keys:
                try:
                    order_data = await redis_client.hgetall(key)
                    last_updated = int(order_data.get("last_updated_time", "0"))
                    if last_updated < two_weeks_ago:
                        logger.info(f"오래된 완료 주문 데이터 삭제: {key}")
                        await redis_client.delete(key)
                except Exception as e:
                    logger.error(f"완료 주문 데이터 삭제 중 오류: {str(e)}")
                    continue
        except Exception as e:
            logger.error(f"만료된 데이터 정리 중 오류: {str(e)}")
            # Redis 재연결 시도
            await reconnect_redis()
            
        logger.info("메모리 정리 완료")
        
    except Exception as e:
        logger.error(f"메모리 정리 중 오류 발생: {str(e)}")
        traceback.print_exc()

async def check_missing_orders(user_id: str, symbol: str, current_orders: List):
    """
    사라진 주문들이 체결되었는지 확인하여 알림을 보냅니다.
    
    Args:
        user_id: 사용자 ID
        symbol: 거래 심볼
        current_orders: 현재 남아있는 주문 목록
    """
    try:
        logger.info(f"사라진 주문 체크 시작: {user_id} {symbol}")
        
        # 현재 남아있는 주문 ID 목록
        current_order_ids = set(order_data.get("order_id") for order_data in current_orders)
        
        # 이전에 저장된 주문 ID 목록 조회
        prev_orders_key = f"prev_orders:{user_id}:{symbol}"
        prev_order_ids_str = await redis_client.get(prev_orders_key)
        
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
                        completed_data = await redis_client.hgetall(completed_key)
                        
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
            await redis_client.set(prev_orders_key, current_order_ids_str, ex=3600)  # 1시간 TTL
        except Exception as save_error:
            logger.error(f"주문 ID 목록 저장 중 오류: {str(save_error)}")
        
    except Exception as e:
        logger.error(f"사라진 주문 체크 중 오류: {str(e)}")
        traceback.print_exc()

async def check_recent_filled_orders(user_id: str, symbol: str):
    """
    최근 체결된 주문들을 확인하여 놓친 알림이 있는지 체크합니다.
    """
    try:
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
                completed_data = await redis_client.hgetall(completed_key)
                
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

async def check_redis_connection_task():
    """
    Redis 연결 상태를 확인하는 별도 태스크입니다.
    """
    try:
        logger.info("Redis 연결 상태 정기 확인")
        if not await check_redis_connection():
            logger.warning("Redis 연결 상태 불량, 재연결 시도")
            await reconnect_redis()
        else:
            logger.info("Redis 연결 상태 양호")
    except Exception as e:
        logger.error(f"Redis 연결 상태 확인 중 오류: {str(e)}")
        traceback.print_exc()

async def get_user_monitor_orders(user_id: str) -> Dict[str, Dict]:
    """
    사용자의 모든 모니터링 중인 주문을 조회합니다.
    
    Args:
        user_id: 사용자 ID (텔레그램 ID 또는 OKX UID)
        
    Returns:
        Dict: {order_id: order_data, ...}
    """
    try:
        # user_id를 OKX UID로 변환
        okx_uid = await get_identifier(str(user_id))
        
        # 사용자 주문 모니터링 키 패턴
        pattern = f"monitor:user:{okx_uid}:*:order:*"
        order_keys = await redis_client.keys(pattern)
        
        orders = {}
        for key in order_keys:
            try:
                # 키 타입 확인
                key_type = await redis_client.type(key)
                
                # 해시 타입인지 확인 - 문자열로 변환하여 비교
                if str(key_type).lower() == 'hash' or str(key_type).lower() == "b'hash'":
                    # 정상적인 해시 타입인 경우
                    order_data = await redis_client.hgetall(key)
                    if order_data and "status" in order_data:
                        # Redis에는 open으로 저장되어 있지만 실제로는 체결되었을 수 있음
                        if order_data["status"] == "open":
                            # 정상적인 open 주문
                            # key 형식: monitor:user:{user_id}:{symbol}:order:{order_id}
                            parts = key.split(":")
                            symbol = parts[3]
                            order_id = parts[5]
                            
                            # order_data에 symbol과 order_id 추가
                            order_data["symbol"] = symbol
                            order_data["order_id"] = order_id
                            orders[order_id] = order_data
                else:
                    # 다른 타입이면 로그만 남기고 스킵
                    logger.warning(f"주문 데이터가 해시 타입이 아닙니다. (key: {key}, 타입: {key_type})")
            except Exception as redis_error:
                logger.error(f"Redis 주문 데이터 조회 중 오류 (key: {key}): {str(redis_error)}")
                continue
                
        return orders
    except Exception as e:
        logger.error(f"사용자 {user_id}의 모니터링 주문 조회 실패: {str(e)}")
        return {}

async def check_order_status(user_id: str, symbol: str, order_id: str, order_type: str = None) -> Dict:
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
                return cached_result
            
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
                    algo_type= None
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
                return result
                
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
                                return result
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
                                return order_info
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

async def update_order_status(user_id: str, symbol: str, order_id: str, status: str, filled_amount: str = "0", order_type: str = None) -> None:
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
        # user_id를 OKX UID로 변환
        okx_uid = await get_identifier(str(user_id))
        
        monitor_key = f"monitor:user:{okx_uid}:{symbol}:order:{order_id}"
        order_data = await redis_client.hgetall(monitor_key)
        
        if not order_data:
            logger.warning(f"주문 데이터를 찾을 수 없음: {monitor_key}")
            await redis_client.delete(monitor_key)
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
                    position_data = await redis_client.hgetall(position_key)
                    
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
            await redis_client.hset(completed_key, mapping=updated_order_data)
            
            # 2주일(14일) TTL 설정
            await redis_client.expire(completed_key, 60 * 60 * 24 * 14)  # 14일 = 1,209,600초
            
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
                                position_data = await redis_client.hgetall(position_key)
                                
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
                            tp_level = order_type[2:] if len(order_type) > 2 else "1"
                            title = f"🟢 익절(TP{tp_level}) 체결 완료"
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
            await redis_client.delete(monitor_key)
            
            logger.info(f"주문 {order_id}를 모니터링에서 제거하고 완료 저장소로 이동 (TTL: 14일)")
        else:
            # 진행 중인 주문은 모니터링 키 업데이트
            await redis_client.hset(monitor_key, mapping=update_data)
            
        logger.info(f"주문 상태 업데이트 완료: {order_id}, 상태: {status}")
        
        # 완전 체결 또는 취소된 경우 알림 발송
        if status in ["filled"]:
            order_type = get_actual_order_type(order_data)
            
            price = float(order_data.get("price", "0"))
            position_side = order_data.get("position_side", "unknown")
            
            # PnL 계산을 위한 추가 정보 가져오기
            position_key = f"user:{okx_uid}:position:{symbol}:{position_side}"
            position_data = await redis_client.hgetall(position_key)
            position_qty = f"{float(position_data.get('position_qty', '0')):.4f}"
            is_hedge = is_true_value(position_data.get("is_hedge", "false"))
            
            filled_qty = await contracts_to_qty(symbol = symbol, contracts = filled_contracts)
            
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
                    tp_level = order_type[2:] if len(order_type) > 2 else "1"
                    title = f"🟢 익절(TP{tp_level}) {status_text}"
                else:
                    title = f"{status_emoji} 주문 {status_text}"
            else:
                if order_type == "sl":
                    title = f"⚠️ 손절(SL) 주문 {status_text}"
                elif order_type and isinstance(order_type, str) and order_type.startswith("tp"):
                    tp_level = order_type[2:] if len(order_type) > 2 else "1"
                    title = f"⚠️ 익절(TP{tp_level}) 주문 {status_text}"
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
            if float(filled_qty) > 0:
                message += f"체결수량: {round(float(filled_qty), 4)}{pnl_text}"


            should_send_message = True
            if order_type == "break_even":
                # 브레이크이븐 체결 시 포지션 종료 확인 후 알림 전송
                if status == "filled":
                    asyncio.create_task(verify_and_handle_position_closure(okx_uid, symbol, position_side, "breakeven"))
                
                break_even_key = f"break_even:notification:user:{okx_uid}:{symbol}:{position_side}"
                last_notification_time = await redis_client.get(break_even_key)
                
                if last_notification_time:
                    # 마지막 알림 시간과 현재 시간의 차이 계산 (초 단위)
                    time_diff = int(now.timestamp()) - int(last_notification_time)
                    if time_diff < 60:  # 1분(60초) 이내의 알림은 스킵
                        logger.info(f"브레이크이븐 알림 중복 방지: {okx_uid}, {symbol}, {position_side}, 마지막 알림으로부터 {time_diff}초 경과")
                        should_send_message = False
                
                # 현재 시간 저장 (중복 알림 방지용)
                await redis_client.set(break_even_key, str(int(now.timestamp())))
                await redis_client.expire(break_even_key, 300)  # 5분 TTL 설정
            
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
                
                tp_level = int(order_type[2:]) if len(order_type) > 2 and order_type[2:].isdigit() else 1
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
                await redis_client.hset(tp_queue_key, str(tp_level), json.dumps(tp_queue_data))
                await redis_client.expire(tp_queue_key, 300)  # 5분 TTL
                
                # TP1의 경우 즉시 알림 전송 (순서 관계없이)
                if tp_level == 1 and status == "filled":
                    logger.info(f"TP1 체결 감지 - 즉시 알림 전송")
                    await send_telegram_message(message, okx_uid=okx_uid)
                    tp_queue_data["processed"] = True
                    await redis_client.hset(tp_queue_key, str(tp_level), json.dumps(tp_queue_data))
                    should_send_message = False
                    
                    # TP1 체결 후 브레이크이븐 로직 처리
                    try:
                        position_key = f"user:{okx_uid}:position:{symbol}:{position_side}"
                        position_data = await redis_client.hgetall(position_key)
                        
                        if position_data:
                            use_break_even_tp1 = is_true_value(position_data.get("use_break_even_tp1", "false"))
                            entry_price = float(position_data.get("entry_price", "0"))
                            contracts_amount = float(position_data.get("contracts_amount", "0"))
                            
                            if use_break_even_tp1 and entry_price > 0 and contracts_amount > 0:
                                logger.info(f"TP1 체결: SL을 브레이크이븐({entry_price})으로 이동합니다.")
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
                all_tp_data = await redis_client.hgetall(tp_queue_key)
                for tp_str, data_str in all_tp_data.items():
                    if tp_str.isdigit():
                        completed_tps.append(int(tp_str))
                
                completed_tps.sort()  # 오름차순 정렬
                logger.info(f"완료된 TP 레벨들: {completed_tps}")
                logger.info(f"현재 체결된 TP: TP{tp_level}")
                
                # 순서대로 처리 가능한 TP들 찾기
                expected_next = 1
                processable_tps = []
                
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
                    await redis_client.hset(tp_queue_key, str(tp_level), json.dumps(tp_queue_data))
                    
                    # 누락된 이전 TP들도 확인하고 알림 전송
                    for i in range(1, tp_level):
                        if i not in processable_tps and i in completed_tps:
                            tp_data_str = await redis_client.hget(tp_queue_key, str(i))
                            if tp_data_str:
                                tp_data = json.loads(tp_data_str)
                                if not tp_data.get("processed", False):
                                    logger.warning(f"누락된 TP{i} 발견, 알림 전송")
                                    await send_telegram_message(tp_data["message"], okx_uid=okx_uid)
                                    tp_data["processed"] = True
                                    await redis_client.hset(tp_queue_key, str(i), json.dumps(tp_data))
                
                # 처리 가능한 TP들을 순서대로 알림 전송
                should_send_message = False
                logger.info(f"처리 가능한 TP 개수: {len(processable_tps)}, 현재 TP: {tp_level}")
                for tp_num in processable_tps:
                    tp_data_str = await redis_client.hget(tp_queue_key, str(tp_num))
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
                            await redis_client.hset(tp_queue_key, str(tp_num), json.dumps(tp_data))
                            
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
                        quantity=float(filled_qty),
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
                tp_level = order_type[2:] if len(order_type) > 2 else "1"
                if tp_level.isdigit() and int(tp_level) > 0:
                    await redis_client.hset(position_key, "tp_state", tp_level)
                    logger.info(f"tp_state 업데이트: {user_id} {symbol} TP{tp_level} 체결됨")
            
    
    except Exception as e:
        logger.error(f"주문 상태 업데이트 실패: {str(e)}")
        traceback.print_exc()

async def move_sl_to_break_even(user_id: str, symbol: str, side: str, break_even_price: float, contracts_amount: float, tp_index: int = 0, is_hedge: bool = False):
    """
    거래소 API를 사용해 SL(Stop Loss) 가격을 break_even_price로 업데이트.
    
    Args:
        user_id: 사용자 ID (텔레그램 ID 또는 OKX UID)
    """
    try:
        # user_id를 OKX UID로 변환
        okx_uid = await get_identifier(str(user_id))
        
        # side가 long 또는 buy이면 order_side는 sell, side가 short 또는 sell이면 order_side는 buy
        order_side = "sell"
        if side == "long" or side == "buy":
            order_side = "sell"
        elif side == "short" or side == "sell":
            order_side = "buy"
            
        result = await update_stop_loss_order(
                        new_sl_price=break_even_price,
                        symbol=symbol,
                        side=side,
                        order_side=order_side,
                        contracts_amount=contracts_amount,
                        user_id=okx_uid,
                        is_hedge=is_hedge,
                        order_type="break_even"
                    ),
                
        if isinstance(result, dict) and not result.get('success', True):
            logger.info(f"SL 업데이트 건너뜀: {result.get('message')}")
            return None
        await asyncio.sleep(2)

        telegram_message = ""

        if tp_index > 0:
            # 브레이크이븐 이동 알림 중복 방지 체크
            from datetime import datetime
            now = datetime.now()
            breakeven_move_key = f"breakeven_move:notification:user:{okx_uid}:{symbol}:{side}:tp{tp_index}"
            last_notification_time = await redis_client.get(breakeven_move_key)
            
            should_send_message = True
            if last_notification_time:
                # 마지막 알림 시간과 현재 시간의 차이 계산 (초 단위)
                time_diff = int(now.timestamp()) - int(last_notification_time)
                if time_diff < 300:  # 5분(300초) 이내의 알림은 스킵
                    logger.info(f"브레이크이븐 이동 알림 중복 방지: {okx_uid}, {symbol}, {side}, TP{tp_index}, 마지막 알림으로부터 {time_diff}초 경과")
                    should_send_message = False
            
            if should_send_message:
                telegram_message += f"🔒 TP{tp_index} 체결 후 SL을 브레이크이븐({break_even_price:.2f})으로 이동\n"
                
                try:
                    dual_side_settings = await get_user_dual_side_settings(okx_uid)
                    dual_side_sl_type = dual_side_settings.get('dual_side_entry_sl_trigger_type', 'percent')
                    dual_side_sl_value = dual_side_settings.get('dual_side_entry_sl_value', 10)
                    if dual_side_settings.get('use_dual_side', False):
                        if dual_side_sl_type == 'existing_position':

                            if int(dual_side_sl_value) > tp_index:
                                dual_side_key = f"user:{okx_uid}:{symbol}:dual_side_position"
                                await redis_client.hset(dual_side_key, "stop_loss", break_even_price)
                                telegram_message += f"🔒 양방향 포지션 SL 업데이트: {break_even_price:.2f}$\n"
                                
                except Exception as e:
                    await send_telegram_message(f"[{okx_uid}]양방향 포지션 SL 업데이트 오류: {str(e)}", okx_uid, debug=True)
                    
                # 현재 시간 저장 (중복 알림 방지용)
                await redis_client.set(breakeven_move_key, str(int(now.timestamp())))
                await redis_client.expire(breakeven_move_key, 600)  # 10분 TTL 설정
                
                asyncio.create_task(send_telegram_message(
                    telegram_message,
                    okx_uid
                ))
        position_key = f"user:{okx_uid}:position:{symbol}:{side}"
        await redis_client.hset(position_key, "sl_price", break_even_price)
        
        # 브레이크이븐 이동 로깅
        try:
            log_order(
                user_id=okx_uid,
                symbol=symbol,
                action_type='break_even_move',
                position_side=side,
                price=break_even_price,
                quantity=contracts_amount,
                tp_index=tp_index,
                is_hedge=is_hedge
            )
        except Exception as e:
            logger.error(f"브레이크이븐 이동 로깅 실패: {str(e)}")
            
        # dual_side_position이 있는지 확인
        dual_side_key = f"user:{okx_uid}:{symbol}:dual_side_position"
        dual_side_position_exists = await redis_client.exists(dual_side_key)
        
        if dual_side_position_exists:
            # dual_side_entry_tp_trigger_type 설정 확인
            dual_settings = await get_user_dual_side_settings(okx_uid)
            dual_side_entry_tp_trigger_type = dual_settings.get('dual_side_entry_tp_trigger_type', 'percent')
            dual_side_tp_value = dual_settings.get('dual_side_entry_tp_value', 10)
            dual_side_sl_value = dual_settings.get('dual_side_entry_sl_value', 10)
            
            dual_side_sl_type = dual_settings.get('dual_side_entry_sl_trigger_type', 'percent')
            dual_sl_on_tp = dual_side_sl_type == 'existing_position'
            use_dual_side = is_true_value(dual_settings.get('use_dual_side', False))
            
            if dual_side_entry_tp_trigger_type == "existing_position":
                # 반대 방향 포지션 찾기
                opposite_side = "short" if side == "long" else "long"
                
                # 반대 방향 포지션 종료
                if int(dual_side_sl_value) == tp_index:
                    
                    close_request = ClosePositionRequest(
                        close_type="market",
                        close_percent=100
                    )
                    
                    try:
                        logger.info(f"dual_side_position 종료 시도: {symbol}, {opposite_side}")
                        response = await close_position(
                            symbol=symbol, 
                            close_request=close_request, 
                            user_id=okx_uid, 
                            side=opposite_side
                        )
                        
                        # 양방향 포지션 익절 시 메인 포지션도 종료 설정이 있는지 확인
                        close_main_on_hedge_tp = dual_settings.get('close_main_on_hedge_tp', False)
                        if close_main_on_hedge_tp:
                            # 메인 포지션 종료
                            try:
                                main_close_request = ClosePositionRequest(
                                    close_type="market",
                                    close_percent=100
                                )
                                await close_position(
                                    symbol=symbol,
                                    close_request=main_close_request,
                                    user_id=okx_uid,
                                    side=side  # 메인 포지션 방향
                                )
                                await send_telegram_message(f"✅양방향 포지션 익절로 메인 포지션도 종료\n" +f"━━━━━━━━━━━━━━━━\n" +f"메인 포지션의 TP{tp_index} 체결로 모든 포지션 종료\n" +f"• 메인 방향: {side}\n" +f"• 양방향 방향: {opposite_side}\n" +f"━━━━━━━━━━━━━━━━\n",okx_uid)
                            except Exception as e:
                                logger.error(f"메인 포지션 종료 실패: {str(e)}")
                                await send_telegram_message(f"메인 포지션 종료 실패: {str(e)}", okx_uid, debug=True)
                        else:
                            # 양방향 종료 로깅
                            await send_telegram_message(f"✅양방향 포지션 종료\n" +f"━━━━━━━━━━━━━━━━\n" +f"메인 포지션의 TP{tp_index} 체결로 양방향 포지션 종료\n" +f"• 방향: {opposite_side}\n" +f"━━━━━━━━━━━━━━━━\n",okx_uid)
                        
                        # dual_side_position 키 삭제
                        await redis_client.delete(dual_side_key)
                        
                    except Exception as e:
                        logger.error(f"dual_side_position 종료 실패: {str(e)}")
                        await send_telegram_message(f"양방향 포지션 종료 실패: {str(e)}", okx_uid, debug=True)

        return result
    except Exception as e:
        error_msg = f"move_sl_to_break_even 오류: {str(e)}"
        await send_telegram_message(error_msg, okx_uid, debug=True)
        log_error(
            error=e,
            user_id=okx_uid,
            additional_info={
                "function": "move_sl_to_break_even",
                "timestamp": datetime.now().isoformat()
            }
        )
        return None

async def process_break_even_settings(user_id: str, symbol: str, order_type: str, position_data: dict):
    """
    TP 주문 체결 시 사용자 설정에 따라 브레이크이븐 처리를 수행합니다.
    
    Args:
        user_id: 사용자 ID (텔레그램 ID 또는 OKX UID)
    """
    try:
        # user_id를 OKX UID로 변환
        okx_uid = await get_identifier(str(user_id))
        
        if not (order_type.startswith('tp') or order_type.startswith('take_profit')):
            return False
            
        # TP 레벨 확인 (tp1, tp2, tp3)
        tp_level = int(order_type[2]) if len(order_type) > 2 and order_type[2].isdigit() else 1
        
        # 사용자 설정 가져오기
        settings = await get_user_settings(okx_uid) 
        dual_side_settings = await get_user_dual_side_settings(okx_uid)

        
        # 안전하게 값 처리
        use_break_even_tp1 = is_true_value(settings.get('use_break_even', False))
        use_break_even_tp2 = is_true_value(settings.get('use_break_even_tp2', False))
        use_break_even_tp3 = is_true_value(settings.get('use_break_even_tp3', False))
        
        dual_side_tp_type = dual_side_settings.get('dual_side_entry_tp_trigger_type', 'percent')
        dual_side_sl_type = dual_side_settings.get('dual_side_entry_sl_trigger_type', 'percent')
        dual_side_tp_value = dual_side_settings.get('dual_side_entry_tp_value', 10)
        dual_side_sl_value = dual_side_settings.get('dual_side_entry_sl_value', 10)
        tp1_close_percent = float(settings.get('tp1_ratio', 30))
        tp2_close_percent = float(settings.get('tp2_ratio', 30))
        tp3_close_percent = float(settings.get('tp3_ratio', 40))
        
        total_tp_close_ratio = tp1_close_percent + tp2_close_percent + tp3_close_percent
        dual_sl_on_tp = dual_side_sl_type == 'existing_position'
        use_dual_side = is_true_value(dual_side_settings.get('use_dual_side', False))
        
        
        # 포지션 정보 가져오기
        position_side = position_data.get('position_side', '')
        contracts_amount = float(position_data.get('contracts_amount', '0'))
        # position_data에서 진입가 확인 (avgPrice 키를 먼저 확인)
        entry_price_from_data = float(position_data.get('avgPrice', position_data.get('entry_price', '0')))
        
        dual_side_position_side = None
        if use_dual_side:
            if position_side == 'long' or position_side == 'buy':
                dual_side_position_side = 'short'
            else:
                dual_side_position_side = 'long'
                
        position_key = f"user:{okx_uid}:position:{symbol}:{position_side}"
        full_position_data = await redis_client.hgetall(position_key)
        
        # 주문 가격 정보
        # Redis에서 진입가를 가져오되, 이미 position_data에서 진입가를 가져왔다면 그 값을 우선 사용
        entry_price = entry_price_from_data if entry_price_from_data > 0 else float(full_position_data.get("entry_price", 0))
        
        # contracts_amount를 이미 위에서 설정했으므로 중복 재설정하지 않음 (값이 유효하지 않은 경우에만 재설정)
        if contracts_amount <= 0:
            contracts_amount = float(full_position_data.get("contracts_amount", 0))
        
        # TP 데이터 가져오기
        tp_data_str = full_position_data.get("tp_data", "{}")
        try:
            tp_data = json.loads(tp_data_str)
        except json.JSONDecodeError:
            tp_data = []
        # TP 레벨에 따른 브레이크이븐 적용
        
        try:
            
            try:
                dual_side_key = f"user:{okx_uid}:{symbol}:dual_side_position"
                
                dual_side_key = f"user:{user_id}:{symbol}:dual_side_position"
            except Exception as e:
                logger.error(f"양방향 포지션 키 오류: {str(e)}")
                dual_side_key =f"user:{user_id}:{symbol}:dual_side_position"
            
            dual_side_position_exists = await redis_client.exists(dual_side_key)

            if dual_side_position_exists:
                if dual_side_tp_type == 'existing_position':
                    if int(dual_side_tp_value) == tp_level:
                        close_request = ClosePositionRequest(
                            close_type="market",
                            close_percent=100
                        )
                        await close_position(
                            symbol=symbol,
                            close_request=close_request,
                            user_id=user_id,
                            side=dual_side_position_side
                        )
                        
                        # 양방향 포지션 익절 시 메인 포지션도 종료 설정이 있는지 확인
                        close_main_on_hedge_tp = dual_side_settings.get('close_main_on_hedge_tp', False)
                        if close_main_on_hedge_tp:
                            # 메인 포지션 종료
                            try:
                                main_close_request = ClosePositionRequest(
                                    close_type="market",
                                    close_percent=100
                                )
                                await close_position(
                                    symbol=symbol,
                                    close_request=main_close_request,
                                    user_id=user_id,
                                    side=position_side  # 메인 포지션 방향
                                )
                                await send_telegram_message(f"✅양방향 포지션 익절로 메인 포지션도 종료\n" +f"━━━━━━━━━━━━━━━━\n" +f"메인 포지션의 TP{tp_level} 체결로 모든 포지션 종료\n" +f"• 메인 방향: {position_side}\n" +f"• 양방향 방향: {dual_side_position_side}\n" +f"━━━━━━━━━━━━━━━━\n",user_id)
                            except Exception as e:
                                logger.error(f"메인 포지션 종료 실패: {str(e)}")
                                await send_telegram_message(f"메인 포지션 종료 실패: {str(e)}", user_id, debug=True)
                        else:
                            await send_telegram_message(f"✅양방향 포지션 종료\n" +f"━━━━━━━━━━━━━━━━\n" +f"메인 포지션의 TP{tp_level} 체결로 양방향 포지션 종료\n" +f"• 방향: {dual_side_position_side}\n" +f"━━━━━━━━━━━━━━━━\n",user_id)
                        
                if dual_side_sl_type == 'existing_position':
                    if int(dual_side_sl_value) == tp_level:
                        close_request = ClosePositionRequest(
                            close_type="market",
                            close_percent=100
                        )
                        await close_position(
                            symbol=symbol,
                            close_request=close_request,
                            user_id=user_id,
                            side=dual_side_position_side
                        )
                        await send_telegram_message(f"✅양방향 포지션 종료\n" +f"━━━━━━━━━━━━━━━━\n" +f"메인 포지션의 TP{tp_level} 체결로 양방향 포지션 종료\n" +f"• 방향: {dual_side_position_side}\n" +f"━━━━━━━━━━━━━━━━\n",user_id)
                        
        except Exception as e:
            logger.error(f"양방향 포지션 종료 실패!: {str(e)}")
            await send_telegram_message(f"양방향 포지션 종료 실패! {str(e)}", user_id, debug=True)
        
        try:
            if tp_level == 1 and use_break_even_tp1:
                #await send_telegram_message(f"TP1 브레이크이븐 확인. [DEBUG] TP1 체결: SL을 브레이크이븐({entry_price})으로 이동합니다.", user_id, debug = True)
                # TP1 체결 시 진입가(브레이크이븐)으로 SL 이동
                print(f"entry_price: {entry_price}, contracts_amount: {contracts_amount}")
                if entry_price > 0 and contracts_amount > 0:
                    logger.info(f"TP1 체결: SL을 브레이크이븐({entry_price})으로 이동합니다.")
                    asyncio.create_task(move_sl_to_break_even(
                        user_id=user_id,
                        symbol=symbol,
                        side=position_side,
                        break_even_price=entry_price,
                        contracts_amount=contracts_amount,
                        tp_index=tp_level,
                    ))
                #else:
                #    await send_telegram_message(f"오류. {entry_price}, {contracts_amount}\n아마 포지션이 이미 없는 경우.", user_id, debug = True)
                    
            elif tp_level == 2 and use_break_even_tp2:
                # TP2 체결 시 TP1 가격으로 SL 이동
                if isinstance(tp_data, list):
                    tp1_price = next((float(tp.get('price', 0)) for tp in tp_data 
                                if tp.get('level') == 1), None)
                    if tp1_price and tp1_price > 0 and contracts_amount > 0:
                        logger.info(f"TP2 체결: SL을 TP1 가격({tp1_price})으로 이동합니다.")
                        asyncio.create_task(move_sl_to_break_even(
                            user_id=user_id,
                            symbol=symbol,
                            side=position_side,
                            break_even_price=tp1_price,
                            contracts_amount=contracts_amount,
                            tp_index=tp_level
                        ))
                
            elif tp_level == 3 and use_break_even_tp3:
                # TP3 체결 시 TP2 가격으로 SL 이동
                if isinstance(tp_data, list):
                    # TP1, TP2, TP3의 비율 합이 100%인지 확인
                    #total_tp_ratio = sum(float(tp.get('ratio', 0)) for tp in tp_data if tp.get('level') in [1, 2, 3])
                    if total_tp_close_ratio >= 99:
                        logger.info(f"TP1, TP2, TP3의 비율 합이 100% 이상이므로 브레이크이븐 로직을 실행하지 않습니다.")
                        return False
                        
                    tp2_price = next((float(tp.get('price', 0)) for tp in tp_data 
                                if tp.get('level') == 2), None)
                    if tp2_price and tp2_price > 0 and contracts_amount > 0:
                        logger.info(f"TP3 체결: SL을 TP2 가격({tp2_price})으로 이동합니다.")
                        asyncio.create_task(move_sl_to_break_even(
                            user_id=user_id,
                            symbol=symbol,
                            side=position_side,
                            break_even_price=tp2_price,
                            contracts_amount=contracts_amount,
                            tp_index=tp_level
                        ))
        except Exception as e:
            logger.error(f"브레이크이븐 처리 중 오류: {str(e)}")
            traceback.print_exc()
            
        
        # TP 체결 시 트레일링 스탑 활성화 여부 확인 (사용자 설정에 따라)
        # 문자열과 불리언 모두 처리
        trailing_stop_active = is_true_value(settings.get('trailing_stop_active', False))
        
        # 문자열 값 처리
        trailing_start_point = str(settings.get('trailing_start_point', 'tp3')).lower()
        current_tp = f"tp{tp_level}"
        print(f"TRAILING START POIN : {trailing_start_point}, CURRENT TP: {current_tp}")
        
        # 사용자 설정의 시작점에 도달했는지 확인
        if trailing_stop_active and current_tp.lower() == trailing_start_point:
            logger.info(f"{current_tp.upper()} 체결: 트레일링 스탑 활성화 조건 충족")
            asyncio.create_task(activate_trailing_stop(user_id, symbol, position_side, full_position_data, tp_data))
        
        return False
    except Exception as e:
        logger.error(f"브레이크이븐 처리 중 오류: {str(e)}")
        traceback.print_exc()
        return False

async def activate_trailing_stop(user_id: str, symbol: str, direction: str, position_data: dict, tp_data: list = None):
    """
    TP3 도달 시 트레일링 스탑 활성화
    
    Args:
        user_id: 사용자 ID (텔레그램 ID 또는 OKX UID)
    """
    try:
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
                await redis_client.hset(trailing_key, mapping=ts_data)
                
                # 트레일링 키 만료 시간 설정 (7일 - 안전장치)
                await redis_client.expire(trailing_key, 60 * 60 * 24 * 7)
                
                # 기존 포지션 키에도 트레일링 활성화 정보 저장 (포지션이 남아있는 경우만)
                position_key = f"user:{user_id}:position:{symbol}:{direction}"
                position_exists = await redis_client.exists(position_key)
                
                if position_exists:
                    # SL 가격 업데이트
                    await redis_client.hset(position_key, "sl_price", trailing_stop_price)
                    await redis_client.hset(position_key, "trailing_stop_active", "true")
                    await redis_client.hset(position_key, "trailing_stop_key", trailing_key)
                
                # SL 주문 업데이트 시도
                try:
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
    try:
        # user_id를 OKX UID로 변환
        okx_uid = await get_identifier(str(user_id))
        
        # 트레일링 스탑 전용 키 확인
        trailing_key = f"trailing:user:{okx_uid}:{symbol}:{direction}"
        
        # 트레일링 스탑 키가 존재하는지 확인
        if not await redis_client.exists(trailing_key):
            # 포지션 키에서 트레일링 스탑 활성화 정보 확인 (레거시 지원)
            position_key = f"user:{okx_uid}:position:{symbol}:{direction}"
            
            try:
                # 키 타입 확인
                key_type = await redis_client.type(position_key)
                
                # 해시 타입인지 확인 - 문자열로 변환하여 비교
                if str(key_type).lower() == 'hash' or str(key_type).lower() == "b'hash'":
                    # 정상적인 해시 타입인 경우
                    position_data = await redis_client.hgetall(position_key)
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
            key_type = await redis_client.type(trailing_key)
            
            # 해시 타입인지 확인 - 문자열로 변환하여 비교
            if str(key_type).lower() == 'hash' or str(key_type).lower() == "b'hash'":
                # 정상적인 해시 타입인 경우
                ts_data = await redis_client.hgetall(trailing_key)
            else:
                # 다른 타입이거나 키가 없는 경우
                logger.warning(f"트레일링 스탑 데이터가 해시 타입이 아닙니다. (key: {trailing_key}, 타입: {key_type})")
                return False
        except Exception as redis_error:
            logger.error(f"Redis 트레일링 스탑 데이터 조회 중 오류: {str(redis_error)}")
            return False
        
        if not ts_data or not ts_data.get("active", False):
            # 비활성화된 트레일링 스탑은 삭제
            await redis_client.delete(trailing_key)
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
                await redis_client.hset(trailing_key, "highest_price", str(highest_price))
                await redis_client.hset(trailing_key, "trailing_stop_price", str(trailing_stop_price))
                await redis_client.hset(trailing_key, "last_updated", str(int(datetime.now().timestamp())))
                
                # 포지션 키가 존재하면 함께 업데이트
                position_key = f"user:{okx_uid}:position:{symbol}:{direction}"
                if await redis_client.exists(position_key):
                    try:
                        # 키 타입 확인
                        key_type = await redis_client.type(position_key)
                        # 해시 타입인지 확인 - 문자열로 변환하여 비교
                        if str(key_type).lower() == 'hash' or str(key_type).lower() == "b'hash'":
                            await redis_client.hset(position_key, "sl_price", str(trailing_stop_price))
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
                    asyncio.create_task(move_sl_to_break_even(
                        user_id=okx_uid,
                        symbol=symbol,
                        side=direction,
                        break_even_price=trailing_stop_price,
                        contracts_amount=contracts_amount,
                        tp_index=0
                    ))  
                    
                    # 마지막 SL 업데이트 시간 기록
                    await redis_client.hset(trailing_key, "last_sl_update", str(current_time))
                
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
                await redis_client.hset(trailing_key, "status", "triggered")
                await redis_client.hset(trailing_key, "trigger_price", str(current_price))
                await redis_client.hset(trailing_key, "trigger_time", str(int(datetime.now().timestamp())))
                
                # 트레일링 스탑 실행 로깅
                try:
                    position_key = f"user:{okx_uid}:position:{symbol}:{direction}"
                    position_data = await redis_client.hgetall(position_key)
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
                await redis_client.hset(trailing_key, "lowest_price", str(lowest_price))
                await redis_client.hset(trailing_key, "trailing_stop_price", str(trailing_stop_price))
                await redis_client.hset(trailing_key, "last_updated", str(int(datetime.now().timestamp())))
                
                # 포지션 키가 존재하면 함께 업데이트
                position_key = f"user:{okx_uid}:position:{symbol}:{direction}"
                if await redis_client.exists(position_key):
                    try:
                        # 키 타입 확인
                        key_type = await redis_client.type(position_key)
                        # 해시 타입인지 확인 - 문자열로 변환하여 비교
                        if str(key_type).lower() == 'hash' or str(key_type).lower() == "b'hash'":
                            await redis_client.hset(position_key, "sl_price", str(trailing_stop_price))
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
                    asyncio.create_task(move_sl_to_break_even(
                        user_id=okx_uid,
                        symbol=symbol,
                        side=direction,
                        break_even_price=trailing_stop_price,
                        contracts_amount=contracts_amount,
                        tp_index=0
                    ))
                    
                    # 마지막 SL 업데이트 시간 기록
                    await redis_client.hset(trailing_key, "last_sl_update", str(current_time))
                
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
                await redis_client.hset(trailing_key, "status", "triggered")
                await redis_client.hset(trailing_key, "trigger_price", str(current_price))
                await redis_client.hset(trailing_key, "trigger_time", str(int(datetime.now().timestamp())))
                
                # 트레일링 스탑 실행 로깅
                try:
                    position_key = f"user:{user_id}:position:{symbol}:{direction}"
                    position_data = await redis_client.hgetall(position_key)
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
        # 트레일링 스탑 키 삭제
        trailing_key = f"trailing:user:{user_id}:{symbol}:{direction}"
        await redis_client.delete(trailing_key)
        
        # 포지션 키가 있으면 트레일링 스탑 관련 필드도 리셋
        position_key = f"user:{user_id}:position:{symbol}:{direction}"
        if await redis_client.exists(position_key):
            await redis_client.hset(position_key, "trailing_stop_active", "false")
            await redis_client.hdel(position_key, "trailing_stop_key")
            
        logger.info(f"트레일링 스탑 데이터 삭제 완료: {trailing_key}")
        return True
    except Exception as e:
        logger.error(f"트레일링 스탑 데이터 삭제 오류: {str(e)}")
        return False

async def get_active_trailing_stops() -> List[Dict]:

    try:
        trailing_keys = await redis_client.keys("trailing:user:*")
        trailing_stops = []
        for key in trailing_keys:
            data = await redis_client.hgetall(key)
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

async def monitor_orders_loop():
    """
    주문을 지속적으로 모니터링하는 무한 루프 함수
    """
    logger.info("주문 모니터링 서비스 시작")
    last_order_check_time = 0  # 마지막 주문 상태 전체 확인 시간
    last_position_check_time = 0  # 마지막 포지션 확인 시간
    last_memory_cleanup_time = 0  # 마지막 메모리 정리 시간
    last_memory_check_time = 0    # 마지막 메모리 체크 시간
    last_algo_cancel_time = 0     # 마지막 알고리즘 주문 취소 시간
    last_redis_check_time = 0     # 마지막 Redis 연결 확인 시간
    POSITION_CHECK_INTERVAL = 60  # 포지션 확인 간격(초)
    MEMORY_CHECK_INTERVAL = 60    # 메모리 체크 간격(초)
    REDIS_CHECK_INTERVAL = 30     # Redis 연결 확인 간격(초)
    ALGO_ORDER_CANCEL_INTERVAL = 300  # 알고리즘 주문 취소 간격(초, 5분)
    consecutive_errors = 0  # 연속 오류 카운터
    
    # API 속도 제한 관리
    api_call_timestamps = []
    
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
                last_active_users_num_logging = await redis_client.get(f"last_active_users_num_logging")
                if len(running_users) > 0 and last_active_users_num_logging is None:
                    logger.info(f"[활성 사용자 수: {len(running_users)}]")
                    await redis_client.set(f"last_active_users_num_logging", current_time)
                elif len(running_users) > 0 and last_active_users_num_logging is not None and abs(current_time - float(last_active_users_num_logging)) >= 60:
                    logger.info(f"[활성 사용자 수: {len(running_users)}]")
                    await redis_client.set(f"last_active_users_num_logging", current_time)
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
                    asyncio.create_task(cancel_algo_orders_for_no_position_sides(user_id))
            
            # 먼저 모든 활성 트레일링 스탑 체크 (독립적인 트레일링 스탑)
            active_trailings = await get_active_trailing_stops()
            if len(active_trailings) > 0:
                logger.info(f"활성 트레일링 스탑 수: {len(active_trailings)}")
                for ts_data in active_trailings:
                    try:
                        user_id = int(ts_data.get("user_id", "0"))
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
                                ts_hit = await check_trailing_stop(user_id, symbol, direction, current_price)
                                
                                # 트레일링 스탑 조건 충족 시
                                if ts_hit:
                                    # SL 주문 ID 확인
                                    
                                    
                                    close_request = ClosePositionRequest(
                                        close_type="market",
                                        price=current_price,
                                        close_percent=100
                                    )
                                    
                                    await close_position(
                                        symbol=symbol,
                                        close_request=close_request,
                                        user_id=user_id,
                                        side=direction
                                    )
                                    
                                    sl_order_id = ts_data.get("sl_order_id", "")
                                    
                                    
                                    
                                    if sl_order_id:
                                        # SL 주문 상태 확인
                                        logger.info(f"[트레일링] SL 주문 상태 확인: {sl_order_id}")
                                        sl_status = await check_order_status(
                                            user_id=user_id,
                                            symbol=symbol,
                                            order_id=sl_order_id,
                                            order_type="sl"
                                        )
                                        
                                        # SL 주문이 체결되었는지 확인
                                        if isinstance(sl_status, dict) and sl_status.get('status') in ['FILLED', 'CLOSED', 'filled', 'closed']:
                                            logger.info(f"[트레일링] SL 주문 체결됨: {sl_order_id}")
                                            # 트레일링 스탑 데이터 삭제
                                            await clear_trailing_stop(user_id, symbol, direction)
                                        elif isinstance(sl_status, dict) and sl_status.get('status') in ['CANCELED', 'canceled']:
                                            # SL 주문이 취소된 경우 트레일링 스탑 데이터 삭제
                                            logger.info(f"[트레일링] SL 주문 취소됨: {sl_order_id}")
                                            await clear_trailing_stop(user_id, symbol, direction)
                                    else:
                                        # SL 주문 ID가 없는 경우 (포지션 자체 확인)
                                        position_exists, _ = await check_position_exists(user_id, symbol, direction)
                                        
                                        if not position_exists:
                                            # 포지션이 없으면 트레일링 스탑 데이터 삭제
                                            logger.info(f"[트레일링] 포지션 없음, 트레일링 스탑 삭제: {user_id}:{symbol}:{direction}")
                                            asyncio.create_task(clear_trailing_stop(user_id, symbol, direction))
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
                    user_orders = await get_user_monitor_orders(user_id)
                    if not user_orders:
                        continue
                        
                    # 사용자별 모니터링 주문 수 로깅 (5분마다)
                    user_monitor_log_key = f"user_monitor_{user_id}"
                    if should_log(user_monitor_log_key):
                        logger.info(f"사용자 {user_id}의 모니터링 주문 수: {len(user_orders)}")
                    
                    # 심볼별 주문 그룹화 (한 번만 현재가를 가져오기 위함)
                    symbol_orders = {}
                    
                    for order_id, order_data in user_orders.items():
                        symbol = order_data.get("symbol")
                        if symbol not in symbol_orders:
                            symbol_orders[symbol] = []
                        symbol_orders[symbol].append(order_data)
                    
                    # 각 심볼에 대해 현재가 조회 및 주문 상태 확인

                    for symbol, orders in symbol_orders.items():
                        # 심볼별 주문 수 변화 감지
                        current_order_count = len(orders)
                        order_count_key = f"order_count:{user_id}:{symbol}"
                        previous_count = await redis_client.get(order_count_key)
                        
                        force_check_all_orders = False
                        if previous_count:
                            previous_count = int(previous_count)
                            if previous_count > current_order_count:
                                logger.warning(f"주문 수 감소 감지: {user_id} {symbol} {previous_count} -> {current_order_count}, 체결된 주문 있을 수 있음")
                                force_check_all_orders = True
                                
                                # 사라진 주문이 체결되었는지 확인하기 위해 별도 태스크 실행
                                asyncio.create_task(check_missing_orders(user_id, symbol, orders))
                                
                                # 추가로 최근 체결된 주문도 확인
                                asyncio.create_task(check_recent_filled_orders(user_id, symbol))
                        
                        # 현재 주문 수 저장
                        await redis_client.set(order_count_key, current_order_count, ex=600)  # 10분 TTL
                        
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
                                        position_exists, _ = await check_position_exists(user_id, symbol, direction)
                                        if not position_exists:
                                            await check_and_cleanup_orders(user_id, symbol, direction)
                                
                                # 심볼별로 트레일링 스탑 활성화된 방향 확인
                                trailing_sides = set()
                                for direction in ["long", "short"]:
                                    ts_key = f"trailing:user:{user_id}:{symbol}:{direction}"
                                    if await redis_client.exists(ts_key):
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
                                    order_id = order_data.get("order_id")
                                    order_type = order_data.get("order_type", "")
                                    position_side = order_data.get("position_side", "")
                                    current_status = order_data.get("status", "")
                                    
                                    # 모니터링되는 주문 로깅
                                    logger.debug(f"모니터링 주문: {order_id}, 타입: {order_type}, 포지션: {position_side}, 상태: {current_status}")
                                    
                                    # 이미 완료 처리된 주문은 스킵 (filled, canceled, failed)
                                    if current_status in ["filled", "canceled", "failed"]:
                                        continue
                                    
                                    # 주문 상태 변화 감지를 위한 이전 상태 확인
                                    status_key = f"order_status:{order_id}"
                                    previous_status = await redis_client.get(status_key)
                                    
                                    # 상태가 변경된 경우 강제 체크
                                    status_changed = previous_status and previous_status != current_status
                                    if status_changed:
                                        logger.info(f"주문 상태 변화 감지: {order_id}, {previous_status} -> {current_status}, 강제 체크")
                                    
                                    # 현재 상태를 Redis에 저장 (다음 비교용)
                                    await redis_client.set(status_key, current_status, ex=3600)  # 1시간 TTL
                                    
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
                                        order_id = order_data.get("order_id")
                                        order_type = order_data.get("order_type", "")
                                        # 주문 상태 확인 로깅도 5분마다 한번만
                                        order_log_key = f"order_status_{order_id}"
                                        if should_log(order_log_key):
                                            logger.info(f"주문 상태 확인: {order_id}, 타입: {order_type}")
                                        
                                        # 주문 상태 확인 전 포지션 정보 로깅 (5분마다 한번만)
                                        log_key = f"order_check_{user_id}_{symbol}_{position_side}"
                                        if should_log(log_key):
                                            logger.info(f"주문 확인 전 포지션 정보 - user_id: {user_id}, symbol: {symbol}, position_side: {position_side}")
                                            logger.info(f"주문 데이터: {order_data}")
                                        tp_index = 0
                                        if order_type.startswith("tp"):
                                            tp_index = int(order_type[2:])
                                        # 주문 확인 간 짧은 딜레이 추가 (서버 부하 방지)
                                        await asyncio.sleep(0.1)
                                        
                                        # order_type 매개변수를 추가하여 호출
                                        try:
                                            order_status = await check_order_status(
                                                user_id=user_id, 
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
                                                        tp_already_processed = await redis_client.hget(position_key, f"get_tp{tp_index}")
                                                        
                                                        if tp_already_processed == "true":
                                                            logger.info(f"TP{tp_index} 이미 처리됨, 중복 처리 방지: {user_id} {symbol} {position_side}")
                                                            continue
                                                        
                                                        #get TP 업데이트
                                                        await redis_client.hset(position_key, f"get_tp{tp_index}", "true")
                                                        
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
                                                        
                                                        # 사용자 설정에 따른 브레이크이븐/트레일링스탑 처리
                                                        asyncio.create_task(process_break_even_settings(
                                                            user_id=user_id,
                                                            symbol=symbol,
                                                            order_type=order_type,
                                                            position_data=order_data
                                                        ))
                                                        
                                                    except Exception as be_error:
                                                        logger.error(f"브레이크이븐/트레일링스탑 처리 실패: {str(be_error)}")
                                                
                                                # 주문 상태 업데이트 (order_type 매개변수 추가)
                                                await update_order_status(
                                                    user_id=user_id,
                                                    symbol=symbol,
                                                    order_id=order_id,
                                                    status=status,
                                                    filled_amount=str(filled_sz),
                                                    order_type=order_type
                                                )
                                                
                                                # SL 주문이 체결된 경우, 관련 트레일링 스탑 데이터 정리
                                                if status == 'filled' and order_type == 'sl':
                                                    # SL 체결 후 포지션이 실제로 종료되었는지 확인
                                                    asyncio.create_task(verify_and_handle_position_closure(user_id, symbol, position_side, "stop_loss"))
                                                    asyncio.create_task(clear_trailing_stop(user_id, symbol, position_side))
                                                    
                                                    
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
                                                state = order_status.get('state')
                                                filled_sz = order_status.get('filled_amount', '0')
                                                if filled_sz == '0':
                                                    filled_sz = order_status.get('amount', '0')
                                                    if filled_sz == '0':
                                                        filled_sz = order_status.get('sz', '0')
                                                
                                                # 상태 매핑
                                                status_mapping = {
                                                    'filled': 'filled',
                                                    'effective': 'open',
                                                    'canceled': 'canceled',
                                                    'order_failed': 'failed'
                                                }
                                                status = status_mapping.get(state, 'unknown')
                                                
                                                # 주문 상태 업데이트 (order_type 매개변수 추가)
                                                await update_order_status(
                                                    user_id=user_id,
                                                    symbol=symbol,
                                                    order_id=order_id,
                                                    status=status,
                                                    filled_amount=filled_sz,
                                                    order_type=order_type
                                                )
                                                
                                                # SL 주문이 체결된 경우, 관련 트레일링 스탑 데이터 정리
                                                if status == 'filled' and order_type == 'sl':
                                                    await clear_trailing_stop(user_id, symbol, position_side)
                                            else:
                                                # dict이지만 'status'나 'state' 키가 없는 경우
                                                logger.warning(f"주문 상태 응답에 'status' 또는 'state' 키가 없음: {order_id} -> {order_status}")
                                                # 기본적으로 canceled로 처리
                                                await update_order_status(
                                                    user_id=user_id,
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
                                                user_id=user_id,
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
                        f"⚠️ 모니터링 서비스 오류 발생\n재시작 시도: {restart_attempts}/{MAX_RESTART_ATTEMPTS}\n오류: {str(e)}\n타입: {error_type}\n서버 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                        user_id=1709556958,
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
                f"🚨 모니터링 서비스 강제 종료\n최대 재시작 시도 횟수({MAX_RESTART_ATTEMPTS})를 초과했습니다.\n수동 개입이 필요합니다.\n서버 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                user_id=1709556958,
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

def convert_to_trading_symbol(symbol: str) -> str:
    """
    다양한 형식의 심볼을 OKX API 호환 형식(BTC-USDT-SWAP)으로 변환합니다.
    지원하는 심볼만 반환하며, 지원하지 않는 심볼은 기본값인 BTC-USDT-SWAP을 반환합니다.
    
    Args:
        symbol (str): 변환할 심볼 (예: "BTCUSDT", "BTC/USDT" 등)
        
    Returns:
        str: OKX API 호환 형식의 심볼 (예: "BTC-USDT-SWAP")
    """
    # 원본 심볼 기록
    original_symbol = symbol
    
    # CCXT 형식(:USDT 등) 제거
    if ":" in symbol:
        symbol = symbol.split(":")[0]
    
    # 슬래시(/) 제거
    symbol = symbol.replace("/", "")
    # 하이픈(-) 제거 
    symbol = symbol.replace("-", "")
    
    logger.debug(f"심볼 변환: {original_symbol} -> {symbol}")
    
    # 일반적인 심볼 형식 변환 (BTCUSDT, ETHUSDT 등)
    converted_symbol = ""
    
    if "USDT" in symbol:
        # USDT를 포함하는 경우 (대부분의 코인)
        base = symbol.replace("USDT", "")
        converted_symbol = f"{base}-USDT-SWAP"
    elif len(symbol) >= 7:
        # 대부분의 코인은 3글자 + 4글자(USDT) 형식
        base = symbol[0:3]
        quote = symbol[3:7]
        converted_symbol = f"{base}-{quote}-SWAP"
    elif len(symbol) >= 6 and symbol.endswith("USDT"):
        # 2글자 코인 (XRPUSDT 같은 경우)
        base_len = len(symbol) - 4
        base = symbol[0:base_len]
        quote = symbol[base_len:]
        converted_symbol = f"{base}-{quote}-SWAP"
    else:
        # 기타 형식은 기본값으로 처리
        logger.warning(f"알 수 없는 심볼 형식: {original_symbol} -> {symbol}, 기본값 사용")
        converted_symbol = "BTC-USDT-SWAP"
    
    logger.debug(f"심볼 변환 완료: {original_symbol} -> {converted_symbol}")
    return converted_symbol

# 심볼 관리 함수 추가
async def add_recent_symbol(user_id: str, symbol: str):
    """
    사용자가 거래한 심볼을 Redis에 저장하고 1시간의 만료 시간을 설정합니다.
    
    Args:
        user_id: 사용자 ID (텔레그램 ID 또는 OKX UID)
        symbol: 거래 심볼
    """
    try:
        # user_id를 OKX UID로 변환
        okx_uid = await get_identifier(str(user_id))
        
        # 각 심볼을 별도의 키로 저장 (개별 만료 시간 설정을 위해)
        symbol_key = f"user:{okx_uid}:recent_symbol:{symbol}"
        
        # 심볼 정보 저장 (값은 중요하지 않음, 키의 존재 여부만 확인)
        await redis_client.set(symbol_key, "1")
        
        # 1시간(3600초) 만료 시간 설정
        await redis_client.expire(symbol_key, 3600)
        
        logger.info(f"최근 거래 심볼 추가: {okx_uid}:{symbol}, 만료: 1시간")
    except Exception as e:
        logger.error(f"최근 거래 심볼 추가 실패: {str(e)}")

async def get_recent_symbols(user_id: str) -> List[str]:
    """
    사용자가 최근 거래한 심볼 목록을 가져옵니다.
    
    Args:
        user_id: 사용자 ID (텔레그램 ID 또는 OKX UID)
        
    Returns:
        List[str]: 최근 거래 심볼 목록
    """
    try:
        # user_id를 OKX UID로 변환
        okx_uid = await get_identifier(str(user_id))
        
        # 패턴 매칭으로 모든 활성 심볼 키 가져오기
        pattern = f"user:{okx_uid}:recent_symbol:*"
        symbol_keys = await redis_client.keys(pattern)
        
        # 키에서 심볼 부분만 추출
        symbols = []
        for key in symbol_keys:
            # 키 형식: user:{user_id}:recent_symbol:{symbol}
            parts = key.split(":")
            if len(parts) >= 4:
                symbol = parts[3]
                symbols.append(symbol)
        
        return symbols
    except Exception as e:
        logger.error(f"최근 거래 심볼 조회 실패: {str(e)}")
        return []

# 텔레그램 메시지 처리 함수
async def process_telegram_messages(user_id):
    """
    텔레그램 메시지 큐에서 메시지를 가져와 처리합니다.
    
    Args:
        user_id: 사용자 ID
    """
    try:
        # 처리 중 플래그 확인
        processing_flag = MESSAGE_PROCESSING_FLAG.format(okx_uid=user_id)
        flag_exists = await redis_client.exists(processing_flag)
        
        if not flag_exists:
            return
        
        # 메시지 큐에서 메시지 가져오기
        queue_key = MESSAGE_QUEUE_KEY.format(okx_uid=user_id)
        message_data = await redis_client.lpop(queue_key)
        
        if not message_data:
            # 큐가 비어있으면 처리 중 플래그 제거
            await redis_client.delete(processing_flag)
            return
        
        # 메시지 데이터 파싱
        message_data = json.loads(message_data)
        message_type = message_data.get("type")
        message = message_data.get("message")
        debug = message_data.get("debug", False)
                    # 메시지 전송
        try:
            telegram_data = await get_telegram_id_from_okx_uid(user_id)
            if telegram_data and "primary_telegram_id" in telegram_data:
                user_telegram_id = telegram_data["primary_telegram_id"]
            else:
                logger.error(f"텔레그램 ID 조회 결과가 없습니다: {telegram_data}")
                user_telegram_id = user_id
        except Exception as e:
            logger.error(f"텔레그램 ID 조회 오류: {str(e)}")
            user_telegram_id = user_id
        # 메시지 타입에 따라 처리
        if message_type == "text":
            # 텔레그램 봇 토큰 가져오기
            bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
            if not bot_token:
                logger.error("텔레그램 봇 토큰이 설정되지 않았습니다.")
                return
            
            # 텔레그램 봇 생성
            bot = telegram.Bot(token=bot_token)
            
            try:
                await bot.send_message(chat_id=str(user_telegram_id), text=message)
            except telegram.error.BadRequest as e:
                if "Chat not found" in str(e):
                    logger.warning(f"텔레그램 메시지 전송 실패 (Chat not found): {user_telegram_id} - {message}")
                else:
                    # 다른 BadRequest 오류는 다시 발생시킴
                    raise e
            
            # 디버그 모드인 경우 로그 출력
            if debug:
                logger.info(f"디버그 메시지 전송 완료: {user_telegram_id} - {message}")
        
        # 다음 메시지 처리
        asyncio.create_task(process_telegram_messages(user_id))
        
    except Exception as e:
        logger.error(f"텔레그램 메시지 처리 중 오류 발생: {str(e)}")
        traceback.print_exc()
        
        # 오류 발생 시 처리 중 플래그 제거
        processing_flag = MESSAGE_PROCESSING_FLAG.format(okx_uid=user_id)
        await redis_client.delete(processing_flag)

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
        elif sys.platform == 'win32':
            import win32process
            import win32api
            pid = win32api.GetCurrentProcessId()
            handle = win32api.OpenProcess(win32process.PROCESS_ALL_ACCESS, True, pid)
            win32process.SetPriorityClass(handle, win32process.BELOW_NORMAL_PRIORITY_CLASS)
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
        sys.exit(1) 