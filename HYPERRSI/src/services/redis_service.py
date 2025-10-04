#src/services/redis_service.py

from redis.asyncio import Redis, ConnectionPool
import json
import logging
from threading import Lock
from typing import Optional, Dict, Any
from tenacity import retry, stop_after_attempt, wait_exponential
from prometheus_client import Counter, Histogram
from shared.constants.default_settings import (
    DEFAULT_PARAMS_SETTINGS,
    SETTINGS_CONSTRAINTS,
    ENTRY_OPTIONS,
    TP_SL_OPTIONS,
    DIRECTION_OPTIONS,
    PYRAMIDING_TYPES,
)
import time
import os
from fastapi import HTTPException
from HYPERRSI.src.core.database import redis_client

logger = logging.getLogger(__name__)

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
            self._local_cache = {}  # 메모리 캐시 추가
            self._cache_ttl = {}
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

    async def ping(self):
        try:
            await self._redis.ping()
            logger.info("Redis connection established successfully")
        except ConnectionError as e:
            logger.error(f"Failed to connect to Redis: {str(e)}")
            raise
    async def close(self):
        if self._redis is not None:
            await self._redis.close()
            self._redis = None
    @property
    def is_connected(self):
        if self._redis is None:
            return False
        try:
            # 비동기 컨텍스트 외부에서도 사용 가능하도록 수정
            # 실제 연결 상태는 ping() 메서드를 통해 확인해야 함
            return self._redis is not None and self._pool is not None
        except Exception as e:
            logger.error(f"Redis 연결 상태 확인 중 오류: {str(e)}")
            return False
    
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
    async def get_user_settings(self, user_id: str) -> Optional[Dict]:
        with self.operation_duration.time():
            try:
                # 먼저 로컬 캐시 확인
                cache_key = f"user:{user_id}:settings"
                if cache_key in self._local_cache:
                    if time.time() < self._cache_ttl.get(cache_key, 0):
                        self.cache_hits.inc()
                        return self._local_cache[cache_key]
                    else:
                        del self._local_cache[cache_key]
                        del self._cache_ttl[cache_key]

                # Redis에서 조회
                settings = await self._redis.get(cache_key)
                if not settings:
                    self.cache_misses.inc()
                    return None

                user_settings = json.loads(settings)
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


    async def set_user_settings(self, user_id: str, settings: dict):
        with self.operation_duration.time():
            try:
                cache_key = f"user:{user_id}:settings"
                # Redis 업데이트
                await self._redis.set(cache_key, json.dumps(settings))
                # 로컬 캐시 업데이트
                self._local_cache[cache_key] = settings
                self._cache_ttl[cache_key] = time.time() + 300
            except Exception as e:
                logger.error(f"Error setting user settings: {e}")
                raise
    async def get_multiple_user_settings(self, user_ids: list) -> Dict[str, Dict]:
        """여러 사용자의 설정을 한 번에 조회"""
        pipeline = self._redis.pipeline()
        for user_id in user_ids:
            pipeline.get(f"user:{user_id}:settings")
        
        results = await pipeline.execute()
        return {
            user_id: json.loads(result) if result else None
            for user_id, result in zip(user_ids, results)
        }

    async def cleanup(self):
        """리소스 정리"""
        if self._redis is not None:
            await self._redis.close()
            self._redis = None
        self._local_cache.clear()
        self._cache_ttl.clear()
        if self._pool is not None:
            self._pool.disconnect()
            self._pool = None



redis_service = RedisService()

async def init_redis():
    await redis_service.ping()

def validate_settings(settings: dict) -> dict:
    # 숫자 범위 검증
    for key, constraint in SETTINGS_CONSTRAINTS.items():
        if key in settings:
            val = settings[key]
            if val < constraint['min'] or val > constraint['max']:
                raise ValueError(
                    f"'{key}' 설정값({val})이 범위를 벗어났습니다. "
                    f"({constraint['min']} ~ {constraint['max']}) 사이여야 함."
                )
    
    # 문자열 옵션 검증
    if "direction" in settings and settings["direction"] not in DIRECTION_OPTIONS:
        raise ValueError(f"direction 옵션이 유효하지 않습니다: {settings['direction']}")
    
    if "entry_option" in settings and settings["entry_option"] not in ENTRY_OPTIONS:
        raise ValueError(f"entry_option 옵션이 유효하지 않습니다: {settings['entry_option']}")
    
    if "tp_sl_option" in settings and settings["tp_sl_option"] not in TP_SL_OPTIONS:
        raise ValueError(f"tp_sl_option 옵션이 유효하지 않습니다: {settings['tp_sl_option']}")
    
    if "pyramiding_type" in settings and settings["pyramiding_type"] not in PYRAMIDING_TYPES:
        raise ValueError(f"pyramiding_type 옵션이 유효하지 않습니다: {settings['pyramiding_type']}")
    
    return settings

async def update_user_settings(user_id: str, new_settings: dict) -> dict:
    existing_settings = await redis_service.get_user_settings(str(user_id))
    if existing_settings is None:
        existing_settings = DEFAULT_PARAMS_SETTINGS.copy()
    merged_settings = {**existing_settings, **new_settings}
    validated_settings = validate_settings(merged_settings)
    await redis_service.set_user_settings(str(user_id), validated_settings)
    return validated_settings

async def set_user_state(user_id: str, state: str) -> None:
    await redis_service.set_user_state(str(user_id), state)

class ApiKeyService:
    @staticmethod
    async def get_user_api_keys(user_id: str) -> dict:
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
            api_key_format = f"user:{user_id}:api:keys"
            api_keys = await redis_client.hgetall(api_key_format)
            
            if not api_keys:
                raise HTTPException(status_code=404, detail="API keys not found in Redis")
                
            return api_keys
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
            api_key_format = f"user:{user_id}:api:keys"
            await redis_client.hmset(api_key_format, {
                'api_key': api_key,
                'api_secret': api_secret,
                'passphrase': passphrase
            })
            logger.info(f"API 키 저장 성공: {user_id}")
            return True
        except Exception as e:
            logger.error(f"API 키 저장 실패: {str(e)}")
            return False