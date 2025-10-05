"""비동기 유틸리티 함수"""
import asyncio
import logging
from typing import TypeVar, Callable, Any, Optional, Tuple
from functools import wraps

logger = logging.getLogger(__name__)

T = TypeVar('T')

async def retry_async(
    func: Callable[..., T],
    *args,
    max_retries: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: Tuple[type, ...] = (Exception,),
    on_retry: Optional[Callable] = None,
    **kwargs
) -> T:
    """
    비동기 함수 재시도 헬퍼

    Args:
        func: 재시도할 비동기 함수
        *args: 함수에 전달할 위치 인자
        max_retries: 최대 재시도 횟수
        delay: 초기 대기 시간 (초)
        backoff: 대기 시간 증가 배수
        exceptions: 재시도할 예외 타입 튜플
        on_retry: 재시도 시 호출할 콜백 함수
        **kwargs: 함수에 전달할 키워드 인자

    Returns:
        함수 실행 결과

    Raises:
        마지막 시도의 예외

    Usage:
        # 방법 1: 함수와 인자를 직접 전달
        result = await retry_async(my_func, arg1, arg2, max_retries=5)

        # 방법 2: 람다 사용
        result = await retry_async(lambda: my_func(arg1, arg2), max_retries=5)
    """
    last_exception = None
    current_delay = delay
    func_name = getattr(func, '__name__', 'unknown')

    for attempt in range(max_retries):
        try:
            return await func(*args, **kwargs)
        except exceptions as e:
            last_exception = e

            if attempt < max_retries - 1:
                logger.warning(
                    f"{func_name} failed on attempt {attempt + 1}/{max_retries}: {str(e)}. "
                    f"Retrying in {current_delay}s..."
                )

                if on_retry:
                    await on_retry(attempt, e)

                await asyncio.sleep(current_delay)
                current_delay *= backoff
            else:
                logger.error(f"{func_name}: All {max_retries} attempts failed. Last error: {str(e)}")

    raise last_exception


def retry_decorator(
    max_retries: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: Tuple[type, ...] = (Exception,)
):
    """
    비동기 함수 재시도 데코레이터

    Usage:
        @retry_decorator(max_retries=5, delay=2.0)
        async def my_function():
            ...
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            return await retry_async(
                lambda: func(*args, **kwargs),
                max_retries=max_retries,
                delay=delay,
                backoff=backoff,
                exceptions=exceptions
            )
        return wrapper
    return decorator
