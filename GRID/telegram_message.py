"""
GRID Telegram 메시지 모듈

shared.notifications.telegram의 GRID 전용 래퍼

IMPORTANT: Uses redis_context() for proper connection management.
"""
import logging
import os

# shared 모듈에서 모든 기능 import
from shared.notifications.telegram import (
    MESSAGE_PROCESSING_FLAG,
    MESSAGE_QUEUE_KEY,
    MessageType,
    TelegramNotifier,
)
from shared.notifications.telegram import enqueue_telegram_message as _enqueue_telegram_message
from shared.notifications.telegram import get_telegram_id as _get_telegram_id
from shared.notifications.telegram import process_telegram_messages as _process_telegram_messages
from shared.notifications.telegram import send_telegram_message as _send_telegram_message

# GRID Redis context manager
from GRID.core.redis import redis_context

logger = logging.getLogger(__name__)

# 환경 변수
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ORDER_BACKEND = os.getenv("ORDER_BACKEND")


# ============================================================================
# 래퍼 함수들 - redis_context() 사용
# ============================================================================

async def get_telegram_id(identifier: str) -> int:
    """
    OKX UID를 Telegram ID로 변환

    Uses redis_context() for proper connection management.
    """
    async with redis_context() as redis:
        return await _get_telegram_id(identifier, redis, ORDER_BACKEND)


async def enqueue_telegram_message(message: str, okx_uid: str = str(587662504768345929), debug: bool = False) -> None:
    """
    텔레그램 메시지를 레디스 큐에 추가

    Uses redis_context() for proper connection management.
    """
    async with redis_context() as redis:
        return await _enqueue_telegram_message(message, okx_uid, redis, debug)


async def process_telegram_messages(okx_uid: str, debug: bool = False) -> None:
    """
    레디스 큐에서 메시지를 가져와 순차적으로 전송

    Uses redis_context() for proper connection management.
    """
    async with redis_context() as redis:
        return await _process_telegram_messages(
            okx_uid, redis, TELEGRAM_BOT_TOKEN, ORDER_BACKEND, debug
        )


async def send_telegram_message_direct(message: str, okx_uid: str = str(587662504768345929), debug: bool = False) -> None:
    """
    텔레그램으로 직접 메시지 전송 (큐 사용 안 함)

    Uses redis_context() for proper connection management.
    """
    async with redis_context() as redis:
        return await _send_telegram_message(
            message, okx_uid, redis, TELEGRAM_BOT_TOKEN, ORDER_BACKEND, debug, use_queue=False
        )


async def send_telegram_message(message: str, okx_uid: str = str(587662504768345929), debug: bool = False) -> None:
    """
    텔레그램 메시지를 큐에 추가 (기본 동작)

    Uses redis_context() for proper connection management.
    """
    async with redis_context() as redis:
        return await _send_telegram_message(
            message, okx_uid, redis, TELEGRAM_BOT_TOKEN, ORDER_BACKEND, debug, use_queue=True
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
