#src/services/redis_service.py
"""
Redis Service - Migrated to New Infrastructure

Manages user settings, API keys, and caching with structured logging
and exception handling.
"""

import json
import os
import time
from threading import Lock
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from prometheus_client import Counter, Histogram
from redis.asyncio import ConnectionPool, Redis

from HYPERRSI.src.core import database as _database_module
from shared.constants.default_settings import (
    DEFAULT_PARAMS_SETTINGS,
    DIRECTION_OPTIONS,
    ENTRY_OPTIONS,
    PYRAMIDING_TYPES,
    SETTINGS_CONSTRAINTS,
    TP_SL_OPTIONS,
)
from shared.database.redis_helper import get_redis_client
from shared.errors import ConfigurationException, DatabaseException, ValidationException
from shared.logging import get_logger
from shared.utils import retry_decorator

logger = get_logger(__name__)

# Dynamic redis_client access - returns current initialized client
def __getattr__(name):
    """
    Module-level __getattr__ for dynamic attribute access.
    Allows redis_client to be accessed after initialization.
    """
    if name == 'redis_client':
        # Return the current redis_client from database module
        # This ensures we always get the initialized client
        return _database_module.redis_client
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")

class RedisService:
    _instance = None
    _redis = None
    _lock = Lock()
    _pool = None
        # 모니터링 메트릭
    cache_hits = Counter('redis_hits_total', 'Redis hit count')
    cache_misses = Counter('redis_misses_total', 'Redis miss count')
    operation_duration = Histogram('redis_operation_seconds', 'Redis operation duration')
    
    
    def __new__(cls, *args, **kwargs):
        # 외부 redis 클라이언트가 제공된 경우 새 인스턴스 생성
        if 'external_redis' in kwargs and kwargs['external_redis'] is not None:
            return super().__new__(cls)
            
        with cls._lock:
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
            
        # 1) env에서 기본값 읽어오기
        if host is None:
            host = os.getenv('REDIS_HOST', 'localhost')
        if port is None:
            port = int(os.getenv('REDIS_PORT', '6379'))
        if db is None:
            db = int(os.getenv('REDIS_DB', '0'))

        if password is None:
            # env에서 읽었는데 없거나, 빈 값이면 None 처리
            env_pass = os.getenv('REDIS_PASSWORD', '')
            password = env_pass if env_pass else None

        logger.info(f"RedisService initializing: host={host}, port={port}, db={db}, password={'YES' if password else 'NO'}")
        
        try:    
            # 연결 풀 설정
            password = os.getenv('REDIS_PASSWORD', None)
            self._pool = ConnectionPool(
                host=host,
                port=port,
                db=db,
                decode_responses=True,
                password=password,
                max_connections=100,  # 동시 접속자 수에 맞게 조정
                health_check_interval=30
            )
            self._redis = Redis(connection_pool=self._pool)
            self._local_cache = {}  # 메모리 캐시 추가
            self._cache_ttl = {}
        except Exception as e:
            logger.error(f"Redis initialization failed: {e}")
            raise

    
    @property
    def redis(self):
        return self._redis

    async def ping(self) -> None:
        try:
            if self._redis is None:
                raise ConnectionError("Redis client not initialized")
            await self._redis.ping()
            logger.info("Redis connection established successfully")
        except ConnectionError as e:
            logger.error(f"Failed to connect to Redis: {str(e)}")
            raise
    async def close(self) -> None:
        if self._redis is not None:
            await self._redis.close()
            self._redis = None
    @property
    def is_connected(self) -> bool:
        if self._redis is None:
            return False
        try:
            # 비동기 컨텍스트 외부에서도 사용 가능하도록 수정
            # 실제 연결 상태는 ping() 메서드를 통해 확인해야 함
            return self._redis is not None and self._pool is not None
        except Exception as e:
            logger.error(f"Redis 연결 상태 확인 중 오류: {str(e)}")
            return False
    
    @retry_decorator(max_retries=3, delay=4.0, backoff=2.0)
    async def get_user_settings(self, user_id: str) -> Optional[Dict[str, Any]]:
        with self.operation_duration.time():
            try:
                if self._redis is None:
                    raise ConnectionError("Redis client not initialized")

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

                # Redis에서 조회
                settings = await self._redis.get(cache_key)
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
                    await self._redis.set(cache_key, json.dumps(user_settings))

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
                if self._redis is None:
                    raise ConnectionError("Redis client not initialized")

                cache_key = f"user:{user_id}:settings"
                # Redis 업데이트
                await self._redis.set(cache_key, json.dumps(settings))
                # 로컬 캐시 업데이트
                self._local_cache[cache_key] = settings
                self._cache_ttl[cache_key] = time.time() + 300
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
                if self._redis is None:
                    raise ConnectionError("Redis client not initialized")

                pipeline = self._redis.pipeline()
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
                if self._redis is None:
                    raise ConnectionError("Redis client not initialized")

                pipeline = self._redis.pipeline()
                for user_id, settings in settings_dict.items():
                    cache_key = f"user:{user_id}:settings"
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
                if self._redis is None:
                    raise ConnectionError("Redis client not initialized")

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
                    pipeline = self._redis.pipeline()
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
                if self._redis is None:
                    raise ConnectionError("Redis client not initialized")

                pipeline = self._redis.pipeline()
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
        """리소스 정리"""
        if self._redis is not None:
            await self._redis.close()
            self._redis = None
        self._local_cache.clear()
        self._cache_ttl.clear()
        if self._pool is not None:
            await self._pool.disconnect()
            self._pool = None



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

        if "pyramiding_type" in settings and settings["pyramiding_type"] not in PYRAMIDING_TYPES:
            raise ValidationException(
                f"Invalid pyramiding type: {settings['pyramiding_type']}",
                details={
                    "value": settings["pyramiding_type"],
                    "valid_options": PYRAMIDING_TYPES
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

        Args:
            user_id (str): 사용자 ID

        Returns:
            dict: API 키 정보 (api_key, api_secret, passphrase)

        Raises:
            HTTPException: API 키를 찾을 수 없거나 오류 발생 시
        """
        try:
            redis = await get_redis_client()
            api_key_format = f"user:{user_id}:api:keys"
            api_keys_result = await redis.hgetall(api_key_format)

            if not api_keys_result:
                raise HTTPException(status_code=404, detail="API keys not found in Redis")

            # Ensure we return a proper Dict[str, str]
            api_keys: Dict[str, str] = {k: str(v) for k, v in api_keys_result.items()}
            return api_keys
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"2API 키 조회 실패: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Error fetching API keys: {str(e)}")

    @staticmethod
    async def set_user_api_keys(user_id: str, api_key: str, api_secret: str, passphrase: str) -> bool:
        """
        사용자 API 키 정보를 Redis에 저장

        Args:
            user_id (str): 사용자 ID
            api_key (str): API 키
            api_secret (str): API 시크릿
            passphrase (str): API 패스프레이즈

        Returns:
            bool: 성공 여부
        """
        try:
            redis = await get_redis_client()
            api_key_format = f"user:{user_id}:api:keys"
            await redis.hmset(api_key_format, {
                'api_key': api_key,
                'api_secret': api_secret,
                'passphrase': passphrase
            })
            logger.info(f"API 키 저장 성공: {user_id}")
            return True
        except Exception as e:
            logger.error(f"API 키 저장 실패: {str(e)}")
            return False