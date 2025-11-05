"""GRID 핵심 모듈

Redis 연결, WebSocket, 예외 처리 등 핵심 기능 제공

IMPORTANT: Use redis_context() for all Redis operations!
"""

from .exceptions import AddAnotherException, QuitException
from .redis import (
    get_redis_connection,  # Deprecated - use redis_context() instead
    redis_context,  # Recommended
    RedisTTL,
)

__all__ = [
    'QuitException',
    'AddAnotherException',
    'get_redis_connection',  # Deprecated
    'redis_context',  # Recommended
    'RedisTTL',
]
