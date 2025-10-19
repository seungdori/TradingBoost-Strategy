"""Redis 연결 관리 (shared 모듈 활용)

이 모듈은 shared.database.redis의 전역 연결 풀을 사용하여
GRID 프로젝트의 Redis 연결을 제공합니다.

모든 연결은 shared 풀을 통해 관리되어 연결 고갈을 방지합니다.
"""

from shared.database.redis_patterns import redis_context, RedisTTL
from shared.database.redis import get_redis, RedisConnectionPool

# shared 모듈 재사용
from shared.utils.redis_utils import (
    delete_redis_data,
    exists_redis_key,
    get_redis_data,
    set_redis_data,
)

__all__ = [
    'get_redis_connection',
    'redis_client',
    'set_redis_data',
    'get_redis_data',
    'delete_redis_data',
    'exists_redis_key',
]


# Backward compatibility: redis_client은 deprecated
# 실제로는 get_redis_connection()을 사용해야 함
redis_client = None  # Will be initialized lazily


async def get_redis_connection():
    """
    Redis 연결을 반환합니다 (shared pool 사용).

    Returns:
        AsyncRedis: Redis 클라이언트 인스턴스
    """
    global redis_client
    if redis_client is None:
        redis_client = await get_redis()
    return redis_client
