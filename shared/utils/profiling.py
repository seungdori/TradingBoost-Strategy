"""
성능 프로파일링 데코레이터

CPU 사용량과 실행 시간을 측정하는 유틸리티
"""
import time
import psutil
from functools import wraps
import asyncio
from typing import Callable, Any


def profile_cpu_and_time(func: Callable) -> Callable:
    """
    CPU 사용량과 실행 시간을 프로파일링하는 데코레이터

    Args:
        func: 프로파일링할 비동기 함수

    Returns:
        Callable: 래핑된 함수

    Examples:
        >>> @profile_cpu_and_time
        ... async def my_function():
        ...     await asyncio.sleep(1)
        ...
        >>> asyncio.run(my_function())
        Function: my_function
        Wall time: 1.0000 seconds
        CPU time: 0.0001 seconds
        CPU usage percentage: 0.01%
    """
    @wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        process = psutil.Process()
        start_time = time.time()
        start_cpu_time = process.cpu_times().user

        result = await func(*args, **kwargs)

        end_time = time.time()
        end_cpu_time = process.cpu_times().user

        cpu_usage = end_cpu_time - start_cpu_time
        wall_time = end_time - start_time

        print(f"Function: {func.__name__}")
        print(f"Wall time: {wall_time:.4f} seconds")
        print(f"CPU time: {cpu_usage:.4f} seconds")
        print(f"CPU usage percentage: {(cpu_usage / wall_time) * 100:.2f}%")

        return result

    return wrapper


def profile_sync(func: Callable) -> Callable:
    """
    동기 함수용 CPU 사용량과 실행 시간 프로파일링 데코레이터

    Args:
        func: 프로파일링할 동기 함수

    Returns:
        Callable: 래핑된 함수

    Examples:
        >>> @profile_sync
        ... def my_sync_function():
        ...     time.sleep(1)
        ...
        >>> my_sync_function()
        Function: my_sync_function
        Wall time: 1.0000 seconds
        CPU time: 0.0001 seconds
        CPU usage percentage: 0.01%
    """
    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        process = psutil.Process()
        start_time = time.time()
        start_cpu_time = process.cpu_times().user

        result = func(*args, **kwargs)

        end_time = time.time()
        end_cpu_time = process.cpu_times().user

        cpu_usage = end_cpu_time - start_cpu_time
        wall_time = end_time - start_time

        print(f"Function: {func.__name__}")
        print(f"Wall time: {wall_time:.4f} seconds")
        print(f"CPU time: {cpu_usage:.4f} seconds")
        if wall_time > 0:
            print(f"CPU usage percentage: {(cpu_usage / wall_time) * 100:.2f}%")

        return result

    return wrapper
