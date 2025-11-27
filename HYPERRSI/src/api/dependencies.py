#src.api.dependencies.py

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Annotated, Optional, TYPE_CHECKING

import ccxt.async_support as ccxt
from fastapi import Depends, HTTPException, Path

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


async def resolve_user_id_to_okx_uid(user_id: str) -> str:
    """
    user_id가 telegram_id인 경우 OKX UID로 변환합니다.

    ⚠️ 이 함수는 shared.helpers.user_id_resolver.resolve_user_identifier의 래퍼입니다.
    실제 변환 로직은 user_id_resolver 모듈에서 통합 관리됩니다.

    Args:
        user_id: 사용자 ID (telegram_id 또는 OKX UID)

    Returns:
        str: OKX UID (변환 실패 시 원본 user_id 반환)
    """
    from shared.helpers.user_id_resolver import resolve_user_identifier

    try:
        return await resolve_user_identifier(user_id)
    except Exception as e:
        logger.warning(f"Failed to resolve user_id {user_id}: {e}")
        # errordb 로깅 (WARNING 레벨)
        from HYPERRSI.src.utils.error_logger import log_error_to_db
        log_error_to_db(
            error=e,
            error_type="UserIdResolutionError",
            user_id=user_id,
            severity="WARNING",
            metadata={"component": "dependencies.resolve_user_id_to_okx_uid"}
        )
        return user_id


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
                # errordb 로깅
                from HYPERRSI.src.utils.error_logger import log_error_to_db
                log_error_to_db(
                    error=e,
                    error_type="ClientCloseError",
                    user_id=user_id,
                    severity="WARNING",
                    metadata={"component": "ExchangeConnectionPool._remove_client"}
                )
        
        
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
                        # 타임아웃 적용하여 load_markets 호출 (네트워크 지연 대응)
                        await asyncio.wait_for(
                            client.load_markets(),
                            timeout=15.0
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
                        # errordb 로깅
                        from HYPERRSI.src.utils.error_logger import log_error_to_db
                        log_error_to_db(
                            error=e,
                            error_type="ClientValidationError",
                            user_id=user_id,
                            severity="WARNING",
                            metadata={"component": "ExchangeConnectionPool.get_client"}
                        )
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
                        'enableRateLimit': True,  # API 호출 제한 준수
                        'timeout': 30000,  # 30초 타임아웃 (네트워크 지연 대응)
                        'options': {
                            'defaultType': 'swap',
                            'adjustForTimeDifference': True,  # 서버 시간 차이 자동 조정
                            'recvWindow': 10000,  # 요청 수신 윈도우 10초
                        },
                    })

                    # 초기 market 로드 (타임아웃 적용, 네트워크 지연 대응)
                    await asyncio.wait_for(
                        client.load_markets(),
                        timeout=15.0
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
                    # errordb 로깅
                    from HYPERRSI.src.utils.error_logger import log_error_to_db
                    log_error_to_db(
                        error=e,
                        error_type="ExchangeAuthenticationError",
                        user_id=user_id,
                        severity="CRITICAL",
                        metadata={"component": "ExchangeConnectionPool.get_client"}
                    )
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
                    # errordb 로깅
                    from HYPERRSI.src.utils.error_logger import log_error_to_db
                    log_error_to_db(
                        error=e,
                        error_type="ExchangeClientInitError",
                        user_id=user_id,
                        severity="CRITICAL",
                        metadata={"component": "ExchangeConnectionPool.get_client"}
                    )
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
                            # errordb 로깅
                            from HYPERRSI.src.utils.error_logger import log_error_to_db
                            log_error_to_db(
                                error=close_error,
                                error_type="ClientCleanupError",
                                user_id=user_id,
                                severity="WARNING",
                                metadata={"component": "ExchangeConnectionPool.get_client.finally"}
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
    """사용자별 Redis 키 생성 (심볼별 상태 관리)"""
    return {
        'api_keys': f"user:{user_id}:api:keys",
        'symbol_status': f"user:{user_id}:symbol:{symbol}:status",  # 심볼별 상태
        'positions': f"user:{user_id}:position:{symbol}:{side}",
        'settings': f"user:{user_id}:settings"
    }

async def get_user_api_keys(user_id: str, raise_on_missing: bool = True) -> Optional[dict]:
    """사용자의 API 키 정보를 TimescaleDB (primary)와 Redis (fallback)에서 가져옴

    조회 우선순위:
    1. TimescaleDB (영구 저장소)
    2. Redis (캐시 레이어) - TimescaleDB 실패 시 fallback

    Args:
        user_id: 사용자 ID (telegram_id 또는 OKX UID)
        raise_on_missing: True일 경우 키가 없으면 HTTPException 발생, False일 경우 None 반환

    Returns:
        API 키 딕셔너리 또는 None (raise_on_missing=False이고 키가 없는 경우)
    """
    from shared.database.redis import get_redis_binary
    from HYPERRSI.src.services.timescale_service import TimescaleUserService
    from shared.security import decrypt_api_key

    try:
        # telegram_id를 OKX UID로 변환
        resolved_user_id = await resolve_user_id_to_okx_uid(user_id)

        # 1️⃣ TimescaleDB 우선 조회 (Primary Storage)
        try:
            api_keys = await TimescaleUserService.get_api_keys(resolved_user_id)
            if api_keys:
                logger.debug(f"API 키 조회 성공 (TimescaleDB): {resolved_user_id}")

                # API 키 복호화 (TimescaleDB에 암호화되어 저장됨)
                decrypted_keys = {}
                for key_name, encrypted_value in api_keys.items():
                    try:
                        decrypted_keys[key_name] = decrypt_api_key(encrypted_value)
                    except Exception as e:
                        logger.warning(f"API 키 복호화 실패 ({key_name}): {e}, 평문 사용")
                        # errordb 로깅
                        from HYPERRSI.src.utils.error_logger import log_error_to_db
                        log_error_to_db(
                            error=e,
                            error_type="APIKeyDecryptionError",
                            user_id=resolved_user_id,
                            severity="WARNING",
                            metadata={"key_name": key_name, "component": "get_user_api_keys"}
                        )
                        decrypted_keys[key_name] = encrypted_value

                # Redis에도 캐싱 (향후 빠른 조회를 위해)
                try:
                    redis_client = await get_redis_binary()
                    cache_key = f"user:{resolved_user_id}:api:keys"
                    await redis_client.hmset(cache_key, decrypted_keys)
                    logger.debug(f"API 키 Redis 캐싱 완료: {resolved_user_id}")
                except Exception as cache_error:
                    logger.warning(f"Redis 캐싱 실패: {cache_error}")
                    # errordb 로깅 (WARNING 레벨)
                    from HYPERRSI.src.utils.error_logger import log_error_to_db
                    log_error_to_db(
                        error=cache_error,
                        error_type="RedisCachingError",
                        user_id=resolved_user_id,
                        severity="WARNING",
                        metadata={"component": "get_user_api_keys"}
                    )

                return decrypted_keys
        except Exception as ts_error:
            logger.warning(f"TimescaleDB API 키 조회 실패: {ts_error}, Redis fallback 시도")
            # errordb 로깅 (WARNING - fallback이 있으므로)
            from HYPERRSI.src.utils.error_logger import log_error_to_db
            log_error_to_db(
                error=ts_error,
                error_type="TimescaleDBLookupError",
                user_id=resolved_user_id,
                severity="WARNING",
                metadata={"component": "get_user_api_keys", "fallback": "Redis"}
            )

        # 2️⃣ Redis fallback (Cache Layer)
        redis_client = await get_redis_binary()
        key = f"user:{resolved_user_id}:api:keys"
        api_keys = await redis_client.hgetall(key)

        if not api_keys:
            logger.info(f"API 키 조회 실패 (Redis + TimescaleDB): {str(user_id)} (resolved: {resolved_user_id})")
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
                # errordb 로깅
                from HYPERRSI.src.utils.error_logger import log_error_to_db
                log_error_to_db(
                    error=e,
                    error_type="KeyDecodingError",
                    user_id=resolved_user_id,
                    severity="ERROR",
                    metadata={"component": "get_user_api_keys"}
                )

        if not all(k in decoded_keys for k in ['api_key', 'api_secret', 'passphrase']):
            logger.error(f"API 키 불완전: {decoded_keys}")
            if raise_on_missing:
                raise HTTPException(status_code=400, detail="Incomplete API keys")
            return None

        logger.info(f"API 키 조회 성공 (Redis fallback): {resolved_user_id}")
        return decoded_keys
    except HTTPException:
        # HTTPException은 그대로 재발생
        raise
    except Exception as e:
        logger.error(f"API 키 조회 중 예외 발생: {str(e)}, user_id: {user_id}")
        # errordb 로깅
        from HYPERRSI.src.utils.error_logger import log_error_to_db
        log_error_to_db(
            error=e,
            error_type="APIKeyRetrievalError",
            user_id=user_id,
            severity="CRITICAL",
            metadata={"component": "get_user_api_keys"}
        )
        if raise_on_missing:
            raise HTTPException(status_code=500, detail=f"Failed to retrieve API keys: {str(e)}")
        return None


# 기존 context manager는 그대로 유지, 내부만 변경
@asynccontextmanager
async def get_exchange_context(user_id: str):
    exchange = None
    pool = get_connection_pool()

    # telegram_id를 OKX UID로 변환 (pool 키 일관성 유지)
    resolved_user_id = await resolve_user_id_to_okx_uid(user_id)

    try:
        exchange = await get_exchange_client(user_id)
        yield exchange
    finally:
        if exchange:
            try:
                await pool.release_client(resolved_user_id, exchange)
            except Exception as e:
                logger.error(f"클라이언트 해제 중 오류 발생(context manager): {str(e)}, user_id: {user_id} (resolved: {resolved_user_id})")
                # errordb 로깅
                from HYPERRSI.src.utils.error_logger import log_error_to_db
                log_error_to_db(
                    error=e,
                    error_type="ClientReleaseError",
                    user_id=user_id,
                    severity="WARNING",
                    metadata={"resolved_user_id": resolved_user_id, "component": "get_exchange_context"}
                )
                # 오류는 기록하되 예외가 전파되지 않도록 합니다
                pass

# 기존 get_exchange_client 함수도 인터페이스는 유지
async def get_exchange_client(user_id: str) -> ccxt.okx:
    pool = get_connection_pool()
    try:
        # telegram_id를 OKX UID로 변환 (connection pool 키 일관성 유지)
        resolved_user_id = await resolve_user_id_to_okx_uid(user_id)

        #logger.info(f"Getting exchange client for user {user_id}")
        client = await pool.get_client(resolved_user_id)

        # 풀 상태 로깅
        if resolved_user_id in pool.pools:
            total = len(pool.pools[resolved_user_id]['clients'])
            in_use = len(pool.pools[resolved_user_id]['in_use'])
            #logger.info(f"Pool status for user {resolved_user_id}: {in_use}/{total} clients in use")

        return client
    except HTTPException:
        # HTTPException은 그대로 전파 (404, 401 등)
        raise
    except Exception as e:
        logger.error(f"Failed to get exchange client: {e}")
        # errordb 로깅
        from HYPERRSI.src.utils.error_logger import log_error_to_db
        log_error_to_db(
            error=e,
            error_type="GetExchangeClientError",
            user_id=user_id,
            severity="CRITICAL",
            metadata={"component": "get_exchange_client"}
        )
        raise HTTPException(status_code=500, detail=str(e))


async def invalidate_exchange_client(user_id: str):
    pool = get_connection_pool()

    # telegram_id를 OKX UID로 변환 (pool 키 일관성 유지)
    resolved_user_id = await resolve_user_id_to_okx_uid(user_id)

    async with pool._lock:
        if resolved_user_id in pool.pools:
            # 모든 클라이언트 정리
            for client in pool.pools[resolved_user_id]['clients']:
                await client.close()
            # pool 제거
            pool.pools.pop(resolved_user_id)
            logger.info(f"Invalidated exchange client pool for user {user_id} (resolved: {resolved_user_id})")


# ============================================================================
# FastAPI Dependency Injection - User ID 자동 변환
# ============================================================================

async def get_resolved_okx_uid(
    user_id: str = Path(..., description="사용자 ID (텔레그램 ID 또는 OKX UID)")
) -> str:
    """
    FastAPI Dependency: Path 파라미터의 user_id를 자동으로 OKX UID로 변환합니다.

    사용 예시:
        @router.get("/{user_id}/positions")
        async def get_positions(okx_uid: ResolvedOkxUid):
            # okx_uid는 이미 변환된 OKX UID
            ...

    Args:
        user_id: Path 파라미터로 받은 사용자 ID

    Returns:
        str: OKX UID
    """
    return await resolve_user_id_to_okx_uid(user_id)


async def get_resolved_okx_uid_from_query(
    user_id: str
) -> str:
    """
    FastAPI Dependency: Query 파라미터의 user_id를 자동으로 OKX UID로 변환합니다.

    Args:
        user_id: Query 파라미터로 받은 사용자 ID

    Returns:
        str: OKX UID
    """
    return await resolve_user_id_to_okx_uid(user_id)


# 타입 별칭 정의 - 라우트에서 사용
ResolvedOkxUid = Annotated[str, Depends(get_resolved_okx_uid)]
ResolvedOkxUidQuery = Annotated[str, Depends(get_resolved_okx_uid_from_query)]
