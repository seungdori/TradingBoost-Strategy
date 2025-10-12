import asyncio
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from typing import Any

import ccxt.pro as ccxtpro
import redis.asyncio as aioredis

from shared.config import OKX_API_KEY, OKX_PASSPHRASE, OKX_SECRET_KEY, settings  # 환경 변수에서 키 가져오기

REDIS_PASSWORD = settings.REDIS_PASSWORD

class ReadOnlyKeys:

    #binance_keys = 'mRBd4yWAhv2EV5bxQHsdyXIvh3JqqByO5Tt6SF246zkSkVPqexCCkCT4nffwEjK6'
    #binance_secret= 'MKHfE31P4Ktqy7RbMSfmfd6wzhPVfr881W77y6DrWe62ooa87HQI1kC5chCIHDJj'
    #upbit_keys = 'ezyT53BMGEetuw1Fxx4DTV3sTsnDalLdM8sdaziJ'
    #upbit_secret= 'YxdJM8vAS0pvKc76EFB8z0FjBTf4zc8Lx0xP8spr'

    #bitget_keys ='bg_f1a2d50a1461661a047db47d89920509'
    #bitegt_secret= '081832a19231d65a86b22a52116a06cfdaa36eb550eae3eaae6854cb6c41bbf7'
    #bitget_password='tmzkdl2014'
    
    #OKX READ ONLY
    okx_keys = OKX_API_KEY
    okx_secret = OKX_SECRET_KEY
    okx_password=OKX_PASSPHRASE
    #okx_keys = 'f542196a-e52e-45b0-94dd-57f93da29a11' 
    #okx_secret = '3CD5713E0466FBF591C50972DE3FB6D3'
    #okx_password='Dlrudtlr11!1'
    
    #okx_keys = 'd8d10ac3-2890-4bb9-95f0-70f857dc38e3' 
    #okx_secret = '7080F1F233F77A081F735E8C0E6F1FF3'
    #okx_password='Lej1321428!'





class ThreadSafeAsyncExchangeManager:
    def __init__(self) -> None:
        self.instances: dict[str, dict[str, Any]] = {}
        self.locks: dict[str, asyncio.Lock] = {}
        self.global_lock = Lock()
        self.INSTANCE_TIMEOUT = 3600  # 1 hour
        self.redis: aioredis.Redis | None = None

    async def init_redis(self) -> None:
        if REDIS_PASSWORD:
            self.redis = await aioredis.from_url('redis://localhost', encoding='utf-8', decode_responses=True,password=REDIS_PASSWORD)
        else:
            self.redis = await aioredis.from_url('redis://localhost', encoding='utf-8', decode_responses=True)

    async def get_instance(self, exchange_name: str, user_id: str) -> Any | None:
        if exchange_name.lower() != 'okx':
            print(f"Exchange {exchange_name} is not supported by this manager")
            raise ValueError("This manager is configured only for OKX")

        key = f"{exchange_name}:{user_id}"
        
        async with self._get_lock(key):
            if key in self.instances:
                instance_data = self.instances[key]
                if asyncio.get_event_loop().time() - instance_data['last_used'] <= self.INSTANCE_TIMEOUT:
                    instance_data['last_used'] = asyncio.get_event_loop().time()
                    print(f"Reused instance for {key}")
                    return instance_data['instance']
                else:
                    await self.close_instance(key)
            
            new_instance = await self._create_okx_instance(user_id)
            if new_instance:
                self.instances[key] = {
                    'instance': new_instance,
                    'last_used': asyncio.get_event_loop().time(),
                }
                return new_instance
            return None

    def _get_lock(self, key: str) -> asyncio.Lock:
        with self.global_lock:
            if key not in self.locks:
                self.locks[key] = asyncio.Lock()
            return self.locks[key]

    async def _create_okx_instance(self, user_id: str) -> Any | None:
        if self.redis is None:
            await self.init_redis()

        try:
            if user_id == '999999999' or user_id == 'admin':
                return ccxtpro.okx({
                    'apiKey': ReadOnlyKeys.okx_keys,
                    'secret': ReadOnlyKeys.okx_secret,
                    'password': ReadOnlyKeys.okx_password,
                    'enableRateLimit': True,
                    'options': {
                        'defaultType': 'future'
                    }
                })
            else:
                user_key = f'okx:user:{user_id}'
                if self.redis is not None:
                    user_data = await self.redis.hgetall(user_key)
                else:
                    user_data = {}
                if user_data and 'api_key' in user_data:
                    return ccxtpro.okx({
                        'apiKey': user_data['api_key'],
                        'secret': user_data['api_secret'],
                        'password': user_data['password'],
                        'enableRateLimit': True,
                        'options': {
                            'defaultType': 'future'
                        }
                    })
                else:
                    print(f"No API keys found for user {user_id}")
                    return None
        except Exception as e:
            print(f"Error creating okx instance for {user_id}: {e}")
            return None

    async def close_instance(self, key: str) -> None:
        if key in self.instances:
            instance_data = self.instances[key]
            await instance_data['instance'].close()
            del self.instances[key]

    async def cleanup_inactive_instances(self) -> None:
        current_time = asyncio.get_event_loop().time()
        keys_to_remove = []
        for key, instance_data in self.instances.items():
            if current_time - instance_data['last_used'] > self.INSTANCE_TIMEOUT:
                await self.close_instance(key)
                keys_to_remove.append(key)
        for key in keys_to_remove:
            del self.instances[key]


# Global instance of the manager
exchange_manager = ThreadSafeAsyncExchangeManager()

# 주기적 정리 태스크 시작
async def start_cleanup_task():
    while True:
        await exchange_manager.cleanup_inactive_instances()
        await asyncio.sleep(3600)  # 1시간마다 실행
        
async def get_exchange_instance(exchange_name: str, user_id: str) -> Any | None:
    return await exchange_manager.get_instance(exchange_name, user_id)




# In your main application
# Note: run_async_task is deprecated - use asyncio.create_task() instead
# def run_async_task(coro):
#     asyncio.run_coroutine_threadsafe(coro, exchange_manager.loop)


# Main thread - commented out as this manager doesn't have loop or periodic_cleanup
# if __name__ == "__main__":
#     # Start the event loop
#     exchange_manager.loop.create_task(exchange_manager.periodic_cleanup())
#     exchange_manager.loop.run_forever()