"""GRID 핵심 모듈

Redis 연결, WebSocket, 예외 처리 등 핵심 기능 제공
"""

from .exceptions import QuitException, AddAnotherException
from .redis import get_redis_connection, redis_client

__all__ = [
    'QuitException',
    'AddAnotherException',
    'get_redis_connection',
    'redis_client',
]
