"""Redis 캐싱 헬퍼 함수

거래소 데이터의 Redis 캐싱을 위한 공통 함수
"""
import json
from typing import Any, Optional, Callable, Awaitable
from redis.asyncio import Redis
from shared.logging import get_logger

logger = get_logger(__name__)


async def get_cached_data(
    redis_client: Redis,
    cache_key: str
) -> Optional[Any]:
    """
    Redis에서 캐시된 데이터 조회

    Args:
        redis_client: Redis 클라이언트
        cache_key: 캐시 키

    Returns:
        Optional[Any]: 캐시된 데이터 (없으면 None)
    """
    try:
        cached_data = await redis_client.get(cache_key)
        if cached_data:
            logger.debug(f"Cache hit for key: {cache_key}")
            return json.loads(cached_data)
        logger.debug(f"Cache miss for key: {cache_key}")
        return None
    except Exception as e:
        logger.error(f"Error getting cached data: {e}")
        return None


async def set_cached_data(
    redis_client: Redis,
    cache_key: str,
    data: Any,
    ttl: int = 300
) -> bool:
    """
    Redis에 데이터 캐싱

    Args:
        redis_client: Redis 클라이언트
        cache_key: 캐시 키
        data: 캐싱할 데이터
        ttl: 캐시 유효 시간 (초, 기본값: 300초 = 5분)

    Returns:
        bool: 캐싱 성공 여부
    """
    try:
        await redis_client.set(
            cache_key,
            json.dumps(data),
            ex=ttl
        )
        logger.debug(f"Cached data for key: {cache_key} (TTL: {ttl}s)")
        return True
    except Exception as e:
        logger.error(f"Error caching data: {e}")
        return False


async def invalidate_cache(
    redis_client: Redis,
    cache_key: str
) -> bool:
    """
    캐시 무효화

    Args:
        redis_client: Redis 클라이언트
        cache_key: 캐시 키

    Returns:
        bool: 무효화 성공 여부
    """
    try:
        await redis_client.delete(cache_key)
        logger.debug(f"Invalidated cache for key: {cache_key}")
        return True
    except Exception as e:
        logger.error(f"Error invalidating cache: {e}")
        return False


async def get_or_fetch(
    redis_client: Redis,
    cache_key: str,
    fetch_func: Callable[[], Awaitable[Any]],
    ttl: int = 300
) -> Optional[Any]:
    """
    캐시에서 데이터를 가져오거나, 없으면 fetch 함수를 호출하여 가져온 후 캐싱

    Args:
        redis_client: Redis 클라이언트
        cache_key: 캐시 키
        fetch_func: 데이터를 가져올 비동기 함수
        ttl: 캐시 유효 시간 (초)

    Returns:
        Optional[Any]: 조회된 데이터
    """
    # 캐시 조회
    cached_data = await get_cached_data(redis_client, cache_key)
    if cached_data is not None:
        return cached_data

    # 캐시 미스 - fetch 함수 호출
    try:
        data = await fetch_func()
        if data is not None:
            await set_cached_data(redis_client, cache_key, data, ttl)
        return data
    except Exception as e:
        logger.error(f"Error fetching data: {e}")
        return None
