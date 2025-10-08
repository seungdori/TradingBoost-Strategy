"""
Async Helper Utilities - Python 3.11+ TaskGroup Patterns

Modern async patterns using asyncio.TaskGroup for better error handling
and automatic task cancellation.
"""

import asyncio
import time
from typing import TypeVar, Callable, Any, Optional, Dict, List, AsyncIterator
from contextlib import asynccontextmanager
from shared.logging import get_logger

logger = get_logger(__name__)

T = TypeVar('T')


class TaskGroupHelper:
    """
    Helper class for TaskGroup operations with monitoring and error handling

    Features:
    - Automatic error propagation
    - Task timing and metrics
    - Graceful cancellation
    - Result aggregation
    """

    @staticmethod
    async def gather_with_timeout(
        tasks: Dict[str, Callable],
        timeout: float = 30.0,
        return_exceptions: bool = False
    ) -> Dict[str, Any]:
        """
        Run multiple async tasks in parallel with timeout using TaskGroup

        Args:
            tasks: Dictionary of task_name -> coroutine
            timeout: Maximum time to wait for all tasks (seconds)
            return_exceptions: If True, return exceptions instead of raising

        Returns:
            Dictionary of task_name -> result

        Example:
            results = await TaskGroupHelper.gather_with_timeout({
                'position': fetch_position(),
                'orders': fetch_orders(),
                'balance': fetch_balance()
            }, timeout=10.0)
        """
        results = {}
        errors = {}
        start_time = time.time()

        try:
            async with asyncio.timeout(timeout):
                async with asyncio.TaskGroup() as tg:
                    # Create all tasks
                    task_handles: dict[str, asyncio.Task[Any]] = {}
                    for name, coro in tasks.items():
                        task_handles[name] = tg.create_task(coro, name=name)

                # Tasks completed - collect results
                for name, task in task_handles.items():
                    try:
                        results[name] = task.result()
                    except Exception as e:
                        if return_exceptions:
                            errors[name] = e
                            logger.warning(f"Task '{name}' failed: {e}")
                        else:
                            raise

        except TimeoutError:
            elapsed = time.time() - start_time
            logger.error(f"TaskGroup timeout after {elapsed:.2f}s")
            if not return_exceptions:
                raise
            errors['_timeout'] = TimeoutError(f"Timeout after {elapsed:.2f}s")
        except ExceptionGroup as eg:
            # Handle ExceptionGroup from TaskGroup
            for exc in eg.exceptions:
                logger.error(f"Task failed: {exc}")
                if not return_exceptions:
                    raise exc from None

        elapsed = time.time() - start_time
        logger.info(
            f"TaskGroup completed in {elapsed:.3f}s",
            extra={
                "task_count": len(tasks),
                "success_count": len(results),
                "error_count": len(errors),
                "elapsed_seconds": elapsed
            }
        )

        if errors and not return_exceptions:
            raise Exception(f"Tasks failed: {list(errors.keys())}")

        return {**results, **({'_errors': errors} if errors else {})}

    @staticmethod
    async def map_concurrent(
        items: List[Any],
        async_func: Callable[[Any], Any],
        max_concurrency: int = 10,
        timeout: Optional[float] = None
    ) -> List[Any]:
        """
        Map async function over items with controlled concurrency

        Args:
            items: List of items to process
            async_func: Async function to apply to each item
            max_concurrency: Maximum concurrent tasks
            timeout: Optional timeout per batch

        Returns:
            List of results in same order as input

        Example:
            user_ids = ['user1', 'user2', 'user3']
            positions = await TaskGroupHelper.map_concurrent(
                user_ids,
                lambda uid: fetch_position(uid),
                max_concurrency=5
            )
        """
        if not items:
            return []

        semaphore = asyncio.Semaphore(max_concurrency)

        async def bounded_task(item):
            async with semaphore:
                return await async_func(item)

        try:
            if timeout:
                async with asyncio.timeout(timeout):
                    async with asyncio.TaskGroup() as tg:
                        tasks = [tg.create_task(bounded_task(item)) for item in items]
            else:
                async with asyncio.TaskGroup() as tg:
                    tasks = [tg.create_task(bounded_task(item)) for item in items]

            return [task.result() for task in tasks]

        except* Exception as eg:
            logger.error(f"Concurrent mapping failed: {eg.exceptions}")
            raise

    @staticmethod
    @asynccontextmanager
    async def measure_time(operation_name: str) -> AsyncIterator[None]:
        """
        Context manager to measure async operation time

        Example:
            async with TaskGroupHelper.measure_time("fetch_all_data"):
                data = await fetch_data()
        """
        start = time.time()
        try:
            yield
        finally:
            elapsed = time.time() - start
            logger.info(
                f"Operation '{operation_name}' took {elapsed:.3f}s",
                extra={"operation": operation_name, "elapsed_seconds": elapsed}
            )


class RetryHelper:
    """
    Advanced retry helper with exponential backoff and jitter
    """

    @staticmethod
    async def retry_with_backoff(
        async_func: Callable,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        exponential_base: float = 2.0,
        jitter: bool = True,
        exceptions: tuple = (Exception,)
    ) -> Any:
        """
        Retry async function with exponential backoff

        Args:
            async_func: Async function to retry
            max_retries: Maximum number of retry attempts
            base_delay: Initial delay between retries (seconds)
            max_delay: Maximum delay between retries (seconds)
            exponential_base: Base for exponential backoff
            jitter: Add random jitter to delay
            exceptions: Tuple of exceptions to catch

        Returns:
            Result of async_func

        Example:
            result = await RetryHelper.retry_with_backoff(
                lambda: api_call(),
                max_retries=5,
                base_delay=2.0
            )
        """
        import random

        last_exception = None

        for attempt in range(max_retries + 1):
            try:
                return await async_func()
            except exceptions as e:
                last_exception = e

                if attempt == max_retries:
                    logger.error(
                        f"All {max_retries} retries failed",
                        extra={"exception": str(e)}
                    )
                    raise

                # Calculate delay with exponential backoff
                delay = min(base_delay * (exponential_base ** attempt), max_delay)

                # Add jitter (0-25% of delay)
                if jitter:
                    jitter_amount = delay * random.uniform(0, 0.25)
                    delay += jitter_amount

                logger.warning(
                    f"Attempt {attempt + 1}/{max_retries} failed, retrying in {delay:.2f}s",
                    extra={
                        "attempt": attempt + 1,
                        "max_retries": max_retries,
                        "delay": delay,
                        "exception": str(e)
                    }
                )

                await asyncio.sleep(delay)

        raise last_exception


class CacheHelper:
    """
    Advanced caching helper with TTL and size limits
    """

    def __init__(self, max_size: int = 1000, default_ttl: float = 300.0):
        self._cache: Dict[str, Any] = {}
        self._cache_times: Dict[str, float] = {}
        self._access_counts: Dict[str, int] = {}
        self.max_size = max_size
        self.default_ttl = default_ttl
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Optional[Any]:
        """Get value from cache with TTL check"""
        async with self._lock:
            if key not in self._cache:
                return None

            # Check TTL
            if time.time() - self._cache_times[key] > self.default_ttl:
                await self._evict(key)
                return None

            # Update access count for LFU
            self._access_counts[key] = self._access_counts.get(key, 0) + 1
            return self._cache[key]

    async def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        """Set value in cache with optional TTL"""
        async with self._lock:
            # Evict if cache is full
            if len(self._cache) >= self.max_size:
                await self._evict_lfu()

            self._cache[key] = value
            self._cache_times[key] = time.time()
            self._access_counts[key] = 1

    async def _evict(self, key: str) -> None:
        """Evict single key"""
        self._cache.pop(key, None)
        self._cache_times.pop(key, None)
        self._access_counts.pop(key, None)

    async def _evict_lfu(self) -> None:
        """Evict least frequently used item"""
        if not self._access_counts:
            return

        lfu_key = min(self._access_counts, key=lambda k: self._access_counts.get(k, 0))
        await self._evict(lfu_key)

    async def clear(self) -> None:
        """Clear entire cache"""
        async with self._lock:
            self._cache.clear()
            self._cache_times.clear()
            self._access_counts.clear()

    @property
    def size(self) -> int:
        """Current cache size"""
        return len(self._cache)
