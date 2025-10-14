"""
HYPERRSI Telegram 메시지 모듈 (하위 호환성 래퍼)

이 모듈은 하위 호환성을 위해 유지됩니다.
새로운 코드에서는 shared.notifications.telegram을 직접 사용하세요.
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

logger = logging.getLogger(__name__)

# 환경 변수
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ORDER_BACKEND = os.getenv("ORDER_BACKEND")


# ============================================================================
# Lazy redis_client import (의존성 분리)
# ============================================================================

async def _get_redis_client():
    """
    Redis 클라이언트를 lazy import합니다.

    이렇게 하면 이 모듈을 import할 때 prometheus_client 등의
    무거운 의존성을 불러오지 않습니다.
    """
    from shared.database.redis import get_redis
    return await get_redis()


# ============================================================================
# 하위 호환성 래퍼 함수들
# ============================================================================

async def get_telegram_id(identifier: str) -> int:
    """
    하위 호환성 래퍼: OKX UID를 Telegram ID로 변환

    Note: shared.notifications.telegram.get_telegram_id를 사용하세요.
    """
    return await _get_telegram_id(identifier, await _get_redis_client(), ORDER_BACKEND)


async def enqueue_telegram_message(message, okx_uid=str(587662504768345929), debug=False):
    """
    하위 호환성 래퍼: 텔레그램 메시지를 레디스 큐에 추가

    Note: shared.notifications.telegram.enqueue_telegram_message를 사용하세요.
    """
    return await _enqueue_telegram_message(message, okx_uid, await _get_redis_client(), debug)


async def process_telegram_messages(okx_uid, debug=False):
    """
    하위 호환성 래퍼: 레디스 큐에서 메시지를 가져와 순차적으로 전송

    Note: shared.notifications.telegram.process_telegram_messages를 사용하세요.
    """
    return await _process_telegram_messages(
        okx_uid, await _get_redis_client(), TELEGRAM_BOT_TOKEN, ORDER_BACKEND, debug
    )


async def send_telegram_message_direct(message, okx_uid=str(587662504768345929), debug=False):
    """
    하위 호환성 래퍼: 텔레그램으로 직접 메시지 전송

    Note: shared.notifications.telegram.send_telegram_message(use_queue=False)를 사용하세요.
    """
    return await _send_telegram_message(
        message, okx_uid, await _get_redis_client(), TELEGRAM_BOT_TOKEN, ORDER_BACKEND, debug, use_queue=False
    )


async def send_telegram_message(message, okx_uid=str(587662504768345929), debug=False):
    """
    하위 호환성 래퍼: 텔레그램 메시지를 큐에 추가

    Note: shared.notifications.telegram.send_telegram_message를 사용하세요.
    """
    return await _send_telegram_message(
        message, okx_uid, await _get_redis_client(), TELEGRAM_BOT_TOKEN, ORDER_BACKEND, debug, use_queue=True
    )


# ============================================================================
# 모듈 exports
# ============================================================================

__all__ = [
    # Classes
    'TelegramNotifier',
    'MessageType',
    # Functions
    'get_telegram_id',
    'enqueue_telegram_message',
    'process_telegram_messages',
    'send_telegram_message_direct',
    'send_telegram_message',
    # Constants
    'MESSAGE_QUEUE_KEY',
    'MESSAGE_PROCESSING_FLAG',
    'TELEGRAM_BOT_TOKEN',
    'ORDER_BACKEND',
]
