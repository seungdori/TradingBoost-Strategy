# src/core/database.py
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from contextlib import asynccontextmanager
from typing import List, Optional, Any, Dict, AsyncGenerator
from .database_dir.base import Base
import json
import redis.asyncio as redis
from celery import Celery
import logging
from threading import Lock
import time
from prometheus_client import Counter, Histogram
from pydantic_settings import BaseSettings
from shared.database import RedisConnectionManager
from shared.utils import retry_decorator

# 로거 설정
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
logger.addHandler(handler)
from HYPERRSI.src.core.config import settings  # <-- 공통 설정 import

class Settings(BaseSettings):
    # Redis 설정
    REDIS_URL: str = settings.REDIS_URL
    REDIS_PASSWORD: str | None = settings.REDIS_PASSWORD
    REDIS_HOST: str = settings.REDIS_HOST
    REDIS_PORT: int = settings.REDIS_PORT
    REDIS_POOL_SIZE: int = 100
    REDIS_BINARY_POOL_SIZE: int = 50
    CACHE_TTL: int = 3600
    LOCAL_CACHE_TTL: int = 300

    # OKX API 설정
    okx_api_key: str
    okx_secret_key: str
    okx_passphrase: str

    # Telegram 설정
    telegram_bot_token: str

    # 데이터베이스 설정
    database_url: str
    db_user: str
    db_password: str
    db_host: str
    db_port: str
    db_name: str

    # 기타 설정
    owner_id: str

    model_config = {
        "env_file": ".env",
        "case_sensitive": False,
        "extra": "allow"
    }

settings = Settings()

DATABASE_URL = "sqlite+aiosqlite:///./local_db.sqlite"

class DatabaseEngine:
    _instance = None
    _engine = None
    _lock = Lock()
    
    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._engine = create_async_engine(
                    DATABASE_URL,
                    echo=False,
                    future=True
                )
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

AsyncSessionLocal = sessionmaker(
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
    """데이터베이스 테이블 생성"""
    try:
        async with engine.begin() as conn:
            inspector = await conn.run_sync(lambda sync_conn: inspect(sync_conn))
            existing_tables = await conn.run_sync(lambda sync_conn: inspector.get_table_names())
            
            await conn.run_sync(Base.metadata.create_all)
            
            created_tables = set(await conn.run_sync(lambda sync_conn: inspector.get_table_names())) - set(existing_tables)
            if created_tables:
                logger.info(f"Created new tables: {', '.join(created_tables)}")
            else:
                logger.info("All tables already exist, no new tables created.")
                
        logger.info("Database initialization completed successfully.")
    except Exception as e:
        logger.error(f"Database initialization failed: {str(e)}")
        raise

async def close_db():
    """데이터베이스 연결 종료"""
    await db_engine.dispose()
    logger.info("Database connection closed.")

class RedisClient:
    """shared RedisConnectionManager를 사용하는 래퍼 클래스 (하위 호환성)"""
    _instance = None
    _manager = None
    _lock = Lock()

    def __new__(cls):
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

    async def get_client(self):
        """decode_responses=True 클라이언트 반환"""
        return await self._manager.get_connection_async(decode_responses=True)

    async def get_binary_client(self):
        """decode_responses=False 클라이언트 반환 (바이너리)"""
        return await self._manager.get_connection_async(decode_responses=False)

    async def ping(self):
        """Redis 서버 연결 상태 확인"""
        try:
            return await self._manager.ping()
        except Exception as e:
            logger.error(f"Redis 핑 확인 중 오류 발생: {str(e)}")
            await self.reconnect()
            return False

    async def reconnect(self, force=False):
        """Redis 연결 재시도"""
        try:
            await self._manager.reconnect()
            logger.info("Redis 재연결 완료")
        except Exception as e:
            logger.error(f"Redis 재연결 실패: {str(e)}")

    async def close(self):
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

# 비동기 함수로 클라이언트 가져오기
async def get_redis_client():
    """Redis 클라이언트 반환 (decode_responses=True)"""
    return await redis_instance.get_client()

async def get_redis_binary_client():
    """Redis 바이너리 클라이언트 반환 (decode_responses=False)"""
    return await redis_instance.get_binary_client()

# 하위 호환성을 위한 동기 wrapper (사용 시 주의 필요)
redis_client = redis_instance.get_client
redis_client_binary = redis_instance.get_binary_client

# 핑 메소드를 공용으로 사용하기 위해 연결 상태 확인 함수 추가
async def check_redis_connection():
    """Redis 연결 상태 확인"""
    return await redis_instance.ping()

# Redis 재연결 함수 추가
async def reconnect_redis():
    """Redis 강제 재연결"""
    return await redis_instance.reconnect(force=True)

# 동기 세션을 위한 의존성 함수 추가
def get_db():
    """FastAPI 의존성 주입을 위한 데이터베이스 세션 함수"""
    return redis_client

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
    _instance = None
    _cache = None
    _lock = Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._cache = Cache()
            return cls._instance

    async def bulk_get_positions(self, user_ids: List[str], symbol: str) -> Dict[str, Dict]:
        keys = [f"position:{user_id}:{symbol}" for user_id in user_ids]
        pipeline = self._cache._redis.pipeline()
        for key in keys:
            pipeline.get(key)
        
        results = await pipeline.execute()
        return {
            user_id: json.loads(result) if result else None
            for user_id, result in zip(user_ids, results)
        }

    async def set_position(self, user_id: str, symbol: str, data: Dict) -> bool:
        key = f"position:{user_id}:{symbol}"
        return await self._cache.set(key, data, expire=300)

    async def get_position(self, user_id: str, symbol: str) -> Optional[Dict]:
        key = f"position:{user_id}:{symbol}"
        return await self._cache.get(key)

    async def set_order(self, order_id: str, data: Dict) -> bool:
        key = f"order:{order_id}"
        return await self._cache.set(key, data, expire=3600)

    async def get_order(self, order_id: str) -> Optional[Dict]:
        key = f"order:{order_id}"
        return await self._cache.get(key)

    async def cleanup(self):
        """트레이딩 캐시 리소스 정리"""
        if self._cache:
            await self._cache.cleanup()
    @classmethod
    async def remove_position(cls, user_id: str, symbol: str, side: str) -> bool:
        """포지션 정보 삭제"""
        key = f"user:{user_id}:position:{symbol}:{side}"
        try:
            if not hasattr(cls, '_cache'):
                cls._cache = Cache()
            return await cls._cache.delete(key)
        except Exception as e:
            logger.error(f"Failed to remove position from cache: {str(e)}")
            return False
trading_cache = TradingCache()