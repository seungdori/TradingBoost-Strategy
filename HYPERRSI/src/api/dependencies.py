#src.api.dependencies.py

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Optional, TYPE_CHECKING

import ccxt.async_support as ccxt
from fastapi import HTTPException

from shared.database.redis_helper import get_redis_client as get_async_redis_client

if TYPE_CHECKING:
    import redis.asyncio as redis

# Prometheus metrics
try:
    from prometheus_client import Counter, Gauge, Histogram
    pool_metrics = {
        'client_created': Counter(
            'exchange_client_created_total',
            'Total exchange clients created',
            ['user_id']
        ),
        'client_released': Counter(
            'exchange_client_released_total',
            'Total exchange clients released',
            ['user_id']
        ),
        'client_error': Counter(
            'exchange_client_error_total',
            'Total exchange client errors',
            ['user_id', 'error_type']
        ),
        'wait_time': Histogram(
            'exchange_client_wait_seconds',
            'Time spent waiting for available client',
            ['user_id']
        ),
        'pool_size': Gauge(
            'exchange_pool_size',
            'Current pool size per user',
            ['user_id', 'status']
        )
    }
    HAS_METRICS = True
except ImportError:
    HAS_METRICS = False
    pool_metrics = {}


logger = logging.getLogger(__name__)

class ExchangeConnectionPool:
    def __init__(
        self,
        redis_client: Optional["redis.Redis"] = None,
        max_size: int = 10,
        max_age: int = 3600,
    ):  # max_age는 초 단위
        # Redis 클라이언트는 필요 시 초기화하는 지연 로딩 방식으로 유지한다.
        self._redis_client: Optional["redis.Redis"] = redis_client
        self.max_size = max_size
        self.max_age = max_age
        self.pools = {}
        self._lock = asyncio.Lock()
        self._client_metadata = {}  # 클라이언트 생성 시간과 사용 횟수 추적

    @property
    def redis(self) -> Optional["redis.Redis"]:
        return self._redis_client

    async def ensure_redis(self) -> "redis.Redis":
        if self._redis_client is None:
            self._redis_client = await get_async_redis_client()
        return self._redis_client

    async def _remove_client(self, user_id: str, client):
        """클라이언트 제거 및 정리"""
        try:
            # 먼저 풀에서 제거 (close 실패 시에도 풀에서는 제거됨)
            if user_id in self.pools:
                if client in self.pools[user_id]['clients']:
                    self.pools[user_id]['clients'].remove(client)
                if client in self.pools[user_id]['in_use']:
                    self.pools[user_id]['in_use'].discard(client)
            if client in self._client_metadata:
                del self._client_metadata[client]
        finally:
            # 클라이언트 종료는 항상 시도
            try:
                await client.close()
            except Exception as e:
                logger.error(f"Error closing client: {e}")
        
        
    async def get_client(self, user_id: str, retry_count=0) -> ccxt.okx:
        # 최대 재시도 횟수 제한
        if retry_count >= 3:  # 3회 이상 재시도하면 예외 발생
            logger.error(f"Client pool is full for user {user_id}")
            if HAS_METRICS:
                pool_metrics['client_error'].labels(
                    user_id=user_id,
                    error_type='pool_full'
                ).inc()
            raise Exception("클라이언트 풀이 가득 찼습니다.")

        wait_start = time.time()

        async with self._lock:
            current_time = time.time()
            
            # 사용자 풀이 없으면 초기화
            if user_id not in self.pools:
                self.pools[user_id] = {
                    'clients': [],
                    'in_use': set()
                }
            
            # 오래된 클라이언트 제거
            for client in list(self.pools[user_id]['clients']):
                if current_time - self._client_metadata.get(client, {}).get('created_at', 0) > self.max_age:
                    await self._remove_client(user_id, client)
            
            pool = self.pools[user_id]
            
            # 사용 가능한 클라이언트 찾기
            for client in list(pool['clients']):  # list()로 복사하여 안전한 순회
                if client not in pool['in_use']:
                    try:
                        # 타임아웃 적용하여 load_markets 호출
                        await asyncio.wait_for(
                            client.load_markets(),
                            timeout=5.0
                        )
                        pool['in_use'].add(client)

                        # Record metrics
                        if HAS_METRICS:
                            wait_time = time.time() - wait_start
                            pool_metrics['wait_time'].labels(user_id=user_id).observe(wait_time)
                            self._update_pool_metrics(user_id)

                        return client
                    except (asyncio.TimeoutError, Exception) as e:
                        logger.warning(f"Client validation failed for user {user_id}: {e}")
                        await self._remove_client(user_id, client)
            # 새 클라이언트 생성
            if len(pool['clients']) < self.max_size:
                client = None
                added_to_pool = False
                try:
                    api_keys = await get_user_api_keys(user_id)
                    client = ccxt.okx({
                        'apiKey': api_keys.get('api_key'),
                        'secret': api_keys.get('api_secret'),
                        'password': api_keys.get('passphrase'),
                        'options': {'defaultType': 'swap'},
                        'enableRateLimit': True,  # API 호출 제한 준수
                    })

                    # 초기 market 로드 (타임아웃 적용)
                    await asyncio.wait_for(
                        client.load_markets(),
                        timeout=5.0
                    )

                    pool['clients'].append(client)
                    pool['in_use'].add(client)
                    self._client_metadata[client] = {
                        'created_at': current_time,
                        'use_count': 0
                    }
                    added_to_pool = True

                    # Record metrics
                    if HAS_METRICS:
                        pool_metrics['client_created'].labels(user_id=user_id).inc()
                        wait_time = time.time() - wait_start
                        pool_metrics['wait_time'].labels(user_id=user_id).observe(wait_time)
                        self._update_pool_metrics(user_id)

                    logger.info(f"Created new exchange client for user {user_id}")
                    return client
                except ccxt.AuthenticationError as e:
                    # API 키 인증 오류 (잘못된 키, 만료된 키, IP 화이트리스트 문제 등)
                    logger.error(f"Failed to create exchange client for user {user_id}: {e}")
                    if HAS_METRICS:
                        pool_metrics['client_error'].labels(
                            user_id=user_id,
                            error_type='authentication'
                        ).inc()
                    raise HTTPException(
                        status_code=401,
                        detail=f"API 키 인증 실패: {str(e)}"
                    )
                except HTTPException as http_exc:
                    # HTTPException을 그대로 전파 (특히 404 API keys not found)
                    if HAS_METRICS and http_exc.status_code == 404:
                        pool_metrics['client_error'].labels(
                            user_id=user_id,
                            error_type='api_keys_not_found'
                        ).inc()
                    raise
                except Exception as e:
                    logger.error(f"Failed to create exchange client for user {user_id}: {e}")
                    if HAS_METRICS:
                        pool_metrics['client_error'].labels(
                            user_id=user_id,
                            error_type='initialization'
                        ).inc()
                    raise HTTPException(
                        status_code=500,
                        detail=f"Failed to initialize exchange client: {str(e)}"
                    )
                finally:
                    if client is not None and not added_to_pool:
                        try:
                            await client.close()
                        except Exception as close_error:
                            logger.warning(
                                "Failed to close exchange client after error for user %s: %s",
                                user_id,
                                close_error,
                            )

            # 풀이 가득 찼다면 대기 후 재시도 (지수 백오프)
            backoff_time = 0.5 * (2 ** retry_count)  # 0.5s, 1s, 2s
            logger.warning(
                f"Pool is full for user {user_id}, waiting {backoff_time}s... (retry {retry_count + 1}/3)"
            )
            await asyncio.sleep(backoff_time)
            return await self.get_client(user_id, retry_count + 1)
    
    async def release_client(self, user_id: str, client):
        async with self._lock:
            if user_id in self.pools:
                self.pools[user_id]['in_use'].discard(client)

                # Record metrics
                if HAS_METRICS:
                    pool_metrics['client_released'].labels(user_id=user_id).inc()
                    self._update_pool_metrics(user_id)
                
    async def cleanup_user_pool(self, user_id: str):
        """특정 사용자의 모든 클라이언트 정리"""
        async with self._lock:
            if user_id in self.pools:
                for client in self.pools[user_id]['clients']:
                    await client.close()
                del self.pools[user_id]

    async def check_client_health(self, client):
        """클라이언트 상태 확인"""
        try:
            await client.load_markets()
            return True
        except Exception:
            return False

    def _update_pool_metrics(self, user_id: str):
        """Update Prometheus metrics for pool"""
        if not HAS_METRICS or user_id not in self.pools:
            return

        pool = self.pools[user_id]
        total = len(pool['clients'])
        in_use = len(pool['in_use'])
        available = total - in_use

        pool_metrics['pool_size'].labels(user_id=user_id, status='total').set(total)
        pool_metrics['pool_size'].labels(user_id=user_id, status='in_use').set(in_use)
        pool_metrics['pool_size'].labels(user_id=user_id, status='available').set(available)
# 전역 pool 인스턴스 - lazy initialization
connection_pool = None

def get_connection_pool():
    """Get or create global connection pool lazily"""
    global connection_pool
    if connection_pool is None:
        connection_pool = ExchangeConnectionPool()
    return connection_pool

def get_redis_keys(user_id: str, symbol:str, side:str) -> dict:
    """사용자별 Redis 키 생성"""
    return {
        'api_keys': f"user:{user_id}:api:keys",
        'trading_status': f"user:{user_id}:trading:status",
        'positions': f"user:{user_id}:position:{symbol}:{side}",
        'settings': f"user:{user_id}:settings"
    }

async def get_user_api_keys(user_id: str, raise_on_missing: bool = True) -> Optional[dict]:
    """Redis에서 사용자의 API 키 정보를 가져옴

    Args:
        user_id: 사용자 ID
        raise_on_missing: True일 경우 키가 없으면 HTTPException 발생, False일 경우 None 반환

    Returns:
        API 키 딕셔너리 또는 None (raise_on_missing=False이고 키가 없는 경우)
    """
    from shared.database.redis import get_redis_binary

    key = f"user:{user_id}:api:keys"
    try:
        redis_client = await get_redis_binary()
        api_keys = await redis_client.hgetall(key)

        if not api_keys:
            logger.info(f"API 키 조회 실패: {str(user_id)}, 빈 결과 반환됨")
            if raise_on_missing:
                raise HTTPException(status_code=404, detail="API keys not found")
            return None

        # 디코딩 단계 분리하여 오류 추적
        decoded_keys = {}
        for k, v in api_keys.items():
            try:
                key_str = k.decode('utf-8') if isinstance(k, bytes) else k
                val_str = v.decode('utf-8') if isinstance(v, bytes) else v
                decoded_keys[key_str] = val_str
                logger.debug(f"키 디코딩: {k} -> {key_str}, 값 디코딩: {v} -> {val_str}")
            except Exception as e:
                logger.error(f"키 디코딩 오류: {k}, {v}, 오류: {str(e)}")

        if not all(k in decoded_keys for k in ['api_key', 'api_secret', 'passphrase']):
            logger.error(f"API 키 불완전: {decoded_keys}")
            if raise_on_missing:
                raise HTTPException(status_code=400, detail="Incomplete API keys")
            return None

        return decoded_keys
    except HTTPException:
        # HTTPException은 그대로 재발생
        raise
    except Exception as e:
        logger.error(f"API 키 조회 중 예외 발생: {str(e)}, 키: {key}")
        if raise_on_missing:
            raise HTTPException(status_code=500, detail=f"Failed to retrieve API keys: {str(e)}")
        return None


# 기존 context manager는 그대로 유지, 내부만 변경
@asynccontextmanager
async def get_exchange_context(user_id: str):
    exchange = None
    pool = get_connection_pool()
    try:
        exchange = await get_exchange_client(user_id)
        yield exchange
    finally:
        if exchange:
            try:
                await pool.release_client(user_id, exchange)
            except Exception as e:
                logger.error(f"클라이언트 해제 중 오류 발생(context manager): {str(e)}, user_id: {user_id}")
                # 오류는 기록하되 예외가 전파되지 않도록 합니다
                pass

# 기존 get_exchange_client 함수도 인터페이스는 유지
async def get_exchange_client(user_id: str) -> ccxt.okx:
    pool = get_connection_pool()
    try:
        #logger.info(f"Getting exchange client for user {user_id}")
        client = await pool.get_client(user_id)

        # 풀 상태 로깅
        if user_id in pool.pools:
            total = len(pool.pools[user_id]['clients'])
            in_use = len(pool.pools[user_id]['in_use'])
            #logger.info(f"Pool status for user {user_id}: {in_use}/{total} clients in use")

        return client
    except HTTPException:
        # HTTPException은 그대로 전파 (404, 401 등)
        raise
    except Exception as e:
        logger.error(f"Failed to get exchange client: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def invalidate_exchange_client(user_id: str):
    pool = get_connection_pool()
    async with pool._lock:
        if user_id in pool.pools:
            # 모든 클라이언트 정리
            for client in pool.pools[user_id]['clients']:
                await client.close()
            # pool 제거
            pool.pools.pop(user_id)
