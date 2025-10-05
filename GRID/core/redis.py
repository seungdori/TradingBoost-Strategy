"""Redis 연결 관리 (shared 모듈 활용)

이 모듈은 shared.database.RedisConnectionManager를 활용하여
GRID 프로젝트 전용 Redis 연결을 제공합니다.
"""
import redis.asyncio as aioredis
from shared.config import settings

# shared 모듈 재사용
from shared.utils.redis_utils import set_redis_data, get_redis_data, delete_redis_data, exists_redis_key

__all__ = [
    'get_redis_connection',
    'redis_client',
    'set_redis_data',
    'get_redis_data',
    'delete_redis_data',
    'exists_redis_key',
]


# Redis 연결 풀 설정
REDIS_PASSWORD = settings.REDIS_PASSWORD

if REDIS_PASSWORD:
    pool = aioredis.ConnectionPool.from_url(
        'redis://localhost',
        max_connections=200,
        encoding='utf-8',
        decode_responses=True,
        password=REDIS_PASSWORD
    )
    redis_client = aioredis.Redis(connection_pool=pool)
else:
    pool = aioredis.ConnectionPool.from_url(
        'redis://localhost',
        max_connections=200,
        encoding='utf-8',
        decode_responses=True
    )
    redis_client = aioredis.Redis(connection_pool=pool)


async def get_redis_connection():
    """
    Redis 연결을 반환합니다.

    Returns:
        aioredis.Redis: Redis 클라이언트 인스턴스
    """
    return redis_client
