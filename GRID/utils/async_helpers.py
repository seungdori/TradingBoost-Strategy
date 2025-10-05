"""비동기 헬퍼 함수"""

import asyncio
import random
from datetime import datetime
from functools import wraps


def async_debounce(wait):
    """
    비동기 함수의 debounce 데코레이터입니다.

    Args:
        wait: 대기 시간 (초)

    Returns:
        데코레이터 함수

    Example:
        @async_debounce(1.0)
        async def my_function():
            pass
    """
    def decorator(fn):
        last_called = None
        task = None

        @wraps(fn)
        async def debounced(*args, **kwargs):
            nonlocal last_called, task
            current_time = asyncio.get_event_loop().time()

            if last_called is None or current_time - last_called >= wait:
                last_called = current_time
                if task:
                    task.cancel()
                task = asyncio.create_task(fn(*args, **kwargs))
                return await task

        return debounced
    return decorator


async def custom_sleep(timeframe):
    """
    다음 시간프레임까지 대기합니다.

    Args:
        timeframe: 시간프레임 문자열 (예: '15m', '1h')
    """
    from utils.time import calculate_next_timeframe_start

    now = datetime.now()
    next_timeframe_start = calculate_next_timeframe_start(now, timeframe)
    print(f"다음 타임프레임 시작 시간: {next_timeframe_start}")

    while datetime.now() < next_timeframe_start:
        await asyncio.sleep(random.uniform(0.5, 1.5))
