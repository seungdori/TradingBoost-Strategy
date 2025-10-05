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


# ============================================================================
# 이벤트 루프 관리
# ============================================================================

def ensure_async_loop() -> asyncio.AbstractEventLoop:
    """
    현재 스레드에 사용 가능한 이벤트 루프를 반환하거나 새로 생성합니다.
    닫힌 루프나 다른 스레드의 루프는 사용하지 않습니다.

    Returns:
        asyncio.AbstractEventLoop: 사용 가능한 이벤트 루프

    Raises:
        RuntimeError: 예상치 못한 오류 발생 시

    Examples:
        >>> loop = ensure_async_loop()
        >>> loop.run_until_complete(my_async_function())

    Note:
        이 함수는 멀티스레드 환경에서 각 스레드가 자체 이벤트 루프를 가져야 할 때 유용합니다.
    """
    try:
        # 현재 실행 중인 루프가 있는지 확인
        loop = asyncio.get_running_loop()
        logger.debug("실행 중인 이벤트 루프를 사용합니다.")
        return loop
    except RuntimeError:
        # 현재 실행 중인 루프가 없는 경우
        pass

    try:
        # 기존 루프가 있는지 확인
        loop = asyncio.get_event_loop()

        # 루프가 닫혀있는지 확인
        if loop.is_closed():
            logger.info("기존 이벤트 루프가 닫혀 있어 새로 생성합니다")
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        return loop
    except RuntimeError as ex:
        # 루프가 아예 없는 경우
        if "There is no current event loop in thread" in str(ex):
            logger.info("이벤트 루프가 없어 새로 생성합니다")
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            return loop

        # 그 외 예상치 못한 오류
        logger.error(f"이벤트 루프 생성 중 오류 발생: {str(ex)}")
        raise


def get_or_create_event_loop() -> asyncio.AbstractEventLoop:
    """
    이벤트 루프를 가져오거나 생성합니다 (ensure_async_loop의 alias).

    Returns:
        asyncio.AbstractEventLoop: 이벤트 루프
    """
    return ensure_async_loop()
