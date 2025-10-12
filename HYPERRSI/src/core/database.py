# src/core/database.py
"""
HYPERRSI Database Module - Migrated to New Infrastructure

Database configuration and connection management with structured logging
and exception handling.
"""

import json
import time
from contextlib import asynccontextmanager
from threading import Lock
from typing import Any, AsyncGenerator, Dict, List, Optional, cast

import redis.asyncio as redis
from celery import Celery
from prometheus_client import Counter, Histogram
from pydantic_settings import BaseSettings
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker

from HYPERRSI.src.core.config import settings  # <-- 공통 설정 import
from shared.database import RedisConnectionManager
from shared.errors import ConfigurationException, DatabaseException
from shared.logging import get_logger
from shared.utils import retry_decorator

from .database_dir.base import Base

# 구조화된 로깅 사용
logger = get_logger(__name__)

# Database URL configuration - Use PostgreSQL from shared config
# DATABASE_URL is constructed from environment variables via shared.config
from shared.config import get_settings

_settings = get_settings()
DATABASE_URL = _settings.db_url  # PostgreSQL from shared configuration

class DatabaseEngine:
    _instance = None
    _engine = None
    _lock = Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                # PostgreSQL connection pool settings
                engine_kwargs: Dict[str, Any] = {
                    "echo": False,
                    "future": True,
                }

                # Add pool settings for PostgreSQL
                if "postgresql" in DATABASE_URL:
                    engine_kwargs.update({
                        "pool_size": _settings.DB_POOL_SIZE,
                        "max_overflow": _settings.DB_MAX_OVERFLOW,
                        "pool_recycle": _settings.DB_POOL_RECYCLE,
                        "pool_pre_ping": _settings.DB_POOL_PRE_PING,
                        "pool_timeout": _settings.DB_POOL_TIMEOUT,
                    })

                cls._engine = create_async_engine(DATABASE_URL, **engine_kwargs)
            return cls._instance
    
    @property
    def engine(self):
        return self._engine
        
    async def dispose(self):
        if self._engine:
            await self._engine.dispose()
            self._engine = None

db_engine = DatabaseEngine()
engine = db_engine.engine

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)

@asynccontextmanager
async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """비동기 데이터베이스 세션 컨텍스트 매니저"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception as e:
            await session.rollback()
            raise
        finally:
            await session.close()

async def init_db():
    """
    Initialize database tables.

    Creates all tables defined in Base metadata if they don't exist.

    Raises:
        DatabaseException: Database initialization failed
    """
    try:
        logger.info("Initializing database...")

        async with engine.begin() as conn:
            inspector = await conn.run_sync(lambda sync_conn: inspect(sync_conn))
            existing_tables = await conn.run_sync(lambda sync_conn: inspector.get_table_names())

            await conn.run_sync(Base.metadata.create_all)

            created_tables = set(await conn.run_sync(lambda sync_conn: inspector.get_table_names())) - set(existing_tables)

            if created_tables:
                logger.info(
                    "Database tables created",
                    extra={"created_tables": list(created_tables)}
                )
            else:
                logger.info("All database tables already exist")

        logger.info("Database initialization completed successfully")

    except Exception as e:
        logger.error(
            "Database initialization failed",
            exc_info=True
        )
        raise DatabaseException(
            "Failed to initialize database",
            details={"error": str(e)}
        )

async def close_db():
    """
    Close database connection.

    Disposes database engine and all connections.
    """
    try:
        logger.info("Closing database connection...")
        await db_engine.dispose()
        logger.info("Database connection closed successfully")
    except Exception as e:
        logger.error(
            "Error closing database connection",
            exc_info=True
        )
        # Don't raise here - allow shutdown to continue

class RedisClient:
    """shared RedisConnectionManager를 사용하는 래퍼 클래스 (하위 호환성)"""
    _instance: Optional["RedisClient"] = None
    _manager: RedisConnectionManager
    _lock = Lock()

    def __new__(cls) -> "RedisClient":
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._manager = RedisConnectionManager(
                    host=settings.REDIS_HOST,
                    port=settings.REDIS_PORT,
                    db=0,
                    password=settings.REDIS_PASSWORD if settings.REDIS_PASSWORD else None,
                    max_connections=200
                )
                logger.info(f"RedisClient 초기화 완료 (shared.database.RedisConnectionManager 사용)")
            return cls._instance

    async def get_client(self) -> redis.Redis:
        """decode_responses=True 클라이언트 반환"""
        return await self._manager.get_connection_async(decode_responses=True)

    async def get_binary_client(self) -> redis.Redis:
        """decode_responses=False 클라이언트 반환 (바이너리)"""
        return await self._manager.get_connection_async(decode_responses=False)

    async def ping(self) -> bool:
        """Redis 서버 연결 상태 확인"""
        try:
            return await self._manager.ping()
        except Exception as e:
            logger.error(f"Redis 핑 확인 중 오류 발생: {str(e)}")
            await self.reconnect()
            return False

    async def reconnect(self, force: bool = False) -> None:
        """Redis 연결 재시도"""
        try:
            await self._manager.reconnect()
            logger.info("Redis 재연결 완료")
        except Exception as e:
            logger.error(f"Redis 재연결 실패: {str(e)}")

    async def close(self) -> None:
        """클라이언트 연결 종료"""
        try:
            await self._manager.close()
            logger.info("Redis 연결이 성공적으로 종료되었습니다.")
        except Exception as e:
            logger.error(f"Redis 연결 종료 중 오류 발생: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())

# 기존 클라이언트 인스턴스 생성
redis_instance = RedisClient()

# 전역 Redis 클라이언트 캐시 (싱글톤 패턴)
_global_redis_client = None
_global_redis_binary_client = None
_redis_init_lock = None  # asyncio.Lock은 런타임에 생성

def _get_redis_init_lock():
    """Lazy initialization of async lock"""
    global _redis_init_lock
    if _redis_init_lock is None:
        import asyncio
        _redis_init_lock = asyncio.Lock()
    return _redis_init_lock

async def get_redis_client():
    """Redis 클라이언트 반환 (decode_responses=True) - 싱글톤 (async-safe)"""
    global _global_redis_client
    if _global_redis_client is None:
        async with _get_redis_init_lock():  # Async lock으로 보호
            # Double-check locking pattern
            if _global_redis_client is None:
                _global_redis_client = await redis_instance.get_client()
                logger.debug("Global Redis client (decoded) initialized")
    return _global_redis_client

async def get_redis_binary_client():
    """Redis 바이너리 클라이언트 반환 (decode_responses=False) - 싱글톤 (async-safe)"""
    global _global_redis_binary_client
    if _global_redis_binary_client is None:
        async with _get_redis_init_lock():  # Async lock으로 보호
            # Double-check locking pattern
            if _global_redis_binary_client is None:
                _global_redis_binary_client = await redis_instance.get_binary_client()
                logger.debug("Global Redis client (binary) initialized")
    return _global_redis_binary_client

async def init_global_redis_clients():
    """
    전역 Redis 클라이언트를 초기화합니다.
    애플리케이션 시작 시 lifespan에서 호출해야 합니다.
    """
    global _global_redis_client, _global_redis_binary_client
    _global_redis_client = await redis_instance.get_client()
    _global_redis_binary_client = await redis_instance.get_binary_client()

    logger.info("Global Redis clients initialized successfully")

    # Return clients for assignment
    return _global_redis_client, _global_redis_binary_client

# Module-level attribute access for dynamic redis_client
def __getattr__(name):
    """
    Module-level __getattr__ for dynamic redis_client access.
    Allows legacy code to use 'redis_client' after initialization.
    """
    if name == 'redis_client':
        if _global_redis_client is None:
            raise RuntimeError(
                "Redis client not initialized. "
                "Call init_global_redis_clients() in application startup."
            )
        return _global_redis_client
    elif name == 'redis_client_binary':
        if _global_redis_binary_client is None:
            raise RuntimeError(
                "Redis binary client not initialized. "
                "Call init_global_redis_clients() in application startup."
            )
        return _global_redis_binary_client
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")

# 핑 메소드를 공용으로 사용하기 위해 연결 상태 확인 함수 추가
async def check_redis_connection():
    """Redis 연결 상태 확인"""
    return await redis_instance.ping()

# Redis 재연결 함수 추가
async def reconnect_redis():
    """Redis 강제 재연결"""
    return await redis_instance.reconnect(force=True)

# FastAPI 의존성 주입을 위한 비동기 세션 함수
async def get_db():
    """FastAPI 의존성 주입을 위한 Redis 클라이언트 반환 함수"""
    return await get_redis_client()

class CeleryApp:
    _instance = None
    _app = None
    _lock = Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                REDIS_DB_BROKER = 1
                REDIS_DB_BACKEND = 2
                REDIS_PASSWORD = settings.REDIS_PASSWORD
                REDIS_HOST = settings.REDIS_HOST
                REDIS_PORT = settings.REDIS_PORT
                cls._instance = super().__new__(cls)
                if REDIS_PASSWORD:
                    cls._app = Celery(
                        "trading_tasks",
                        broker=f"redis://:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB_BROKER}",
                        backend=f"redis://:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB_BACKEND}"
                    )
                else:
                    cls._app = Celery(
                        "trading_tasks",
                        broker=f"redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB_BROKER}",
                        backend=f"redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB_BACKEND}"
                    )
            return cls._instance

    @property
    def app(self):
        return self._app

celery_app = CeleryApp().app

class Cache:
    # 메트릭 카운터
    cache_hits = Counter('cache_hits_total', 'Cache hit count')
    cache_misses = Counter('cache_misses_total', 'Cache miss count')
    cache_operation_duration = Histogram('cache_operation_seconds', 'Cache operation duration')

    # 싱글톤 변수
    _instance = None
    _lock = Lock()

    def __init__(self):
        self._redis_client = RedisClient()
        self._local_cache = {}
        self._cache_ttl = {}

    async def _get_redis(self):
        """Redis 클라이언트 가져오기"""
        return await self._redis_client.get_client()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
            return cls._instance

    @retry_decorator(max_retries=3, delay=4.0, backoff=2.0)
    async def set(self, key: str, value: Any, expire: int = 3600) -> bool:
        with self.cache_operation_duration.time():
            try:
                serialized = json.dumps(value) if not isinstance(value, str) else value
                # 로컬 캐시에도 저장
                self._local_cache[key] = value
                self._cache_ttl[key] = time.time() + expire
                redis = await self._get_redis()
                await redis.set(key, serialized, ex=expire)
                return True
            except Exception as e:
                logger.error(f"Cache set error: {e}")
                raise

    @retry_decorator(max_retries=3, delay=4.0, backoff=2.0)
    async def get(self, key: str) -> Optional[Any]:
        with self.cache_operation_duration.time():
            try:
                # 먼저 로컬 캐시 확인
                if key in self._local_cache:
                    if time.time() < self._cache_ttl[key]:
                        self.cache_hits.inc()
                        return self._local_cache[key]
                    else:
                        del self._local_cache[key]
                        del self._cache_ttl[key]

                # Redis에서 조회
                redis = await self._get_redis()
                data = await redis.get(key)
                if data:
                    try:
                        parsed_data = json.loads(data)
                        # 로컬 캐시 업데이트
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
        try:
            if key in self._local_cache:
                del self._local_cache[key]
                del self._cache_ttl[key]
            redis = await self._get_redis()
            await redis.delete(key)
            return True
        except Exception as e:
            logger.error(f"Cache delete error: {e}")
            return False

    async def cleanup(self):
        """캐시 리소스 정리"""
        self._local_cache.clear()
        self._cache_ttl.clear()
        
class TradingCache:
    """트레이딩 관련 캐시 관리"""
    _instance: Optional["TradingCache"] = None
    _cache: Cache
    _lock = Lock()

    def __new__(cls) -> "TradingCache":
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._cache = Cache()
            return cls._instance

    async def bulk_get_positions(self, user_ids: List[str], symbol: str) -> Dict[str, Optional[Dict[Any, Any]]]:
        """벌크 포지션 조회 - Redis 직접 접근 대신 Cache.get() 사용"""
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
        key = f"position:{user_id}:{symbol}"
        return await self._cache.set(key, data, expire=300)

    async def get_position(self, user_id: str, symbol: str) -> Optional[Dict[Any, Any]]:
        key = f"position:{user_id}:{symbol}"
        result = await self._cache.get(key)
        if result and isinstance(result, dict):
            return cast(Dict[Any, Any], result)
        return None

    async def set_order(self, order_id: str, data: Dict[Any, Any]) -> bool:
        key = f"order:{order_id}"
        return await self._cache.set(key, data, expire=3600)

    async def get_order(self, order_id: str) -> Optional[Dict[Any, Any]]:
        key = f"order:{order_id}"
        result = await self._cache.get(key)
        if result and isinstance(result, dict):
            return cast(Dict[Any, Any], result)
        return None

    async def cleanup(self) -> None:
        """트레이딩 캐시 리소스 정리"""
        await self._cache.cleanup()

    @classmethod
    async def remove_position(cls, user_id: str, symbol: str, side: str) -> bool:
        """포지션 정보 삭제"""
        key = f"user:{user_id}:position:{symbol}:{side}"
        try:
            if not hasattr(cls, '_cache') or cls._cache is None:
                cls._cache = Cache()
            return await cls._cache.delete(key)
        except Exception as e:
            logger.error(f"Failed to remove position from cache: {str(e)}")
            return False
trading_cache = TradingCache()