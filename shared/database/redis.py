"""
Redis Connection Management with Connection Pooling

Provides optimized Redis connection management with:
- Connection pooling for performance
- Automatic reconnection on failure
- Type-safe operations
- Backward compatibility with legacy RedisConnectionManager
"""

import asyncio
import logging
import os
import time
import warnings
from threading import Lock
from typing import Any

from logging import LogRecord

import redis.asyncio as aioredis
from redis import Redis, RedisError
from redis.asyncio import ConnectionPool
from redis.asyncio import Redis as AsyncRedis

from shared.config import settings
from shared.database.pool_monitor import RedisPoolMonitor
from shared.errors import RedisException

logger = logging.getLogger(__name__)

# c-ares DNS resolver 경고 억제
os.environ.setdefault('GRPC_DNS_RESOLVER', 'native')
os.environ.setdefault('GRPC_ENABLE_FORK_SUPPORT', '1')
os.environ.setdefault('GRPC_VERBOSITY', 'ERROR')
os.environ.setdefault('GRPC_TRACE', '')

# Python warnings 필터
warnings.filterwarnings('ignore', message='.*c-ares.*')
warnings.filterwarnings('ignore', message='.*DNS resolver.*')

# 특정 gRPC 경고 로그 필터링


class _GrpcDnsWarningFilter(logging.Filter):
    """Suppress known noisy gRPC DNS resolver warnings."""

    _SUBSTRINGS = (
        'Failed to create DNS resolver channel with automatic monitoring of resolver configuration changes.',
        'Failed to initialize c-ares channel',
    )

    def filter(self, record: LogRecord) -> bool:  # pragma: no cover - logging side effect
        if not record.name.startswith('grpc'):
            return True

        message = record.getMessage()
        return not any(substring in message for substring in self._SUBSTRINGS)


_grpc_dns_warning_filter = _GrpcDnsWarningFilter()


def _suppress_grpc_dns_warning_logs() -> None:
    target_logger_names = ('', 'grpc', 'grpc._cython', 'grpc._cython.cygrpc', 'grpc.aio')
    for logger_name in target_logger_names:
        logging.getLogger(logger_name).addFilter(_grpc_dns_warning_filter)


_suppress_grpc_dns_warning_logs()

# gRPC 관련 로거 레벨 조정
for grpc_logger_name in ['grpc', 'grpc._cython', 'grpc.aio']:
    grpc_logger = logging.getLogger(grpc_logger_name)
    grpc_logger.setLevel(logging.ERROR)
    grpc_logger.propagate = False


class RedisConnectionManager:
    """Redis 연결 관리 싱글톤 클래스
    
    특징:
    - 싱글톤 패턴: 애플리케이션 전체에서 하나의 인스턴스만 존재
    - 연결 풀 관리: 동기/비동기 연결 풀 자동 관리
    - 자동 재연결: 연결 실패 시 백오프 로직으로 재연결
    - 멀티 클라이언트: decode_responses=True/False 모두 지원
    """
    
    _instance: "RedisConnectionManager | None" = None
    _lock = Lock()
    _initialized: bool = False
    
    # 연결 풀들
    _sync_pool: Redis | None = None
    _async_pool: ConnectionPool | None = None
    _async_binary_pool: ConnectionPool | None = None

    # 클라이언트들
    _sync_client: Redis | None = None
    _async_client: AsyncRedis | None = None
    _async_binary_client: AsyncRedis | None = None
    
    # 재연결 관리
    _last_connect_attempt: float = 0
    _connect_backoff: float = 1
    _max_backoff: float = 30
    
    def __new__(cls, host: str = "localhost", port: int = 6379, db: int = 0,
                password: str | None = None, max_connections: int = 200) -> "RedisConnectionManager":
        """싱글톤 인스턴스 생성"""
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance
    
    def __init__(self, host: str = "localhost", port: int = 6379, db: int = 0,
                 password: str | None = None, max_connections: int = 200) -> None:
        """
        Redis 연결 관리자 초기화
        
        Args:
            host: Redis 서버 호스트
            port: Redis 서버 포트
            db: Redis 데이터베이스 번호
            password: Redis 비밀번호 (선택)
            max_connections: 최대 연결 수
        """
        if self._initialized:
            return
            
        self.redis_host = host
        self.redis_port = port
        self.redis_db = db
        self.redis_password = password
        self.max_connections = max_connections
        
        self._initialized = True
        logger.info(f"RedisConnectionManager initialized: {host}:{port}/{db}")
    
    # ==================== 동기 연결 ====================
    
    def get_connection(self) -> Redis:
        """
        동기 Redis 연결 반환 (decode_responses=False)
        
        Returns:
            Redis: 동기 Redis 클라이언트
        """
        if self._sync_client is None:
            self._sync_client = Redis(
                host=self.redis_host,
                port=self.redis_port,
                db=self.redis_db,
                password=self.redis_password,
                decode_responses=False,
                max_connections=self.max_connections,
                socket_keepalive=True,
                socket_connect_timeout=5,
                retry_on_timeout=True
            )
            logger.info("동기 Redis 클라이언트 생성 완료")
        return self._sync_client
    
    # ==================== 비동기 연결 ====================
    
    async def get_connection_async(self, decode_responses: bool = False) -> AsyncRedis:
        """
        비동기 Redis 연결 반환
        
        Args:
            decode_responses: 응답을 str로 디코딩할지 여부 (기본: False, bytes 반환)
            
        Returns:
            AsyncRedis: 비동기 Redis 클라이언트
        """
        if decode_responses:
            # decode_responses=True 클라이언트
            if self._async_client is None:
                self._async_pool = await self._create_async_pool(decode_responses=True)
                self._async_client = AsyncRedis(connection_pool=self._async_pool)
                logger.info("비동기 Redis 클라이언트 (decoded) 생성 완료")
            return self._async_client
        else:
            # decode_responses=False 클라이언트 (바이너리)
            if self._async_binary_client is None:
                self._async_binary_pool = await self._create_async_pool(decode_responses=False)
                self._async_binary_client = AsyncRedis(connection_pool=self._async_binary_pool)
                logger.info("비동기 Redis 클라이언트 (binary) 생성 완료")
            return self._async_binary_client
    
    async def _create_async_pool(self, decode_responses: bool) -> ConnectionPool:
        """비동기 연결 풀 생성"""
        redis_url = f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"

        pool: ConnectionPool = aioredis.ConnectionPool.from_url(
            redis_url,
            max_connections=self.max_connections if decode_responses else 100,
            decode_responses=decode_responses,
            password=self.redis_password,
            retry_on_timeout=True,
            socket_connect_timeout=5,
            socket_keepalive=True,
            health_check_interval=15
        )
        return pool
    
    # ==================== 헬스 체크 ====================
    
    async def ping(self) -> bool:
        """
        Redis 서버 연결 상태 확인
        
        Returns:
            bool: 연결 성공 여부
        """
        try:
            client = await self.get_connection_async(decode_responses=True)
            result = await client.ping()
            if not result:
                logger.warning("Redis 핑 응답이 없습니다. 연결 재시도가 필요할 수 있습니다.")
                return False
            return True
        except Exception as e:
            logger.error(f"Redis 핑 실패: {str(e)}")
            return False
    
    def ping_sync(self) -> bool:
        """
        동기 Redis 서버 연결 상태 확인

        Returns:
            bool: 연결 성공 여부
        """
        try:
            client = self.get_connection()
            return bool(client.ping())
        except Exception as e:
            logger.error(f"동기 Redis 핑 실패: {str(e)}")
            return False
    
    # ==================== 재연결 로직 ====================
    
    async def reconnect(self):
        """Redis 재연결 (백오프 로직 포함)"""
        current_time = time.time()
        
        # 백오프 시간이 지나지 않았으면 대기
        if current_time - self._last_connect_attempt < self._connect_backoff:
            logger.debug(f"재연결 백오프 대기 중: {self._connect_backoff}초")
            return
        
        try:
            logger.info("Redis 재연결 시도 중...")
            
            # 기존 연결 종료
            await self.close()
            
            # 새로운 연결 생성
            self._async_pool = await self._create_async_pool(decode_responses=True)
            self._async_binary_pool = await self._create_async_pool(decode_responses=False)
            
            self._async_client = AsyncRedis(connection_pool=self._async_pool)
            self._async_binary_client = AsyncRedis(connection_pool=self._async_binary_pool)
            
            # 연결 테스트
            if await self.ping():
                logger.info("Redis 재연결 성공")
                self._connect_backoff = 1  # 백오프 리셋
            else:
                raise Exception("재연결 후 핑 실패")
                
        except Exception as e:
            logger.error(f"Redis 재연결 실패: {str(e)}")
            # 백오프 증가
            self._connect_backoff = min(self._connect_backoff * 2, self._max_backoff)
            self._last_connect_attempt = current_time
    
    # ==================== 연결 종료 ====================
    
    async def close(self):
        """모든 Redis 연결 종료"""
        try:
            if self._async_pool:
                await self._async_pool.disconnect()
                self._async_pool = None
            
            if self._async_binary_pool:
                await self._async_binary_pool.disconnect()
                self._async_binary_pool = None
            
            if self._sync_client:
                self._sync_client.close()
                self._sync_client = None
            
            self._async_client = None
            self._async_binary_client = None
            
            logger.info("모든 Redis 연결이 종료되었습니다.")
        except Exception as e:
            logger.error(f"Redis 연결 종료 중 오류: {str(e)}")
    
    def close_sync(self):
        """동기 Redis 연결만 종료"""
        if self._sync_client:
            self._sync_client.close()
            self._sync_client = None
            logger.info("동기 Redis 연결이 종료되었습니다.")


# ==================== 편의 함수 ====================

async def get_redis_connection(decode_responses: bool = False) -> AsyncRedis:
    """
    전역 Redis 연결 반환 (편의 함수)
    
    Args:
        decode_responses: 응답 디코딩 여부
        
    Returns:
        AsyncRedis: Redis 클라이언트
        
    Note:
        이 함수를 사용하기 전에 RedisConnectionManager를 먼저 초기화해야 합니다.
    """
    manager = RedisConnectionManager()
    return await manager.get_connection_async(decode_responses=decode_responses)


# ============================================================================
# New Connection Pool System (Recommended)
# ============================================================================

class RedisConnectionPool:
    """
    Modern Redis connection pool manager.

    Uses settings from shared.config for automatic configuration.
    """

    _pool: ConnectionPool | None = None
    _monitor: RedisPoolMonitor | None = None
    _lock = Lock()

    @classmethod
    def get_pool(cls) -> ConnectionPool:
        """
        Get or create Redis connection pool.

        Returns:
            ConnectionPool: Redis connection pool
        """
        if cls._pool is None:
            with cls._lock:
                if cls._pool is None:
                    cls._pool = aioredis.ConnectionPool.from_url(
                        settings.REDIS_URL,
                        max_connections=settings.REDIS_MAX_CONNECTIONS,
                        decode_responses=True,
                        socket_keepalive=True,
                        socket_connect_timeout=5,
                        retry_on_timeout=True,
                        health_check_interval=15,
                    )
                    logger.info(
                        f"✅ Redis pool created: {settings.REDIS_HOST}:{settings.REDIS_PORT} "
                        f"(max_connections={settings.REDIS_MAX_CONNECTIONS})"
                    )

                    # Initialize pool monitor
                    cls._monitor = RedisPoolMonitor(cls._pool)
                    logger.info("Redis pool monitor initialized")

        return cls._pool

    @classmethod
    def get_monitor(cls) -> RedisPoolMonitor:
        """
        Get Redis pool monitor.

        Returns:
            RedisPoolMonitor: Pool monitoring instance
        """
        if cls._monitor is None:
            # Ensure pool is created first
            cls.get_pool()

        assert cls._monitor is not None, "Monitor should be initialized after get_pool()"
        return cls._monitor

    @classmethod
    async def health_check(cls) -> dict:
        """
        Perform health check on Redis connection pool.

        Returns:
            dict: Health status with latency metrics

        Example:
            {
                "status": "healthy",
                "message": "Redis responding normally",
                "latency_ms": 1.23,
                "metrics": {
                    "max_connections": 200,
                    "connection_kwargs": {
                        "db": 0,
                        "decode_responses": true,
                        ...
                    }
                },
                "timestamp": "2025-10-05T10:30:45.123456"
            }
        """
        monitor = cls.get_monitor()
        return await monitor.health_check()

    @classmethod
    async def close_pool(cls):
        """Close Redis connection pool"""
        if cls._pool is not None:
            try:
                # Use asyncio.wait_for to add timeout protection
                await asyncio.wait_for(cls._pool.disconnect(), timeout=3.0)
            except asyncio.TimeoutError:
                logger.warning("Redis pool disconnect timed out after 3 seconds")
            except asyncio.CancelledError:
                logger.debug("Redis pool disconnect cancelled during shutdown")
                # Re-raise to allow proper cleanup chain
                raise
            except Exception as e:
                logger.error(f"Error disconnecting Redis pool: {e}", exc_info=True)
            finally:
                cls._pool = None
                cls._monitor = None
                logger.info("✅ Redis connection pool closed")


async def get_redis() -> AsyncRedis:
    """
    Get Redis client from connection pool (FastAPI dependency).

    The returned client supports async context manager protocol for explicit cleanup:

        # Pattern 1: FastAPI dependency injection (recommended for routes)
        @router.get("/cache")
        async def get_cache(redis: Redis = Depends(get_redis)):
            value = await redis.get("key")
            return {"value": value}

        # Pattern 2: Context manager (recommended for services)
        async with await get_redis() as redis:
            await redis.set("key", "value")

    Returns:
        AsyncRedis: Redis client instance with context manager support

    Note:
        The redis.asyncio.Redis client natively supports __aenter__ and __aexit__,
        allowing it to be used as an async context manager. When used in a context
        manager, the connection is properly cleaned up after use.
    """
    pool = RedisConnectionPool.get_pool()
    return AsyncRedis(connection_pool=pool)


async def init_redis():
    """Initialize Redis connection pool (call at app startup)"""
    try:
        redis = await get_redis()
        await redis.ping()
        logger.info(f"✅ Redis connected: {settings.REDIS_HOST}:{settings.REDIS_PORT}")
    except Exception as e:
        logger.error(f"❌ Redis connection failed: {e}")
        raise


async def close_redis():
    """Close Redis connections (call at app shutdown)"""
    try:
        await RedisConnectionPool.close_pool()
    except asyncio.CancelledError:
        # Suppress CancelledError during shutdown - this is normal when tasks are cancelled
        logger.debug("Redis close operation cancelled during shutdown")
        pass
    except Exception as e:
        logger.error(f"Error closing Redis: {e}", exc_info=True)


async def get_redis_binary() -> AsyncRedis:
    """
    Get Redis client with decode_responses=False (returns bytes).

    This is useful for operations that need to work with binary data
    or when you need explicit control over encoding/decoding.

    Returns:
        AsyncRedis: Redis client instance that returns bytes
    """
    manager = RedisConnectionManager()
    return await manager.get_connection_async(decode_responses=False)


def get_pool_metrics() -> dict[str, Any]:
    """
    Get current Redis connection pool metrics.

    Returns:
        dict: Pool configuration and metrics

    Example:
        {
            "max_connections": 200,
            "pool_class": "ConnectionPool",
            "connection_kwargs": {
                "db": 0,
                "decode_responses": True,
                "socket_keepalive": True,
                ...
            }
        }
    """
    pool = RedisConnectionPool.get_pool()
    return {
        "max_connections": pool.max_connections,
        "pool_class": pool.__class__.__name__,
        "connection_kwargs": pool.connection_kwargs,
    }


class RedisCircuitBreaker:
    """
    Simple circuit breaker for Redis operations.

    Prevents cascading failures by failing fast when Redis is unavailable.

    States:
        - CLOSED: Normal operation, requests pass through
        - OPEN: Too many failures, requests fail immediately
        - HALF_OPEN: Testing if Redis has recovered

    Usage:
        breaker = RedisCircuitBreaker()

        async def my_redis_operation():
            if breaker.is_open():
                raise Exception("Circuit breaker open - Redis unavailable")

            try:
                result = await redis.get("key")
                breaker.record_success()
                return result
            except RedisError:
                breaker.record_failure()
                raise
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        half_open_max_attempts: int = 3,
    ):
        """
        Initialize circuit breaker.

        Args:
            failure_threshold: Number of failures before opening circuit
            recovery_timeout: Seconds to wait before trying half-open state
            half_open_max_attempts: Max attempts in half-open state before reopening
        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_attempts = half_open_max_attempts

        self.failure_count = 0
        self.last_failure_time = 0.0
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
        self.half_open_attempts = 0

    def is_open(self) -> bool:
        """Check if circuit breaker is open (blocking requests)"""
        if self.state == "OPEN":
            # Check if recovery timeout has passed
            if time.time() - self.last_failure_time >= self.recovery_timeout:
                self.state = "HALF_OPEN"
                self.half_open_attempts = 0
                logger.info("Circuit breaker entering HALF_OPEN state")
                return False
            return True
        return False

    def record_success(self):
        """Record successful operation"""
        if self.state == "HALF_OPEN":
            self.half_open_attempts += 1
            if self.half_open_attempts >= self.half_open_max_attempts:
                self.state = "CLOSED"
                self.failure_count = 0
                logger.info("Circuit breaker CLOSED - Redis recovered")
        elif self.state == "CLOSED":
            # Reset failure count on success
            self.failure_count = 0

    def record_failure(self):
        """Record failed operation"""
        self.failure_count += 1
        self.last_failure_time = time.time()

        if self.state == "HALF_OPEN":
            self.state = "OPEN"
            logger.warning("Circuit breaker OPEN - Redis still unavailable")
        elif self.failure_count >= self.failure_threshold:
            self.state = "OPEN"
            logger.error(
                f"Circuit breaker OPEN - {self.failure_count} consecutive failures"
            )

    def get_state(self) -> dict[str, Any]:
        """Get current circuit breaker state"""
        return {
            "state": self.state,
            "failure_count": self.failure_count,
            "last_failure_time": self.last_failure_time,
            "is_open": self.is_open(),
        }


# Global circuit breaker instance (optional - can be enabled per strategy)
_global_circuit_breaker: RedisCircuitBreaker | None = None


def get_circuit_breaker() -> RedisCircuitBreaker:
    """
    Get global circuit breaker instance.

    Returns:
        RedisCircuitBreaker: Global circuit breaker
    """
    global _global_circuit_breaker
    if _global_circuit_breaker is None:
        _global_circuit_breaker = RedisCircuitBreaker()
    return _global_circuit_breaker
