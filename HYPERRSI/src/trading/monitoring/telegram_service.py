# src/trading/monitoring/telegram_service.py

"""
텔레그램 메시징 서비스 모듈
"""

import asyncio
import json
import os
import traceback
import telegram
from typing import Optional, Dict
from shared.logging import get_logger

from .utils import MESSAGE_QUEUE_KEY, MESSAGE_PROCESSING_FLAG

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


async def send_telegram_message(message: str, okx_uid: str, debug: bool = False):
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


async def get_telegram_id_from_okx_uid(okx_uid: str) -> Optional[Dict]:
    """
    OKX UID를 텔레그램 ID로 변환하는 함수

    Args:
        okx_uid: OKX UID

    Returns:
        dict: 텔레그램 ID 정보 또는 None
    """
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


async def get_okx_uid_from_telegram_id(telegram_id: str) -> Optional[str]:
    """
    텔레그램 ID를 OKX UID로 변환하는 함수

    Args:
        telegram_id: 텔레그램 ID

    Returns:
        str: OKX UID 또는 None
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


async def process_telegram_messages(user_id: str):
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
