# src/trading/monitoring/utils.py

"""
HYPERRSI 모니터링 유틸리티 함수

이 모듈은 하위 호환성을 위해 shared 모듈의 함수들을 re-export합니다.
새로운 코드에서는 직접 shared 모듈에서 import하는 것을 권장합니다.
"""

import time

from shared.config.constants import (
    API_RATE_LIMIT,
    CONNECTION_TIMEOUT,
    LOG_INTERVAL_SECONDS,
    MAX_MEMORY_MB,
    MAX_RESTART_ATTEMPTS,
    MEMORY_CLEANUP_INTERVAL,
    MESSAGE_PROCESSING_FLAG,
    MESSAGE_QUEUE_KEY,
    MONITOR_INTERVAL,
    ORDER_CHECK_INTERVAL,
    ORDER_STATUS_CACHE_TTL,
    SUPPORTED_SYMBOLS,
)
from shared.database.redis_helper import get_redis_client
from shared.logging import get_logger

# shared 모듈에서 공통 유틸리티 import 및 re-export
from shared.utils import (
    convert_to_trading_symbol,
    get_actual_order_type,
    is_true_value,
)

logger = get_logger(__name__)

# Dynamic redis_client access


# Module-level attribute for backward compatibility
def __getattr__(name):
    if name == "redis_client":
        return get_redis_client()
    raise AttributeError(f"module has no attribute {name}")

# ============================================================================
# HYPERRSI 전용 전역 변수
# ============================================================================

# 상태 캐시 (HYPERRSI 모니터링 서비스 전용)
order_status_cache: dict[str, str] = {}
last_log_times: dict[str, float] = {}

# ============================================================================
# Redis 래퍼 함수 (하위 호환성 유지)
# ============================================================================

async def get_user_settings(user_id: str) -> dict:
    """
    사용자 설정을 가져옵니다.

    Note: 하위 호환성을 위한 래퍼 함수입니다.
    shared.utils.redis_utils.get_user_settings를 사용하세요.
    """
    from shared.database.redis_helper import get_redis_client
    from shared.utils.redis_utils import get_user_settings as _get_user_settings

    redis_client = await get_redis_client()
    result = await _get_user_settings(redis_client, user_id)
    return dict(result) if result else {}


async def add_recent_symbol(user_id: str, symbol: str) -> None:
    """
    최근 심볼을 추가합니다.

    Note: 하위 호환성을 위한 래퍼 함수입니다.
    shared.utils.add_recent_symbol을 사용하세요.
    """
    from shared.utils import add_recent_symbol as _add_recent_symbol
    redis = await get_redis_client()
    await _add_recent_symbol(redis, user_id, symbol)


async def get_recent_symbols(user_id: str) -> list:
    """
    최근 심볼 목록을 가져옵니다.

    Note: 하위 호환성을 위한 래퍼 함수입니다.
    shared.utils.get_recent_symbols을 사용하세요.
    """
    from shared.utils import get_recent_symbols as _get_recent_symbols
    redis = await get_redis_client()
    result = await _get_recent_symbols(redis, user_id)
    return list(result) if result else []


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
# Signal Bot 통합 청산 헬퍼 함수
# ============================================================================

async def close_position_with_signal_bot_support(
    user_id: str,
    symbol: str,
    side: str,
    current_price: float = 0.0,
    close_percent: int = 100,
    size: float | None = None,
    reason: str = "monitoring"
) -> bool:
    """
    Signal Bot 모드를 지원하는 통합 포지션 청산 함수.

    execution_mode가 signal_bot이면 SignalBotExecutor를 통해 EXIT_LONG/EXIT_SHORT를 전송하고,
    그렇지 않으면 기존 close_position API를 사용합니다.

    Args:
        user_id: 사용자 ID
        symbol: 거래 심볼 (예: "BTC-USDT-SWAP")
        side: 포지션 방향 ("long" | "short")
        current_price: 현재 가격 (API Direct 마켓 주문 시 선택적, 기본값 0)
        close_percent: 청산 비율 (기본 100%)
        size: 청산할 계약 수량 (Signal Bot 모드에서 contract 기반 청산 시 사용)
        reason: 청산 사유 (로깅용)

    Returns:
        bool: 청산 성공 여부
    """
    from HYPERRSI.src.trading.executors import ExecutorFactory
    from HYPERRSI.src.bot.telegram_message import send_telegram_message

    redis = await get_redis_client()

    try:
        # 1. 사용자 설정에서 execution_mode 확인
        settings = await get_user_settings(user_id)
        execution_mode = settings.get("execution_mode", "api_direct")
        signal_token = settings.get("signal_bot_token")

        # 2. Signal Bot 모드 분기
        if execution_mode == "signal_bot" and signal_token:
            logger.info(f"[{user_id}][SignalBot] Closing {side} position: {symbol} ({reason})")

            # Signal Bot Executor 생성
            executor = await ExecutorFactory.create_signal_bot_executor(
                user_id=user_id,
                signal_token=signal_token
            )

            try:
                # EXIT_LONG 또는 EXIT_SHORT 전송
                await executor.close_position(
                    symbol=symbol,
                    side=side,
                    size=size,  # None이면 percentage_position 100% 청산
                    close_percentage=close_percent if size is None else None
                )

                # 텔레그램 알림
                side_kr = "롱" if side == "long" else "숏"
                size_info = f"{size} contracts" if size else f"{close_percent}%"
                await send_telegram_message(
                    f"✅ [Signal Bot] {side_kr} 포지션 청산\n"
                    f"📊 심볼: {symbol}\n"
                    f"💰 수량: {size_info}\n"
                    f"📝 사유: {reason}",
                    user_id
                )

                logger.info(f"[{user_id}][SignalBot] Position closed: {symbol} {side} - {reason}")
                return True

            finally:
                await executor.close()

        # 3. API Direct 모드 (기존 로직)
        else:
            # Lazy import to avoid circular dependency
            from HYPERRSI.src.api.routes.order.models import ClosePositionRequest
            from HYPERRSI.src.api.routes.order.order import close_position

            close_request = ClosePositionRequest(
                close_type="market",
                price=current_price,
                close_percent=close_percent
            )

            await close_position(
                symbol=symbol,
                close_request=close_request,
                user_id=user_id,
                side=side
            )

            logger.info(f"[{user_id}][APIDirect] Position closed: {symbol} {side} - {reason}")
            return True

    except Exception as e:
        logger.error(f"[{user_id}] Failed to close position: {symbol} {side} - {str(e)}")
        import traceback
        traceback.print_exc()
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
    # Signal Bot support
    'close_position_with_signal_bot_support',
]
