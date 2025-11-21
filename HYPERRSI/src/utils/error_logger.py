"""
Error Logging Utility for HYPERRSI

모든 에러를 errordb에 자동으로 기록하는 헬퍼 함수들.
"""

import asyncio
import inspect
from typing import Optional, Dict, Any
from functools import wraps

from shared.logging import get_logger

logger = get_logger(__name__)


def log_error_to_db(
    error: Exception,
    error_type: Optional[str] = None,
    user_id: Optional[str] = None,
    telegram_id: Optional[int] = None,
    severity: str = "ERROR",
    symbol: Optional[str] = None,
    side: Optional[str] = None,
    order_type: Optional[str] = None,
    position_info: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    **kwargs
):
    """
    에러를 errordb에 비동기로 기록 (동기 함수에서 호출 가능).

    Args:
        error: Exception 객체
        error_type: 에러 타입 (기본값: error.__class__.__name__)
        user_id: 사용자 ID
        telegram_id: 텔레그램 ID
        severity: 심각도 (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        symbol: 거래 심볼
        side: 포지션 방향
        order_type: 주문 타입
        position_info: 포지션 정보
        metadata: 추가 메타데이터
        **kwargs: 추가 파라미터
    """
    try:
        from HYPERRSI.src.database.hyperrsi_error_db import log_hyperrsi_error

        # 호출 위치 자동 추출
        frame = inspect.currentframe().f_back
        module = frame.f_globals.get('__name__', 'unknown')
        function_name = frame.f_code.co_name

        # 에러 타입 자동 결정
        if error_type is None:
            error_type = error.__class__.__name__

        # 비동기 태스크로 실행 (blocking 방지)
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            # 이벤트 루프가 없으면 새로 생성
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        # 이미 실행 중인 루프에서는 create_task, 아니면 run_until_complete
        if loop.is_running():
            asyncio.create_task(
                log_hyperrsi_error(
                    error=error,
                    error_type=error_type,
                    user_id=user_id,
                    telegram_id=telegram_id,
                    severity=severity,
                    module=module,
                    function_name=function_name,
                    symbol=symbol,
                    side=side,
                    order_type=order_type,
                    position_info=position_info,
                    metadata=metadata,
                    **kwargs
                )
            )
        else:
            # 동기 컨텍스트에서 호출된 경우
            loop.run_until_complete(
                log_hyperrsi_error(
                    error=error,
                    error_type=error_type,
                    user_id=user_id,
                    telegram_id=telegram_id,
                    severity=severity,
                    module=module,
                    function_name=function_name,
                    symbol=symbol,
                    side=side,
                    order_type=order_type,
                    position_info=position_info,
                    metadata=metadata,
                    **kwargs
                )
            )

    except Exception as e:
        # 에러 로깅 실패해도 원본 에러는 유지
        logger.error(f"Failed to log error to errordb: {e}")


async def async_log_error_to_db(
    error: Exception,
    error_type: Optional[str] = None,
    user_id: Optional[str] = None,
    telegram_id: Optional[int] = None,
    severity: str = "ERROR",
    symbol: Optional[str] = None,
    side: Optional[str] = None,
    order_type: Optional[str] = None,
    position_info: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    **kwargs
):
    """
    에러를 errordb에 기록 (비동기 함수용).

    Args:
        error: Exception 객체
        error_type: 에러 타입
        user_id: 사용자 ID
        telegram_id: 텔레그램 ID
        severity: 심각도
        symbol: 거래 심볼
        side: 포지션 방향
        order_type: 주문 타입
        position_info: 포지션 정보
        metadata: 추가 메타데이터
        **kwargs: 추가 파라미터
    """
    try:
        from HYPERRSI.src.database.hyperrsi_error_db import log_hyperrsi_error

        # 호출 위치 자동 추출
        frame = inspect.currentframe().f_back
        module = frame.f_globals.get('__name__', 'unknown')
        function_name = frame.f_code.co_name

        # 에러 타입 자동 결정
        if error_type is None:
            error_type = error.__class__.__name__

        await log_hyperrsi_error(
            error=error,
            error_type=error_type,
            user_id=user_id,
            telegram_id=telegram_id,
            severity=severity,
            module=module,
            function_name=function_name,
            symbol=symbol,
            side=side,
            order_type=order_type,
            position_info=position_info,
            metadata=metadata,
            **kwargs
        )

    except Exception as e:
        # 에러 로깅 실패해도 원본 에러는 유지
        logger.error(f"Failed to log error to errordb: {e}")


def with_error_logging(
    user_id: Optional[str] = None,
    telegram_id: Optional[int] = None,
    severity: str = "ERROR",
    reraise: bool = True
):
    """
    함수 데코레이터: 발생하는 에러를 자동으로 errordb에 기록.

    Usage:
        @with_error_logging(user_id="123", severity="CRITICAL")
        async def some_function():
            # 에러 발생 시 자동으로 DB에 기록
            pass

    Args:
        user_id: 사용자 ID
        telegram_id: 텔레그램 ID
        severity: 심각도
        reraise: 에러를 다시 raise할지 여부 (기본값: True)
    """
    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                # 에러 기록
                await async_log_error_to_db(
                    error=e,
                    user_id=user_id,
                    telegram_id=telegram_id,
                    severity=severity,
                    metadata={
                        'function': func.__name__,
                        'args': str(args)[:200],
                        'kwargs': str(kwargs)[:200],
                    }
                )
                if reraise:
                    raise

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                # 에러 기록
                log_error_to_db(
                    error=e,
                    user_id=user_id,
                    telegram_id=telegram_id,
                    severity=severity,
                    metadata={
                        'function': func.__name__,
                        'args': str(args)[:200],
                        'kwargs': str(kwargs)[:200],
                    }
                )
                if reraise:
                    raise

        # 비동기 함수인지 확인
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper

    return decorator
