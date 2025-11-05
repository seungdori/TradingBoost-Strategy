from shared.database.redis_patterns import redis_context, RedisTTL
import asyncio
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone

import ccxt.pro as ccxt

from shared.config import settings

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class CentralizedPriceManager:
    def __init__(self, exchange_id='okx'):
        self.exchange = getattr(ccxt, exchange_id)({
            'options': {
                'defaultType': 'future'
            }
        })
        self.redis = None
        self.symbols = []
        self.tasks = []
        self.max_retries = 5
        self.retry_delay = 5

    async def initialize(self):
        """Initialize Redis connection using shared connection pool"""
        retry_count = 0
        while retry_count < self.max_retries:
            try:
                async with redis_context() as redis:
                    self.symbols = await self.exchange.load_markets()
                    self.symbols = [symbol for symbol in self.symbols if symbol.endswith('USDT:USDT')]
                    logging.info(f"Initialized with {len(self.symbols)} symbols")
                    return
            except Exception as e:
                retry_count += 1
                logging.error(f"Initialization error (attempt {retry_count}/{self.max_retries}): {e}")
                if retry_count >= self.max_retries:
                    raise
                await asyncio.sleep(self.retry_delay)

    async def start(self):
        await self.initialize()
        logging.info("Starting to watch tickers...")
        self.tasks = [self.watch_ticker(symbol) for symbol in self.symbols]
        await asyncio.gather(*self.tasks)

    async def watch_ticker(self, symbol):
        last_update_time = 0
        update_interval = 2  # 5초 간격으로 업데이트
        consecutive_errors = 0
        max_consecutive_errors = 10

        while True:
            try:
                ticker = await self.exchange.watch_ticker(symbol)
                if consecutive_errors != 0:
                    logging.info(f"Reconnected {symbol} ticker successfully in {consecutive_errors} attempts")
                current_time = time.time()
                if current_time - last_update_time >= update_interval:
                    last_price = ticker['last']
                    server_time = ticker.get('timestamp', None)
                    utc_time = datetime.fromtimestamp(server_time / 1000, timezone.utc)
                    kst_time = utc_time + timedelta(hours=9)
                    await self.redis.set(f"price:{symbol}", f"{last_price}:{kst_time.timestamp()}") # type: ignore[union-attr]
                    await self.redis.publish( # type: ignore[union-attr]
                        "price_update",
                        json.dumps({"symbol": symbol, "price": last_price, "timestamp": kst_time.timestamp()})
                    )
                    last_update_time = current_time # type: ignore[assignment]
                    consecutive_errors = 0  # 성공적인 업데이트 후 오류 카운트 리셋
            except Exception as e:
                consecutive_errors += 1
                logging.error(f"Error in watch_ticker for {symbol} (consecutive errors: {consecutive_errors}): {e}")
                if consecutive_errors >= max_consecutive_errors:
                    logging.critical(f"Too many consecutive errors for {symbol}. Restarting the ticker.")
                    break  # 이 break는 while 루프를 빠져나가 티커를 재시작하게 함
                await asyncio.sleep(self.retry_delay)
            await asyncio.sleep(0.3)  # 짧은 대기 시간으로 CPU 사용량 감소

    async def cleanup(self):
        logging.info("Cleaning up...")
        for task in self.tasks:
            task.cancel()
        await self.exchange.close()
        if self.redis:
            await self.redis.close()
        logging.info("Cleanup completed")


async def main():
    retry_count = 0
    max_retries = 3
    retry_delay = 10

    while True:
        try:
            manager = CentralizedPriceManager()
            logging.info("Starting CentralizedPriceManager")
            await manager.start()
        except KeyboardInterrupt:
            logging.info("Received KeyboardInterrupt. Shutting down...")
            await manager.cleanup()
            break
        except Exception as e:
            retry_count += 1
            logging.error(f"Unexpected error (attempt {retry_count}/{max_retries}): {e}")
            if retry_count >= max_retries:
                logging.critical("Max retries reached. Shutting down...")
                break
            await asyncio.sleep(retry_delay)
        finally:
            await manager.cleanup()

if __name__ == "__main__":
    asyncio.run(main())