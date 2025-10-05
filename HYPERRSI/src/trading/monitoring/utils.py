# src/trading/monitoring/utils.py

"""
HYPERRSI 모니터링 유틸리티 함수

이 모듈은 하위 호환성을 위해 shared 모듈의 함수들을 re-export합니다.
새로운 코드에서는 직접 shared 모듈에서 import하는 것을 권장합니다.
"""

import time
from HYPERRSI.src.core.logger import get_logger
from HYPERRSI.src.core.database import redis_client

# shared 모듈에서 공통 유틸리티 import 및 re-export
from shared.utils import (
    is_true_value,
    get_actual_order_type,
    convert_to_trading_symbol,
)
from shared.config.constants import (
    SUPPORTED_SYMBOLS,
    MESSAGE_QUEUE_KEY,
    MESSAGE_PROCESSING_FLAG,
    MONITOR_INTERVAL,
    ORDER_CHECK_INTERVAL,
    MAX_RESTART_ATTEMPTS,
    MAX_MEMORY_MB,
    MEMORY_CLEANUP_INTERVAL,
    CONNECTION_TIMEOUT,
    API_RATE_LIMIT,
    ORDER_STATUS_CACHE_TTL,
    LOG_INTERVAL_SECONDS
)

logger = get_logger(__name__)

# ============================================================================
# HYPERRSI 전용 전역 변수
# ============================================================================

# 상태 캐시 (HYPERRSI 모니터링 서비스 전용)
order_status_cache = {}
last_log_times = {}

# ============================================================================
# Redis 래퍼 함수 (하위 호환성 유지)
# ============================================================================

async def get_user_settings(user_id: str) -> dict:
    """
    사용자 설정을 가져옵니다.

    Note: 하위 호환성을 위한 래퍼 함수입니다.
    shared.utils.get_user_settings를 사용하세요.
    """
    from shared.utils import get_user_settings as _get_user_settings
    return await _get_user_settings(redis_client, user_id)


async def add_recent_symbol(user_id: str, symbol: str):
    """
    최근 심볼을 추가합니다.

    Note: 하위 호환성을 위한 래퍼 함수입니다.
    shared.utils.add_recent_symbol을 사용하세요.
    """
    from shared.utils import add_recent_symbol as _add_recent_symbol
    await _add_recent_symbol(redis_client, user_id, symbol)


async def get_recent_symbols(user_id: str) -> list:
    """
    최근 심볼 목록을 가져옵니다.

    Note: 하위 호환성을 위한 래퍼 함수입니다.
    shared.utils.get_recent_symbols을 사용하세요.
    """
    from shared.utils import get_recent_symbols as _get_recent_symbols
    return await _get_recent_symbols(redis_client, user_id)


# ============================================================================
# HYPERRSI 전용 유틸리티 함수
# ============================================================================

def should_log(log_key: str, interval_seconds: int = LOG_INTERVAL_SECONDS) -> bool:
    """
    지정된 키에 대해 로깅을 해야 하는지 확인합니다.
    (HYPERRSI 모니터링 서비스 전용 함수)

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


# ============================================================================
# 모듈 exports
# ============================================================================

__all__ = [
    # Re-exported from shared
    'is_true_value',
    'get_actual_order_type',
    'convert_to_trading_symbol',
    'SUPPORTED_SYMBOLS',
    'MESSAGE_QUEUE_KEY',
    'MESSAGE_PROCESSING_FLAG',
    'MONITOR_INTERVAL',
    'ORDER_CHECK_INTERVAL',
    'MAX_RESTART_ATTEMPTS',
    'MAX_MEMORY_MB',
    'MEMORY_CLEANUP_INTERVAL',
    'CONNECTION_TIMEOUT',
    'API_RATE_LIMIT',
    'ORDER_STATUS_CACHE_TTL',
    'LOG_INTERVAL_SECONDS',
    # Wrapper functions
    'get_user_settings',
    'add_recent_symbol',
    'get_recent_symbols',
    # HYPERRSI specific
    'order_status_cache',
    'last_log_times',
    'should_log',
]
