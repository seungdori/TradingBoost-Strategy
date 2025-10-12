"""Redis 연결 관리 (shared 모듈 활용)

이 모듈은 shared.database.RedisConnectionManager를 활용하여
GRID 프로젝트 전용 Redis 연결을 제공합니다.
"""
import redis.asyncio as aioredis

from shared.config import settings

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


# Redis 연결 풀 설정
REDIS_PASSWORD = settings.REDIS_PASSWORD
REDIS_HOST = settings.REDIS_HOST
REDIS_PORT = settings.REDIS_PORT

# Redis URL 동적 생성
redis_url = f'redis://{REDIS_HOST}:{REDIS_PORT}'

# 연결 풀 설정 (패스워드 유무에 관계없이 동일한 구조 사용)
pool_config = {
    'max_connections': 200,
    'encoding': 'utf-8',
    'decode_responses': True
}

if REDIS_PASSWORD:
    pool_config['password'] = REDIS_PASSWORD

pool: aioredis.ConnectionPool = aioredis.ConnectionPool.from_url(redis_url, **pool_config)
redis_client = aioredis.Redis(connection_pool=pool)


async def get_redis_connection():
    """
    Redis 연결을 반환합니다.

    Returns:
        aioredis.Redis: Redis 클라이언트 인스턴스
    """
    return redis_client
