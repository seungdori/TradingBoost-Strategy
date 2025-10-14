"""
Trading Cache Module - HYPERRSI-specific caching utilities

Provides Cache and TradingCache classes for efficient data caching
with Redis backend and local in-memory cache.
"""

import json
import time
from threading import Lock
from typing import Any, Dict, List, Optional, cast

from prometheus_client import Counter, Histogram

from shared.database.redis import get_redis
from shared.logging import get_logger
from shared.utils.async_helpers import retry_decorator

logger = get_logger(__name__)


class Cache:
    """Generic cache implementation with Redis backend and local cache"""

    # Prometheus metrics
    cache_hits = Counter('cache_hits_total', 'Cache hit count')
    cache_misses = Counter('cache_misses_total', 'Cache miss count')
    cache_operation_duration = Histogram('cache_operation_seconds', 'Cache operation duration')

    # Singleton pattern
    _instance = None
    _lock = Lock()

    def __init__(self):
        self._local_cache = {}
        self._cache_ttl = {}

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
            return cls._instance

    @retry_decorator(max_retries=3, delay=4.0, backoff=2.0)
    async def set(self, key: str, value: Any, expire: int = 3600) -> bool:
        """Set cache value in both local cache and Redis"""
        with self.cache_operation_duration.time():
            try:
                serialized = json.dumps(value) if not isinstance(value, str) else value
                # Store in local cache
                self._local_cache[key] = value
                self._cache_ttl[key] = time.time() + expire
                # Store in Redis
                redis = await get_redis()
                await redis.set(key, serialized, ex=expire)
                return True
            except Exception as e:
                logger.error(f"Cache set error: {e}")
                raise

    @retry_decorator(max_retries=3, delay=4.0, backoff=2.0)
    async def get(self, key: str) -> Optional[Any]:
        """Get cache value from local cache or Redis"""
        with self.cache_operation_duration.time():
            try:
                # Check local cache first
                if key in self._local_cache:
                    if time.time() < self._cache_ttl[key]:
                        self.cache_hits.inc()
                        return self._local_cache[key]
                    else:
                        # Expired, remove from local cache
                        del self._local_cache[key]
                        del self._cache_ttl[key]

                # Fetch from Redis
                redis = await get_redis()
                data = await redis.get(key)
                if data:
                    try:
                        parsed_data = json.loads(data)
                        # Update local cache
                        self._local_cache[key] = parsed_data
                        self.cache_hits.inc()
                        return parsed_data
                    except json.JSONDecodeError:
                        return data
                self.cache_misses.inc()
                return None
            except Exception as e:
                logger.error(f"Cache get error: {e}")
                return None

    async def delete(self, key: str) -> bool:
        """Delete cache value from both local cache and Redis"""
        try:
            if key in self._local_cache:
                del self._local_cache[key]
                del self._cache_ttl[key]
            redis = await get_redis()
            await redis.delete(key)
            return True
        except Exception as e:
            logger.error(f"Cache delete error: {e}")
            return False

    async def cleanup(self):
        """Clean up cache resources"""
        self._local_cache.clear()
        self._cache_ttl.clear()


class TradingCache:
    """Trading-specific cache management for positions and orders"""

    _instance: Optional["TradingCache"] = None
    _cache: Cache
    _lock = Lock()

    def __new__(cls) -> "TradingCache":
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._cache = Cache()
            return cls._instance

    async def bulk_get_positions(
        self, user_ids: List[str], symbol: str
    ) -> Dict[str, Optional[Dict[Any, Any]]]:
        """Bulk fetch positions for multiple users"""
        result: Dict[str, Optional[Dict[Any, Any]]] = {}
        for user_id in user_ids:
            key = f"position:{user_id}:{symbol}"
            position_data = await self._cache.get(key)
            if position_data and isinstance(position_data, dict):
                result[user_id] = cast(Dict[Any, Any], position_data)
            else:
                result[user_id] = None
        return result

    async def set_position(self, user_id: str, symbol: str, data: Dict[Any, Any]) -> bool:
        """Cache position data"""
        key = f"position:{user_id}:{symbol}"
        return await self._cache.set(key, data, expire=300)

    async def get_position(self, user_id: str, symbol: str) -> Optional[Dict[Any, Any]]:
        """Retrieve cached position data"""
        key = f"position:{user_id}:{symbol}"
        result = await self._cache.get(key)
        if result and isinstance(result, dict):
            return cast(Dict[Any, Any], result)
        return None

    async def set_order(self, order_id: str, data: Dict[Any, Any]) -> bool:
        """Cache order data"""
        key = f"order:{order_id}"
        return await self._cache.set(key, data, expire=3600)

    async def get_order(self, order_id: str) -> Optional[Dict[Any, Any]]:
        """Retrieve cached order data"""
        key = f"order:{order_id}"
        result = await self._cache.get(key)
        if result and isinstance(result, dict):
            return cast(Dict[Any, Any], result)
        return None

    async def cleanup(self) -> None:
        """Clean up trading cache resources"""
        await self._cache.cleanup()

    @classmethod
    async def remove_position(cls, user_id: str, symbol: str, side: str) -> bool:
        """Remove position from cache"""
        key = f"user:{user_id}:position:{symbol}:{side}"
        try:
            if not hasattr(cls, '_cache') or cls._cache is None:
                cls._cache = Cache()
            return await cls._cache.delete(key)
        except Exception as e:
            logger.error(f"Failed to remove position from cache: {str(e)}")
            return False


# Singleton instances
trading_cache = TradingCache()
