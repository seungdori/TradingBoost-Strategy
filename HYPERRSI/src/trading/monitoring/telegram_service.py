# src/trading/monitoring/telegram_service.py

"""
텔레그램 메시징 서비스 모듈
"""

import asyncio
import json
import os
import traceback
from typing import Dict, Optional

import telegram
from telegram.error import NetworkError, RetryAfter, TimedOut
from telegram.request import HTTPXRequest

from shared.database.redis_helper import get_redis_client
from shared.database.redis_patterns import scan_keys_pattern
from shared.helpers.user_id_resolver import is_telegram_id, TELEGRAM_ID_MAX_LENGTH
from shared.logging import get_logger

from .utils import MESSAGE_PROCESSING_FLAG, MESSAGE_QUEUE_KEY

logger = get_logger(__name__)
TELEGRAM_REQUEST_TIMEOUT = 10
MAX_SEND_RETRIES = 3
MAX_REQUEUE_ATTEMPTS = 3
REQUEUE_DELAY_BASE_SECONDS = 2


# Module-level attribute for backward compatibility
def __getattr__(name):
    if name == "redis_client":
        return get_redis_client()
    raise AttributeError(f"module has no attribute {name}")


def _create_bot(bot_token: str) -> telegram.Bot:
    """HTTPXRequest로 타임아웃을 강제한 Bot 인스턴스 생성."""
    request = HTTPXRequest(
        connect_timeout=TELEGRAM_REQUEST_TIMEOUT,
        read_timeout=TELEGRAM_REQUEST_TIMEOUT,
        write_timeout=TELEGRAM_REQUEST_TIMEOUT,
    )
    return telegram.Bot(token=bot_token, request=request)


async def _send_message_with_retry(
    bot: telegram.Bot,
    chat_id: str,
    message: str,
    attempt_offset: int = 0,
) -> bool:
    """
    텔레그램 메시지를 재시도하며 전송합니다.

    Returns:
        bool: 전송 성공 여부
    """
    for attempt in range(1, MAX_SEND_RETRIES + 1):
        try:
            await bot.send_message(
                chat_id=str(chat_id),
                text=message,
            )
            return True
        except RetryAfter as e:
            wait_seconds = max(float(getattr(e, "retry_after", 0)), 1.0)
            logger.warning(
                f"[{chat_id}] 텔레그램 API 제한 - {attempt + attempt_offset}차 시도,"
                f" {wait_seconds:.1f}s 후 재시도 예정: {str(e)}"
            )
            await asyncio.sleep(wait_seconds)
        except (TimedOut, NetworkError) as e:
            wait_seconds = min(REQUEUE_DELAY_BASE_SECONDS * (attempt + attempt_offset), 30)
            logger.warning(
                f"[{chat_id}] 텔레그램 메시지 전송 타임아웃 -"
                f" {attempt + attempt_offset}차 시도 실패, {wait_seconds:.1f}s 후 재시도: {str(e)}"
            )
            await asyncio.sleep(wait_seconds)

    return False


async def _requeue_message(
    redis,
    queue_key: str,
    processing_flag: str,
    message_data: dict,
    user_id: str,
    retry_count: int,
):
    """
    전송 실패한 메시지를 재큐잉하고 다음 처리를 예약합니다.
    """
    next_retry_count = retry_count + 1
    if next_retry_count > MAX_REQUEUE_ATTEMPTS:
        logger.error(
            f"[{user_id}] 텔레그램 메시지 전송 재시도 한도 초과 - 메시지 드롭: {message_data.get('message')}"
        )
        await redis.expire(processing_flag, 60)
        asyncio.create_task(process_telegram_messages(user_id))
        return

    message_data["retry_count"] = next_retry_count
    await redis.lpush(queue_key, json.dumps(message_data))
    await redis.expire(processing_flag, 60)

    delay_seconds = min(REQUEUE_DELAY_BASE_SECONDS * next_retry_count, 30)
    logger.warning(
        f"[{user_id}] 텔레그램 메시지 전송 실패 - {next_retry_count}차 재시도"
        f" {delay_seconds:.1f}s 후 진행 예정"
    )

    asyncio.create_task(_delayed_process(user_id, delay_seconds))


async def _delayed_process(user_id: str, delay_seconds: float):
    await asyncio.sleep(delay_seconds)
    await process_telegram_messages(user_id)


async def send_telegram_message(message: str, okx_uid: str, debug: bool = False):
    """
    텔레그램 메시지를 전송합니다.

    Args:
        message: 전송할 메시지
        okx_uid: 사용자 ID
        debug: 디버그 모드 여부
    """
    try:
        redis = await get_redis_client()
        # 메시지 큐에 추가
        message_data = {
            "type": "text",
            "message": message,
            "okx_uid": okx_uid,
            "debug": debug
        }

        if debug == True:
            okx_uid = str(586156710277369942)

        # 메시지 큐에 추가
        queue_key = MESSAGE_QUEUE_KEY.format(okx_uid=okx_uid)
        await redis.rpush(queue_key, json.dumps(message_data))

        # 메시지 처리 플래그 설정
        processing_flag = MESSAGE_PROCESSING_FLAG.format(okx_uid=okx_uid)
        await redis.set(processing_flag, "1", ex=60)  # 60초 후 만료

        if debug:
            okx_uid = str(586156710277369942)

        # 메시지 처리 태스크 시작
        asyncio.create_task(process_telegram_messages(okx_uid))

    except Exception as e:
        logger.error(f"텔레그램 메시지 전송 중 오류 발생: {str(e)}")
        traceback.print_exc()


async def get_telegram_id_from_okx_uid(okx_uid: str) -> Optional[Dict]:
    """
    OKX UID를 텔레그램 ID로 변환하는 함수

    Args:
        okx_uid: OKX UID

    Returns:
        dict: 텔레그램 ID 정보 또는 None
    """
    try:
        redis = await get_redis_client()
        # 모든 사용자 키를 검색하기 위한 패턴
        pattern = "user:*:okx_uid"
        # Use SCAN instead of KEYS to avoid blocking Redis
        keys = await scan_keys_pattern(pattern, redis=redis)

        valid_telegram_ids = []

        for key in keys:
            # Redis 키에서 저장된 OKX UID 값 가져오기
            stored_uid = await redis.get(key)

            # stored_uid 값 처리 (bytes일 수도 있고 str일 수도 있음)
            stored_uid_str = stored_uid.decode() if isinstance(stored_uid, bytes) else stored_uid

            # 요청된 OKX UID와 일치하는 경우
            if stored_uid and stored_uid_str == okx_uid:
                # user:123456789:okx_uid 형식에서 user_id(텔레그램 ID) 추출
                user_key = key.decode() if isinstance(key, bytes) else key
                user_id = user_key.split(':')[1]

                # 숫자로 시작하는 텔레그램 ID만 추가 (통합 기준: TELEGRAM_ID_MAX_LENGTH 이하)
                if is_telegram_id(user_id):
                    # 최근 활동 시간 확인 (가능한 경우)
                    last_activity = 0
                    try:
                        stats = await redis.hgetall(f"user:{user_id}:stats")
                        if stats and b'last_trade_date' in stats:
                            last_trade_date = stats[b'last_trade_date'] if isinstance(stats[b'last_trade_date'], bytes) else stats[b'last_trade_date'].encode()
                            last_activity = int(last_trade_date.decode() or '0')
                    except Exception as e:
                        print(f"통계 정보 가져오기 오류: {str(e)}")
                        pass

                    # telegram_id는 정수여야 하므로 안전하게 변환
                    try:
                        telegram_id = int(user_id)
                    except (ValueError, TypeError):
                        # UUID인 경우 건너뛰기 (텔레그램 ID가 아님)
                        continue

                    valid_telegram_ids.append({
                        "telegram_id": telegram_id,
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


async def get_okx_uid_from_telegram_id(telegram_id: str) -> Optional[str]:
    """
    텔레그램 ID를 OKX UID로 변환하는 함수

    Args:
        telegram_id: 텔레그램 ID

    Returns:
        str: OKX UID 또는 None
    """
    try:
        redis = await get_redis_client()
        # 텔레그램 ID로 OKX UID 조회
        okx_uid = await redis.get(f"user:{telegram_id}:okx_uid")
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

    Note:
        이 함수는 shared.helpers.user_id_resolver.resolve_user_identifier()를 권장합니다.
    """
    from shared.helpers.user_id_resolver import resolve_user_identifier
    return await resolve_user_identifier(str(user_id))


async def process_telegram_messages(user_id: str):
    """
    텔레그램 메시지 큐에서 메시지를 가져와 처리합니다.

    Args:
        user_id: 사용자 ID
    """
    try:
        redis = await get_redis_client()
        # 처리 중 플래그 확인
        processing_flag = MESSAGE_PROCESSING_FLAG.format(okx_uid=user_id)
        flag_exists = await redis.exists(processing_flag)

        if not flag_exists:
            return

        # 메시지 큐에서 메시지 가져오기
        queue_key = MESSAGE_QUEUE_KEY.format(okx_uid=user_id)
        message_data = await redis.lpop(queue_key)

        if not message_data:
            # 큐가 비어있으면 처리 중 플래그 제거
            await redis.delete(processing_flag)
            return

        # 메시지 데이터 파싱
        message_data = json.loads(message_data)
        message_type = message_data.get("type")
        message = message_data.get("message")
        debug = message_data.get("debug", False)
        retry_count = message_data.get("retry_count", 0)

        # 메시지 전송
        try:
            telegram_data = await get_telegram_id_from_okx_uid(user_id)
            if telegram_data and "primary_telegram_id" in telegram_data:
                user_telegram_id = telegram_data["primary_telegram_id"]
            else:
                logger.warning(f"[{user_id}] 텔레그램 ID 조회 실패 - 메시지 전송 건너뜀. OKX UID에 연결된 텔레그램 계정이 없습니다.")
                # 메시지를 전송할 수 없으므로 다음 메시지로 넘어감
                asyncio.create_task(process_telegram_messages(user_id))
                return
        except Exception as e:
            logger.error(f"[{user_id}] 텔레그램 ID 조회 중 오류: {str(e)}")
            traceback.print_exc()
            # 오류 발생 시에도 메시지 전송 건너뜀
            asyncio.create_task(process_telegram_messages(user_id))
            return

        # 메시지 타입에 따라 처리
        if message_type == "text":
            # 텔레그램 봇 토큰 가져오기
            bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
            if not bot_token:
                logger.error("텔레그램 봇 토큰이 설정되지 않았습니다.")
                return

            # 텔레그램 봇 생성
            bot = _create_bot(bot_token)

            try:
                send_success = await _send_message_with_retry(
                    bot,
                    user_telegram_id,
                    message,
                    attempt_offset=retry_count,
                )
                if not send_success:
                    await _requeue_message(
                        redis,
                        queue_key,
                        processing_flag,
                        message_data,
                        user_id,
                        retry_count,
                    )
                    return

                logger.debug(
                    f"[{user_id}] 텔레그램 메시지 전송 성공: chat_id={user_telegram_id}"
                )
            except telegram.error.BadRequest as e:
                if "Chat not found" in str(e):
                    logger.warning(f"[{user_id}] 텔레그램 메시지 전송 실패 (Chat not found): chat_id={user_telegram_id}")
                    logger.warning(f"[{user_id}] 해당 사용자가 봇을 시작(/start)하지 않았거나 차단한 것 같습니다.")
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
        await redis.delete(processing_flag)
