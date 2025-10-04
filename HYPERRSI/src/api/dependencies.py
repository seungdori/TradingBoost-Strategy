#src.api.dependencies.py

from fastapi import  HTTPException
from typing import Optional
from HYPERRSI.src.core.database import redis_client_binary as redis_client
import ccxt.async_support as ccxt
import time
from datetime import timedelta
from contextlib  import asynccontextmanager
import logging
import asyncio


logger =  logging.getLogger(__name__)
class ExchangeConnectionPool:
    def __init__(self, redis_client, max_size=10, max_age=3600):  # max_age는 초 단위
        self.redis = redis_client
        self.max_size = max_size
        self.max_age = max_age
        self.pools = {}
        self._lock = asyncio.Lock()
        self._client_metadata = {}  # 클라이언트 생성 시간과 사용 횟수 추적

    async def _remove_client(self, user_id: str, client):
        """클라이언트 제거 및 정리"""
        if user_id in self.pools:
            if client in self.pools[user_id]['clients']:
                self.pools[user_id]['clients'].remove(client)
            if client in self.pools[user_id]['in_use']:
                self.pools[user_id]['in_use'].remove(client)
        if client in self._client_metadata:
            del self._client_metadata[client]
        await client.close()
        
        
    async def get_client(self, user_id: str, retry_count=0) -> ccxt.okx:
        # 최대 재시도 횟수 제한
        if retry_count >= 3:  # 3회 이상 재시도하면 예외 발생
            logger.error(f"Client pool is full for user {user_id}")
            raise Exception("클라이언트 풀이 가득 찼습니다.")
        
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
            for client in pool['clients']:
                if client not in pool['in_use']:
                    try:
                        await client.load_markets()
                        pool['in_use'].add(client)
                        return client
                    except Exception:
                        await self._remove_client(user_id, client)
            print(f"[{user_id}]Length of pool['clients']: {len(pool['clients'])}")
            # 새 클라이언트 생성
            if len(pool['clients']) < self.max_size:
                api_keys = await get_user_api_keys(user_id)
                client = ccxt.okx({
                    'apiKey': api_keys.get('api_key'),
                    'secret': api_keys.get('api_secret'),
                    'password': api_keys.get('passphrase'),
                    'options': {'defaultType': 'swap'}
                })
                pool['clients'].append(client)
                pool['in_use'].add(client)
                self._client_metadata[client] = {
                    'created_at': current_time,
                    'use_count': 0
                }
                return client
                
            # 풀이 가득 찼다면 대기
            logger.warning(f"Pool is full for user {user_id}, waiting... (retry {retry_count})")
            await asyncio.sleep(0.1 * (retry_count + 1))
            return await self.get_client(user_id, retry_count + 1)
    
    async def release_client(self, user_id: str, client):
        async with self._lock:
            if user_id in self.pools:
                self.pools[user_id]['in_use'].remove(client)
                
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
# 전역 pool 인스턴스 생성
connection_pool = ExchangeConnectionPool(redis_client)

def get_redis_keys(user_id: str, symbol:str, side:str) -> dict:
    """사용자별 Redis 키 생성"""
    return {
        'api_keys': f"user:{user_id}:api:keys",
        'trading_status': f"user:{user_id}:trading:status",
        'positions': f"user:{user_id}:position:{symbol}:{side}",
        'settings': f"user:{user_id}:settings"
    }

async def get_user_api_keys(user_id: str) -> dict:
    """Redis에서 사용자의 API 키 정보를 가져옴"""
    key = f"user:{user_id}:api:keys"
    try:
        #logger.info(f"Redis에서 키 조회 시작: {key}")
        api_keys = await redis_client.hgetall(key)
        #logger.info(f"Redis 원본 응답: {api_keys}, 타입: {type(api_keys)}")
        
        if not api_keys:
            logger.error(f"API 키 조회 실패: {str(user_id)}, 빈 결과 반환됨")
            raise HTTPException(status_code=404, detail="API keys not found")
        
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
        
        #logger.info(f"디코딩된 API 키: {decoded_keys}")
        
        if not all(k in decoded_keys for k in ['api_key', 'api_secret', 'passphrase']):
            logger.error(f"API 키 불완전: {decoded_keys}")
            raise HTTPException(status_code=400, detail="Incomplete API keys")
        
        return decoded_keys
    except Exception as e:
        logger.error(f"API 키 조회 중 예외 발생: {str(e)}, 키: {key}")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve API keys: {str(e)}")


# 기존 context manager는 그대로 유지, 내부만 변경
@asynccontextmanager
async def get_exchange_context(user_id: str):
    exchange = None
    try:
        exchange = await get_exchange_client(user_id)
        yield exchange
    finally:
        if exchange:
            try:
                await connection_pool.release_client(user_id, exchange)
            except Exception as e:
                logger.error(f"클라이언트 해제 중 오류 발생(context manager): {str(e)}, user_id: {user_id}")
                # 오류는 기록하되 예외가 전파되지 않도록 합니다
                pass

# 기존 get_exchange_client 함수도 인터페이스는 유지
async def get_exchange_client(user_id: str) -> ccxt.okx:
    try:
        #logger.info(f"Getting exchange client for user {user_id}")
        client = await connection_pool.get_client(user_id)
        
        # 풀 상태 로깅
        if user_id in connection_pool.pools:
            total = len(connection_pool.pools[user_id]['clients'])
            in_use = len(connection_pool.pools[user_id]['in_use'])
            #logger.info(f"Pool status for user {user_id}: {in_use}/{total} clients in use")
            
        return client
    except Exception as e:
        logger.error(f"Failed to get exchange client: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    
    
async def invalidate_exchange_client(user_id: str):
    async with connection_pool._lock:
        if user_id in connection_pool.pools:
            # 모든 클라이언트 정리
            for client in connection_pool.pools[user_id]['clients']:
                await client.close()
            # pool 제거
            connection_pool.pools.pop(user_id)
