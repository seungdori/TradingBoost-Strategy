"""Helper utilities for accessing the shared Redis client.

이 모듈은 Redis 클라이언트를 지연 로딩(lazy load) 방식으로 제공하여
`get_redis_client().get(...)`와 같이 체이닝된 호출도 안전하게 동작하도록
Proxy 객체를 노출합니다. 기존처럼 `await get_redis_client()`로 실제 클라이언트를
획득하는 패턴 역시 그대로 지원합니다.
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any, Awaitable, Callable, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    import redis.asyncio as redis


class _RedisResultProxy:
    """Awaitable wrapper around lazily resolved Redis attributes or results."""

    def __init__(self, resolver: Callable[[], Awaitable[Any]]):
        self._resolver = resolver
        self._value: Any = None
        self._resolved = False

    async def _ensure(self) -> Any:
        if not self._resolved:
            self._value = await self._resolver()
            self._resolved = True
        return self._value

    def __await__(self):  # type: ignore[override]
        return self._ensure().__await__()

    async def __aenter__(self):
        value = await self._ensure()
        if hasattr(value, "__aenter__"):
            return await value.__aenter__()
        raise TypeError("Object is not an async context manager")

    async def __aexit__(self, exc_type, exc, tb):
        value = await self._ensure()
        if hasattr(value, "__aexit__"):
            return await value.__aexit__(exc_type, exc, tb)
        raise TypeError("Object is not an async context manager")

    def __call__(self, *args, **kwargs):
        async def _call():
            target = await self._ensure()
            if not callable(target):
                raise TypeError("Resolved object is not callable")
            result = target(*args, **kwargs)
            if inspect.isawaitable(result):
                result = await result
            return result

        return _RedisResultProxy(_call)

    def __getattr__(self, item: str):
        async def _get_attr():
            target = await self._ensure()
            attr = getattr(target, item)
            if inspect.isawaitable(attr):
                attr = await attr
            return attr

        return _RedisResultProxy(_get_attr)


class RedisClientProxy:
    """Proxy 객체로 Redis 클라이언트를 지연 로딩하여 노출한다."""

    def __init__(self) -> None:
        self._client: Optional["redis.Redis"] = None
        self._lock: Optional[asyncio.Lock] = None

    async def _ensure_client(self) -> "redis.Redis":
        if self._client is None:
            if self._lock is None:
                self._lock = asyncio.Lock()
            async with self._lock:
                if self._client is None:
                    from HYPERRSI.src.core.database import (
                        get_redis_client as get_async_client,
                    )

                    self._client = await get_async_client()
        return self._client

    def __await__(self):  # type: ignore[override]
        return self._ensure_client().__await__()

    def __getattr__(self, item: str):
        async def _resolver():
            client = await self._ensure_client()
            attr = getattr(client, item)
            if inspect.isawaitable(attr):
                attr = await attr
            return attr

        return _RedisResultProxy(_resolver)


_REDIS_PROXY = RedisClientProxy()


def get_redis_client() -> RedisClientProxy:
    """
    Redis 클라이언트 Proxy 반환.

    - `await get_redis_client()` : 실제 Redis 인스턴스 반환
    - `await get_redis_client().get("key")` : 체이닝된 비동기 호출 지원
    - `async with get_redis_client().pipeline() as pipe`: 파이프라인 컨텍스트 지원
    """

    return _REDIS_PROXY
