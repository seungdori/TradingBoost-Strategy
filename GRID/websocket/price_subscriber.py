from shared.database.redis_patterns import redis_context, RedisTTL
import asyncio
import json
import logging
import os
from datetime import datetime, timezone

import ccxt.pro as ccxt
import redis.asyncio as aioredis

from shared.config import settings
from GRID.core.redis import get_redis_connection

REDIS_URL = settings.REDIS_URL

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    
class PriceSubscriber:
    def __init__(self, redis_url=REDIS_URL):
        self.redis_pool = None
        self.pubsub = None
        self.price_cache = {}
        self.subscribers = set()
        self.REDIS_URL = redis_url
        self.exchanges = {}
        self.is_running = True
        self.last_update_time = {}

    async def initialize(self):
        """Initialize Redis connection using shared connection pool"""
        while self.is_running:
            try:
                async with redis_context() as redis:
                    self.redis_pool = redis
                    self.pubsub = redis.pubsub()
                    await self.pubsub.subscribe('price_update')
                    logging.info("Successfully connected to Redis and subscribed to price updates.")
                    return True
            except Exception as e:
                logging.error(f"Failed to connect to Redis: {e}. Retrying in 5 seconds...")
                await asyncio.sleep(5)
        return False

    async def listen_for_updates(self):
        while self.is_running:
            try:
                message = await self.pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0) # type: ignore[union-attr]
                if message:
                    try:
                        data = json.loads(message['data'])  # JSON 디코딩
                        symbol = data["symbol"]
                        price = float(data["price"])
                        timestamp = float(data["timestamp"])
                        self.price_cache[symbol] = (price, timestamp)
                        self.last_update_time[symbol] = datetime.now(timezone.utc)
                        logging.debug(f"Received update for {symbol}: price={price}, timestamp={timestamp}")

                        for callback in self.subscribers:
                            asyncio.create_task(callback(symbol, price, timestamp))
                    except json.JSONDecodeError as e:
                        logging.error(f"Invalid JSON message: {message['data']}. Error: {e}")
                    except Exception as e:
                        logging.error(f"Error processing message: {e}. Raw message: {message}")
                else:
                    logging.debug("No new messages")
            except aioredis.RedisError as e:
                logging.error(f"Redis error in listen_for_updates: {e}. Attempting to reconnect...")
                if not await self.reconnect(): # type: ignore[attr-defined]
                    break
            except Exception as e:
                logging.error(f"Unexpected error in listen_for_updates: {e}")
                await asyncio.sleep(1)


    async def get_exchange(self, exchange_name):
        if exchange_name not in self.exchanges:
            exchange_class = getattr(ccxt, exchange_name)
            self.exchanges[exchange_name] = exchange_class({
                'options': {'defaultType': 'future'}
            })
        return self.exchanges[exchange_name]


    def convert_symbol(self, symbol: str) -> str:
        """OKX 형식의 심볼을 CCXT 형식으로 변환"""
        if '-SWAP' in symbol:
            base, quote, _ = symbol.split('-')
            return f"{base}/{quote}:{quote}"
        return symbol  # 이미 CCXT 형식이거나 다른 형식일 경우 그대로 반환

    async def get_current_price(self, exchange_name, symbol):
        CACHE_VALIDITY = 30  # 캐시 유효 기간을 30초로 연장
        REDIS_VALIDITY = 60  # Redis 데이터 유효 기간을 60초로 설정
        EMERGENCY_CACHE_VALIDITY = 300  # 긴급 캐시 유효 기간 5분

        retry_count = 0
        max_retries = 3
        
        while retry_count < max_retries:
            try:
                current_time = datetime.now(timezone.utc)
                
                if self.redis_pool is None:
                    await self.initialize()
                
                # 메모리 캐시 확인
                if symbol in self.price_cache:
                    price, timestamp = self.price_cache[symbol]
                    cache_age = (current_time - self.last_update_time.get(symbol, current_time)).total_seconds()
                    logging.debug(f"Cache for {symbol}: price={price}, age={cache_age}s")
                    if cache_age <= CACHE_VALIDITY:
                        return float(price)
                
                logging.debug(f"Cache miss or expired for {symbol}, querying Redis")

                # Redis 확인
                try:
                    price_data = await self.redis_pool.get(f"price:{symbol}")
                    if price_data:
                        price, timestamp = price_data.split(':') # type: ignore[arg-type]
                        price = float(price)
                        timestamp = float(timestamp)
                        redis_age = (current_time - datetime.fromtimestamp(timestamp, timezone.utc)).total_seconds()
                        logging.debug(f"Redis data for {symbol}: price={price}, age={redis_age}s")
                        if redis_age <= REDIS_VALIDITY:
                            self.price_cache[symbol] = (price, timestamp)
                            self.last_update_time[symbol] = current_time
                            return price
                    else:
                        logging.debug(f"No data in Redis for {symbol}")
                except Exception as e:
                    logging.error(f"Redis error in get_current_price: {e}")
                
                # CCXT에서 가격 가져오기
                logging.debug(f"Fetching price for {symbol} from CCXT")
                exchange = await self.get_exchange(exchange_name)
                try:
                    await asyncio.sleep(0.5)
                    ticker = await exchange.fetch_ticker(symbol)
                    new_price = ticker['last']
                    new_timestamp = datetime.now(timezone.utc).timestamp()
                    logging.debug(f"CCXT price for {symbol}: {new_price}")

                    # Redis 업데이트
                    try:
                        await self.redis_pool.set(f"price:{symbol}", f"{new_price}:{new_timestamp}", ex=REDIS_VALIDITY)
                        logging.debug(f"Updated Redis with new price for {symbol}")
                    except Exception as e:
                        logging.error(f"Failed to update Redis with new price: {e}")
                    
                    self.price_cache[symbol] = (new_price, new_timestamp)
                    self.last_update_time[symbol] = current_time
                    return new_price
                except Exception as e:
                    logging.error(f"Error fetching price for {symbol} on {exchange_name}: {str(e)}")
                    retry_count += 1
                    await asyncio.sleep(0.5 * retry_count)
                    continue
            
            except Exception as e:
                logging.error(f"Unexpected error in get_current_price: {str(e)}")
                retry_count += 1
                await asyncio.sleep(0.5 * retry_count)
        
        # 모든 시도 실패 시 긴급 캐시 사용
        if symbol in self.price_cache:
            price, timestamp = self.price_cache[symbol]
            cache_age = (current_time - datetime.fromtimestamp(timestamp, timezone.utc)).total_seconds()
            if cache_age <= EMERGENCY_CACHE_VALIDITY:
                logging.warning(f"Using emergency cache for {symbol}, age: {cache_age}s")
                return float(price)
        
        logging.error(f"All attempts to get price for {symbol} failed")
        return None
        
        
    def subscribe(self, callback):
        self.subscribers.add(callback)

    def unsubscribe(self, callback):
        self.subscribers.discard(callback)

    async def close(self):
        self.is_running = False
        for exchange in self.exchanges.values():
            await exchange.close()
        if self.redis_pool:
            await self.redis_pool.close()

async def price_update_callback(symbol, price, timestamp):
    logging.info(f"Price update: {symbol} - {price} at {datetime.fromtimestamp(timestamp, timezone.utc)}")

async def main():
    subscriber = PriceSubscriber()
    if not await subscriber.initialize():
        logging.error("Failed to initialize subscriber. Exiting.")
        return

    subscriber.subscribe(price_update_callback)
    asyncio.create_task(subscriber.listen_for_updates())

    try:
        while True:
            price = await subscriber.get_current_price('okx', 'BTC/USDT:USDT')
            logging.info(f"Current BTC price: {price}")
            await asyncio.sleep(3)  # 5초마다 가격 확인
    except KeyboardInterrupt:
        logging.info("Keyboard interrupt received. Shutting down...")
    finally:
        await subscriber.close()

# 전역 PriceSubscriber 인스턴스 생성
global_price_subscriber = PriceSubscriber()

async def initialize_global_subscriber():
    await global_price_subscriber.initialize()

async def close_global_subscriber():
    await global_price_subscriber.close()

if __name__ == "__main__":
    asyncio.run(main())