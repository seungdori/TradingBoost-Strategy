#src/services/redis_service.py
"""
Redis Service - Migrated to New Infrastructure

Manages user settings, API keys, and caching with structured logging
and exception handling. Includes automatic stale cache cleanup.

Updated: 2025-10-22 - Added timeout protection for all Redis operations
"""

import asyncio
import json
import os
import time
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from prometheus_client import Counter, Histogram
from redis.asyncio import Redis

from shared.constants.default_settings import (
    DEFAULT_PARAMS_SETTINGS,
    DIRECTION_OPTIONS,
    ENTRY_OPTIONS,
    SETTINGS_CONSTRAINTS,
    TP_SL_OPTIONS,
)
from shared.database.redis import get_redis, RedisConnectionPool
from shared.database.redis_helper import get_redis_client
from shared.database.redis_patterns import RedisTimeout, RedisTTL, redis_context  # Import timeout, TTL, and context manager
from shared.errors import ConfigurationException, DatabaseException, ValidationException
from shared.logging import get_logger
from shared.security import encrypt_api_key, decrypt_api_key, EncryptionError
from shared.utils import retry_decorator

logger = get_logger(__name__)

# Default timeout for Redis operations in this service
DEFAULT_REDIS_TIMEOUT = RedisTimeout.NORMAL_OPERATION  # 5 seconds

class RedisService:
    _instance = None
    _redis = None
    _pool = None
    _cleanup_task: Optional[asyncio.Task] = None
    _cleanup_interval = 60  # Clean stale cache every 60 seconds
        # 모니터링 메트릭
    cache_hits = Counter('redis_hits_total', 'Redis hit count')
    cache_misses = Counter('redis_misses_total', 'Redis miss count')
    operation_duration = Histogram('redis_operation_seconds', 'Redis operation duration')


    def __new__(cls, *args, **kwargs):
        # 외부 redis 클라이언트가 제공된 경우 새 인스턴스 생성
        if 'external_redis' in kwargs and kwargs['external_redis'] is not None:
            return super().__new__(cls)

        # Simple singleton pattern without lock (safe for single-threaded async)
        # Python's GIL and __new__ atomicity ensure thread safety for this simple check
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._pool = None
            cls._redis = None
        return cls._instance

    def __init__(self, host=None, port=None, db=None, password=None, external_redis=None):
        # 외부 redis 클라이언트가 제공된 경우, 그것을 사용
        if external_redis is not None:
            self._redis = external_redis
            self._local_cache: Dict[str, Any] = {}  # 메모리 캐시 추가
            self._cache_ttl: Dict[str, float] = {}
            logger.info("RedisService initialized with external Redis client")
            return

        # 이미 초기화 된 경우 중복 초기화 방지
        if self._redis is not None and self == RedisService._instance:
            return

        # shared 연결 풀 사용 (중복 풀 생성 방지)
        try:
            # shared.database.redis의 전역 풀 사용
            # 실제 Redis 클라이언트는 _get_redis() 메서드에서 비동기로 획득
            self._pool = None  # shared 풀 사용으로 독립 풀 불필요
            self._redis = None  # 지연 초기화 (async context에서만 접근)
            self._local_cache = {}  # 메모리 캐시 추가
            self._cache_ttl = {}

            # Start cache cleanup task (will be initialized when event loop is available)
            self._cleanup_task = None

        except Exception as e:
            logger.error(f"Redis initialization failed: {e}")
            raise

    async def start_cleanup_task(self) -> None:
        """
        Start background task for periodic cache cleanup.

        This should be called from async context (e.g., FastAPI lifespan).
        """
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._cleanup_stale_cache())
            logger.info(f"Cache cleanup task started (interval: {self._cleanup_interval}s)")

    async def _cleanup_stale_cache(self) -> None:
        """
        Background task that periodically removes stale cache entries.

        Runs every _cleanup_interval seconds and removes entries
        whose TTL has expired.
        """
        try:
            while True:
                await asyncio.sleep(self._cleanup_interval)

                now = time.time()
                expired_keys = [
                    key for key, ttl in self._cache_ttl.items()
                    if ttl < now
                ]

                for key in expired_keys:
                    self._local_cache.pop(key, None)
                    self._cache_ttl.pop(key, None)

                if expired_keys:
                    logger.debug(f"Cleaned {len(expired_keys)} stale cache entries")

        except asyncio.CancelledError:
            logger.info("Cache cleanup task cancelled")
            raise
        except Exception as e:
            logger.error(f"Error in cache cleanup task: {e}", exc_info=True)


    async def _ensure_redis(self) -> Redis:
        """Ensure Redis client is initialized from shared pool"""
        if self._redis is None:
            self._redis = await get_redis()
        return self._redis

    @property
    def redis(self):
        """
        Deprecated: Use async methods instead.
        This property is kept for backward compatibility but will return None.
        """
        logger.warning("Accessing .redis property synchronously is deprecated. Use async methods.")
        return self._redis

    async def ping(self) -> None:
        try:
            async with redis_context(timeout=RedisTimeout.FAST_OPERATION) as redis:
                await redis.ping()
                logger.info("Redis connection established successfully")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {str(e)}")
            raise

    async def close(self) -> None:
        """Close is handled by shared pool, no-op here"""
        logger.info("RedisService close() called - connection managed by shared pool")
        self._redis = None

    @property
    def is_connected(self) -> bool:
        """Check if Redis client exists (actual connection checked via ping)"""
        return self._redis is not None
    
    @retry_decorator(max_retries=3, delay=4.0, backoff=2.0)
    async def get_user_settings(self, user_id: str) -> Optional[Dict[str, Any]]:
        with self.operation_duration.time():
            try:
                # 먼저 로컬 캐시 확인
                cache_key = f"user:{user_id}:settings"
                if cache_key in self._local_cache:
                    if time.time() < self._cache_ttl.get(cache_key, 0):
                        self.cache_hits.inc()
                        cached_value: Dict[str, Any] = self._local_cache[cache_key]
                        return cached_value
                    else:
                        del self._local_cache[cache_key]
                        del self._cache_ttl[cache_key]

                async with redis_context(timeout=DEFAULT_REDIS_TIMEOUT) as redis:
                    # Redis에서 조회
                    settings = await redis.get(cache_key)
                    if not settings:
                        self.cache_misses.inc()
                        return None

                    user_settings: Dict[str, Any] = json.loads(settings)
                    updated = False

                    # 기본값 확인 및 업데이트
                    for k, v in DEFAULT_PARAMS_SETTINGS.items():
                        if k not in user_settings:
                            user_settings[k] = v
                            updated = True

                    if updated:
                        # Save without TTL (permanent storage)
                        await redis.set(cache_key, json.dumps(user_settings))

                    # 로컬 캐시 업데이트
                    self._local_cache[cache_key] = user_settings
                    self._cache_ttl[cache_key] = time.time() + 30  # 30초 캐시

                    return user_settings

            except Exception as e:
                logger.error(f"Error getting user settings: {e}")
                raise


    async def set_user_settings(self, user_id: str, settings: dict) -> None:
        with self.operation_duration.time():
            try:
                cache_key = f"user:{user_id}:settings"

                async with redis_context(timeout=DEFAULT_REDIS_TIMEOUT) as redis:
                    # Redis 업데이트 (no TTL - permanent storage)
                    await redis.set(cache_key, json.dumps(settings))

                # 로컬 캐시 업데이트 (즉시 반영)
                self._local_cache[cache_key] = settings
                self._cache_ttl[cache_key] = time.time() + 300

                # PUBLISH to notify other instances to invalidate their cache
                await redis.publish(f"settings:update:{user_id}", cache_key)
            except Exception as e:
                logger.error(f"Error setting user settings: {e}")
                raise
    async def get_multiple_user_settings(self, user_ids: List[str]) -> Dict[str, Optional[Dict[str, Any]]]:
        """
        여러 사용자의 설정을 한 번에 조회 (배치 작업 - 개선됨)

        Pipeline을 사용하여 단일 왕복으로 여러 설정을 가져옵니다.
        개별 조회 대비 50-80% 빠릅니다.

        Args:
            user_ids: 사용자 ID 리스트

        Returns:
            {user_id: settings_dict}
        """
        with self.operation_duration.time():
            try:
                async with redis_context(timeout=RedisTimeout.PIPELINE) as redis:
                    pipeline = redis.pipeline()
                    for user_id in user_ids:
                        pipeline.get(f"user:{user_id}:settings")

                    results = await pipeline.execute()

                    parsed_results: Dict[str, Optional[Dict[str, Any]]] = {}
                    for user_id, result in zip(user_ids, results):
                        if result:
                            try:
                                parsed_results[user_id] = json.loads(result)
                                # 로컬 캐시 업데이트
                                cache_key = f"user:{user_id}:settings"
                                self._local_cache[cache_key] = parsed_results[user_id]
                                self._cache_ttl[cache_key] = time.time() + 30
                            except json.JSONDecodeError:
                                parsed_results[user_id] = None
                        else:
                            parsed_results[user_id] = None

                    logger.info(f"Batch fetched {len(user_ids)} user settings")
                    return parsed_results

            except Exception as e:
                logger.error(f"Error in batch get_multiple_user_settings: {e}")
                raise

    async def set_multiple_user_settings(self, settings_dict: Dict[str, Dict[str, Any]]) -> None:
        """
        여러 사용자의 설정을 한 번에 저장 (배치 작업 - 신규)

        Pipeline을 사용하여 단일 왕복으로 여러 설정을 저장합니다.

        Args:
            settings_dict: {user_id: settings}
        """
        with self.operation_duration.time():
            try:
                async with redis_context(timeout=RedisTimeout.PIPELINE) as redis:
                    pipeline = redis.pipeline()
                    for user_id, settings in settings_dict.items():
                        cache_key = f"user:{user_id}:settings"
                        # Save without TTL (permanent storage)
                        pipeline.set(cache_key, json.dumps(settings))
                        # 로컬 캐시 업데이트
                        self._local_cache[cache_key] = settings
                        self._cache_ttl[cache_key] = time.time() + 300

                    await pipeline.execute()
                    logger.info(f"Batch saved {len(settings_dict)} user settings")

            except Exception as e:
                logger.error(f"Error in batch set_multiple_user_settings: {e}")
                raise

    async def get_many(self, keys: List[str]) -> Dict[str, Any]:
        """
        여러 키의 값을 한 번에 조회 (범용 배치 작업 - 신규)

        Args:
            keys: Redis 키 리스트

        Returns:
            {key: value}
        """
        with self.operation_duration.time():
            try:
                # 먼저 로컬 캐시 확인
                results: Dict[str, Any] = {}
                missing_keys: List[str] = []

                for key in keys:
                    if key in self._local_cache:
                        if time.time() < self._cache_ttl.get(key, 0):
                            results[key] = self._local_cache[key]
                            self.cache_hits.inc()
                            continue
                        else:
                            del self._local_cache[key]
                            del self._cache_ttl[key]
                    missing_keys.append(key)

                # Redis에서 없는 키들 조회
                if missing_keys:
                    async with redis_context(timeout=RedisTimeout.PIPELINE) as redis:
                        pipeline = redis.pipeline()
                        for key in missing_keys:
                            pipeline.get(key)

                        redis_results = await pipeline.execute()

                        for key, value in zip(missing_keys, redis_results):
                            if value:
                                try:
                                    parsed = json.loads(value)
                                    results[key] = parsed
                                    # 로컬 캐시 업데이트
                                    self._local_cache[key] = parsed
                                    self._cache_ttl[key] = time.time() + 30
                                    self.cache_hits.inc()
                                except json.JSONDecodeError:
                                    results[key] = value
                            else:
                                self.cache_misses.inc()

                logger.debug(f"Batch get: {len(keys)} keys, {len(results)} found")
                return results

            except Exception as e:
                logger.error(f"Error in batch get_many: {e}")
                raise

    async def set_many(self, items: Dict[str, Any], ttl: int = 300) -> None:
        """
        여러 키-값 쌍을 한 번에 저장 (범용 배치 작업 - 신규)

        Args:
            items: {key: value} 딕셔너리
            ttl: TTL (초)
        """
        with self.operation_duration.time():
            try:
                async with redis_context(timeout=RedisTimeout.PIPELINE) as redis:
                    pipeline = redis.pipeline()
                    for key, value in items.items():
                        if isinstance(value, (dict, list)):
                            serialized = json.dumps(value)
                        else:
                            serialized = str(value)
                        pipeline.setex(key, ttl, serialized)

                        # 로컬 캐시 업데이트
                        self._local_cache[key] = value
                        self._cache_ttl[key] = time.time() + ttl

                    await pipeline.execute()
                    logger.debug(f"Batch set: {len(items)} keys")

            except Exception as e:
                logger.error(f"Error in batch set_many: {e}")
                raise

    async def cleanup(self) -> None:
        """
        Clean up Redis resources, local cache, and background tasks.

        Properly closes Redis connection, cancels cleanup task, and clears cache.
        """
        try:
            # Cancel cleanup task if running
            if self._cleanup_task and not self._cleanup_task.done():
                self._cleanup_task.cancel()
                try:
                    await self._cleanup_task
                except asyncio.CancelledError:
                    pass
                logger.debug("Cache cleanup task cancelled")

            # Close Redis connection if it exists
            if self._redis is not None:
                await self._redis.close()
                logger.debug("Redis connection closed")
                self._redis = None

            # Clear local cache
            self._local_cache.clear()
            self._cache_ttl.clear()

            logger.info("RedisService cleanup completed")
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")



redis_service = RedisService()

async def init_redis() -> None:
    await redis_service.ping()

def validate_settings(settings: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate user settings against constraints.

    Args:
        settings: User settings dictionary

    Returns:
        Validated settings dictionary

    Raises:
        ValidationException: Settings validation failed
    """
    try:
        # 숫자 범위 검증
        for key, constraint in SETTINGS_CONSTRAINTS.items():
            if key in settings:
                val = settings[key]
                constraint_dict = constraint if isinstance(constraint, dict) else {}
                min_val = constraint_dict.get('min', float('-inf'))
                max_val = constraint_dict.get('max', float('inf'))
                if val < min_val or val > max_val:
                    raise ValidationException(
                        f"Setting '{key}' value ({val}) is out of range",
                        details={
                            "key": key,
                            "value": val,
                            "min": min_val,
                            "max": max_val
                        }
                    )

        # 문자열 옵션 검증
        if "direction" in settings and settings["direction"] not in DIRECTION_OPTIONS:
            raise ValidationException(
                f"Invalid direction option: {settings['direction']}",
                details={
                    "value": settings["direction"],
                    "valid_options": DIRECTION_OPTIONS
                }
            )

        if "entry_option" in settings and settings["entry_option"] not in ENTRY_OPTIONS:
            raise ValidationException(
                f"Invalid entry option: {settings['entry_option']}",
                details={
                    "value": settings["entry_option"],
                    "valid_options": ENTRY_OPTIONS
                }
            )

        if "tp_sl_option" in settings and settings["tp_sl_option"] not in TP_SL_OPTIONS:
            raise ValidationException(
                f"Invalid TP/SL option: {settings['tp_sl_option']}",
                details={
                    "value": settings["tp_sl_option"],
                    "valid_options": TP_SL_OPTIONS
                }
            )

        logger.debug(
            "Settings validation successful",
            extra={"settings_keys": list(settings.keys())}
        )

        return settings

    except ValidationException:
        raise
    except Exception as e:
        logger.error(
            "Settings validation failed",
            exc_info=True,
            extra={"settings": settings}
        )
        raise ValidationException(
            f"Settings validation error: {str(e)}",
            details={"error": str(e)}
        )

async def update_user_settings(user_id: str, new_settings: Dict[str, Any]) -> Dict[str, Any]:
    existing_settings = await redis_service.get_user_settings(str(user_id))
    if existing_settings is None:
        existing_settings = DEFAULT_PARAMS_SETTINGS.copy()
    merged_settings = {**existing_settings, **new_settings}
    validated_settings = validate_settings(merged_settings)
    await redis_service.set_user_settings(str(user_id), validated_settings)
    return validated_settings

class ApiKeyService:
    @staticmethod
    async def get_user_api_keys(user_id: str) -> Dict[str, str]:
        """
        사용자 ID를 기반으로 Redis에서 OKX API 키를 가져오는 함수

        API 키가 암호화되어 있으면 자동으로 복호화합니다.
        Backward compatibility: 평문 키도 읽을 수 있습니다.

        Args:
            user_id (str): 사용자 ID

        Returns:
            dict: API 키 정보 (api_key, api_secret, passphrase) - 복호화됨

        Raises:
            HTTPException: API 키를 찾을 수 없거나 오류 발생 시
        """
        try:
            async with redis_context(timeout=DEFAULT_REDIS_TIMEOUT) as redis:
                api_key_format = f"user:{user_id}:api:keys"
                api_keys_result = await redis.hgetall(api_key_format)

                if not api_keys_result:
                    raise HTTPException(status_code=404, detail="API keys not found in Redis")

                # Convert to Dict[str, str]
                encrypted_keys: Dict[str, str] = {k: str(v) for k, v in api_keys_result.items()}

                # Decrypt API keys (backward compatible - handles plaintext too)
                decrypted_keys: Dict[str, str] = {}
                for key_name, encrypted_value in encrypted_keys.items():
                    try:
                        # decrypt_api_key handles both encrypted and plaintext keys
                        decrypted_keys[key_name] = decrypt_api_key(encrypted_value)
                    except EncryptionError as e:
                        logger.error(
                            f"Failed to decrypt {key_name} for user {user_id}: {e}",
                            extra={"user_id": user_id, "key_name": key_name}
                        )
                        # Return encrypted value as fallback (for debugging)
                        decrypted_keys[key_name] = encrypted_value

                return decrypted_keys

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"API 키 조회 실패: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Error fetching API keys: {str(e)}")

    @staticmethod
    async def set_user_api_keys(user_id: str, api_key: str, api_secret: str, passphrase: str) -> bool:
        """
        사용자 API 키 정보를 암호화하여 TimescaleDB (primary)와 Redis (cache)에 저장

        저장 순서:
        1. TimescaleDB (영구 저장소) - 암호화 저장
        2. Redis (캐시 레이어) - 암호화 저장

        Args:
            user_id (str): 사용자 ID (OKX UID 또는 Telegram ID)
            api_key (str): API 키 (평문)
            api_secret (str): API 시크릿 (평문)
            passphrase (str): API 패스프레이즈 (평문)

        Returns:
            bool: 성공 여부
        """
        from HYPERRSI.src.services.timescale_service import TimescaleUserService

        try:
            # Encrypt API keys before storing
            encrypted_data = {
                'api_key': encrypt_api_key(api_key),
                'api_secret': encrypt_api_key(api_secret),
                'passphrase': encrypt_api_key(passphrase)
            }

            # 1️⃣ TimescaleDB 저장 (Primary Storage)
            try:
                result = await TimescaleUserService.upsert_api_credentials(
                    identifier=user_id,
                    api_key=encrypted_data['api_key'],
                    api_secret=encrypted_data['api_secret'],
                    passphrase=encrypted_data['passphrase']
                )
                if result:
                    logger.info(
                        f"API 키 TimescaleDB 저장 성공: {user_id}",
                        extra={"user_id": user_id}
                    )
            except Exception as ts_error:
                logger.error(
                    f"TimescaleDB API 키 저장 실패: {ts_error}",
                    extra={"user_id": user_id}
                )
                # TimescaleDB 실패해도 Redis 저장은 시도

            # 2️⃣ Redis 저장 (Cache Layer)
            async with redis_context(timeout=DEFAULT_REDIS_TIMEOUT) as redis:
                api_key_format = f"user:{user_id}:api:keys"

                # Store encrypted keys (no TTL - permanent storage)
                await redis.hmset(api_key_format, encrypted_data)

                logger.info(
                    f"API 키 Redis 캐싱 성공: {user_id}",
                    extra={"user_id": user_id}
                )
                return True

        except EncryptionError as e:
            logger.error(
                f"API 키 암호화 실패: {str(e)}",
                extra={"user_id": user_id}
            )
            return False
        except Exception as e:
            logger.error(
                f"API 키 저장 실패: {str(e)}",
                extra={"user_id": user_id}
            )
            return False