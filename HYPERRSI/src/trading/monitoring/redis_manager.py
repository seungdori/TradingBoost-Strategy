# src/trading/monitoring/redis_manager.py

"""
Redis 연결 관리 및 데이터 조회 모듈
"""

import asyncio
import gc
import json
import traceback
from datetime import datetime, timedelta
from typing import Dict, List

import psutil

from shared.database.redis import ping_redis as check_redis_connection, reconnect_redis
from shared.database.redis_helper import get_redis_client
from shared.database.redis_patterns import scan_keys_pattern
from shared.logging import get_logger

from .telegram_service import get_identifier
from .utils import MEMORY_CLEANUP_INTERVAL, ORDER_STATUS_CACHE_TTL, order_status_cache

logger = get_logger(__name__)


# Module-level attribute for backward compatibility
def __getattr__(name):
    if name == "redis_client":
        return get_redis_client()
    raise AttributeError(f"module has no attribute {name}")


async def get_all_running_users() -> List[int]:
    """
    현재 'running' 상태인 모든 user_id를 조회

    Returns:
        List[int]: 실행 중인 사용자 ID 목록
    """
    # 최대 재시도 횟수

    redis = await get_redis_client()
    max_retry = 3
    retry_count = 0

    while retry_count < max_retry:
        try:
            # Redis 연결 상태 확인
            if not await check_redis_connection():
                logger.warning(f"Redis 연결 상태 불량, 재연결 시도 ({retry_count+1}/{max_retry})")
                await reconnect_redis()

            # Use SCAN instead of KEYS to avoid blocking Redis (심볼별 상태 키 패턴)
            status_keys = await scan_keys_pattern("user:*:symbol:*:status", redis=redis)
            running_users = set()  # 중복 제거를 위해 set 사용

            for key in status_keys:
                status = await redis.get(key)
                if status == "running":
                    # key 구조: user:{user_id}:symbol:{symbol}:status
                    parts = key.split(":")
                    user_id = parts[1]
                    # OKX UID로 변환
                    okx_uid = await get_identifier(user_id)
                    running_users.add(int(okx_uid))

            return list(running_users)
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
        redis = await get_redis_client()
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
        import time
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
            # Use SCAN instead of KEYS to avoid blocking Redis
            old_order_keys = await scan_keys_pattern(pattern, redis=redis)

            for key in old_order_keys:
                try:
                    order_data = await redis.hgetall(key)
                    last_updated = int(order_data.get("last_updated_time", "0"))
                    if last_updated < two_weeks_ago:
                        logger.info(f"오래된 완료 주문 데이터 삭제: {key}")
                        await redis.delete(key)
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


async def check_websocket_health() -> bool:
    """
    WebSocket(position_monitor.py) 연결 상태를 확인합니다.
    Redis에 저장된 heartbeat 키를 기반으로 WebSocket이 정상 동작 중인지 판단합니다.

    Returns:
        bool: WebSocket이 정상이면 True, 비정상이면 False
    """
    try:
        redis = await get_redis_client()

        # position_monitor.py에서 주기적으로 업데이트하는 heartbeat 키 확인
        heartbeat_key = "ws:position_monitor:heartbeat"
        last_heartbeat = await redis.get(heartbeat_key)

        if not last_heartbeat:
            logger.debug("WebSocket heartbeat 키가 없습니다. (position_monitor.py 미실행 또는 초기 상태)")
            return False

        # bytes 타입 처리
        if isinstance(last_heartbeat, bytes):
            last_heartbeat = last_heartbeat.decode()

        # 60초 이내에 heartbeat가 있으면 정상
        import time
        current_time = time.time()
        time_diff = current_time - float(last_heartbeat)

        if time_diff < 60:
            return True
        else:
            logger.warning(f"WebSocket heartbeat 오래됨: {time_diff:.1f}초 전 (기준: 60초)")
            return False

    except Exception as e:
        logger.error(f"WebSocket 상태 확인 중 오류: {str(e)}")
        return False


async def get_user_monitor_orders(user_id: str) -> Dict[str, Dict]:
    """
    사용자의 모든 모니터링 중인 주문을 조회합니다.

    Args:
        user_id: 사용자 ID (텔레그램 ID 또는 OKX UID)

    Returns:
        Dict: {order_id: order_data, ...}
    """
    try:
        redis = await get_redis_client()
        # user_id를 OKX UID로 변환
        okx_uid = await get_identifier(str(user_id))

        # 사용자 주문 모니터링 키 패턴
        pattern = f"monitor:user:{okx_uid}:*:order:*"
        # Use SCAN instead of KEYS to avoid blocking Redis
        order_keys = await scan_keys_pattern(pattern, redis=redis)

        orders = {}
        for key in order_keys:
            try:
                # 키 타입 확인
                key_type = await redis.type(key)

                # 해시 타입인지 확인 - 문자열로 변환하여 비교
                if str(key_type).lower() == 'hash' or str(key_type).lower() == "b'hash'":
                    # 정상적인 해시 타입인 경우
                    order_data = await redis.hgetall(key)
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
