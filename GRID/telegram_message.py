"""
GRID Telegram 메시지 모듈

shared.notifications.telegram의 GRID 전용 래퍼
"""
import os
import logging
from typing import Any

# shared 모듈에서 모든 기능 import
from shared.notifications.telegram import (
    TelegramNotifier,
    MessageType,
    get_telegram_id as _get_telegram_id,
    enqueue_telegram_message as _enqueue_telegram_message,
    process_telegram_messages as _process_telegram_messages,
    send_telegram_message as _send_telegram_message,
    MESSAGE_QUEUE_KEY,
    MESSAGE_PROCESSING_FLAG
)

logger = logging.getLogger(__name__)

# 환경 변수
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ORDER_BACKEND = os.getenv("ORDER_BACKEND")


# ============================================================================
# Lazy redis_client import (의존성 분리)
# ============================================================================

def _get_redis_client() -> Any:
    """
    Redis 클라이언트를 lazy import합니다.

    GRID의 Redis 클라이언트를 사용합니다.
    """
    from GRID.core.redis import redis_client
    return redis_client


# ============================================================================
# 래퍼 함수들
# ============================================================================

async def get_telegram_id(identifier: str) -> int:
    """
    OKX UID를 Telegram ID로 변환
    """
    return await _get_telegram_id(identifier, _get_redis_client(), ORDER_BACKEND)


async def enqueue_telegram_message(message: str, okx_uid: str = str(587662504768345929), debug: bool = False) -> None:
    """
    텔레그램 메시지를 레디스 큐에 추가
    """
    return await _enqueue_telegram_message(message, okx_uid, _get_redis_client(), debug)


async def process_telegram_messages(okx_uid: str, debug: bool = False) -> None:
    """
    레디스 큐에서 메시지를 가져와 순차적으로 전송
    """
    return await _process_telegram_messages(
        okx_uid, _get_redis_client(), TELEGRAM_BOT_TOKEN, ORDER_BACKEND, debug
    )


async def send_telegram_message_direct(message: str, okx_uid: str = str(587662504768345929), debug: bool = False) -> None:
    """
    텔레그램으로 직접 메시지 전송 (큐 사용 안 함)
    """
    return await _send_telegram_message(
        message, okx_uid, _get_redis_client(), TELEGRAM_BOT_TOKEN, ORDER_BACKEND, debug, use_queue=False
    )


async def send_telegram_message(message: str, okx_uid: str = str(587662504768345929), debug: bool = False) -> None:
    """
    텔레그램 메시지를 큐에 추가 (기본 동작)
    """
    return await _send_telegram_message(
        message, okx_uid, _get_redis_client(), TELEGRAM_BOT_TOKEN, ORDER_BACKEND, debug, use_queue=True
    )


# ============================================================================
# 모듈 exports
# ============================================================================

__all__ = [
    'TelegramNotifier',
    'MessageType',
    'get_telegram_id',
    'enqueue_telegram_message',
    'process_telegram_messages',
    'send_telegram_message_direct',
    'send_telegram_message',
    'MESSAGE_QUEUE_KEY',
    'MESSAGE_PROCESSING_FLAG',
]
