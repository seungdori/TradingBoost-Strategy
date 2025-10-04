import trace
import aiohttp
import asyncio
import aiosqlite
from redis.asyncio import Redis
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import traceback
from HYPERRSI.src.core.config import settings

class AsyncTickSizeManager:
    def __init__(self):
        self.db_path = 'tick_sizes.db'
        self.redis_client = Redis(host=settings.REDIS_HOST, port=settings.REDIS_PORT, db=settings.REDIS_DB,
                                 password=settings.REDIS_PASSWORD if settings.REDIS_PASSWORD else None)
        self.scheduler = AsyncIOScheduler()
        
    async def setup_database(self):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute('''
            CREATE TABLE IF NOT EXISTS tick_sizes (
                exchange TEXT,
                symbol TEXT,
                market_type TEXT,
                tick_size REAL,
                last_updated TIMESTAMP,
                PRIMARY KEY (exchange, symbol, market_type)
            )
            ''')
            await db.commit()
        
    async def fetch_tick_sizes(self, exchange_name):
        if exchange_name in ['binance', 'binance_spot']:
            return await self.fetch_binance_tick_sizes(exchange_name)
        elif exchange_name in ['okx', 'okx_spot']:
            return await self.fetch_okx_tick_sizes(exchange_name)
        elif exchange_name == 'upbit':
            return await self.fetch_upbit_tick_sizes()
        else:
            raise ValueError(f"Unsupported exchange: {exchange_name}")

    async def fetch_binance_tick_sizes(self, exchange_name):
        market_type = 'futures' if exchange_name == 'binance' else 'spot'
        url = 'https://api.binance.com/api/v3/exchangeInfo' if market_type == 'spot' else 'https://fapi.binance.com/fapi/v1/exchangeInfo'
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                data = await response.json()
        tick_sizes = []
        for symbol_data in data['symbols']:
            symbol = symbol_data['symbol']
            for filter in symbol_data['filters']:
                if filter['filterType'] == 'PRICE_FILTER':
                    tick_size = float(filter['tickSize'])
                    tick_sizes.append({
                        'symbol': symbol,
                        'market_type': market_type,
                        'tick_size': tick_size
                    })
                    break
        return tick_sizes

    async def fetch_okx_tick_sizes(self, exchange_name):
        market_type = 'futures' if exchange_name == 'okx' else 'spot'
        url = 'https://www.okx.com/api/v5/public/instruments'
        params = {'instType': 'SWAP' if market_type == 'futures' else 'SPOT'}
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as response:
                data = await response.json()
        tick_sizes = []
        for instrument in data['data']:
            tick_sizes.append({
                'symbol': instrument['instId'],
                'market_type': market_type,
                'tick_size': float(instrument['tickSz'])
            })
        return tick_sizes

    async def get_upbit_market_data():
        url = "https://api.upbit.com/v1/market/all"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                markets = await response.json()
    
        krw_markets = [market['market'] for market in markets if market['market'].startswith('KRW-')]
    
        async def fetch_orderbook(symbol):
            orderbook_url = f'https://api.upbit.com/v1/orderbook?markets={symbol}'
            async with aiohttp.ClientSession() as session:
                async with session.get(orderbook_url) as response:
                    orderbook_data = await response.json()
            return orderbook_data[0]

        tasks = [fetch_orderbook(krw_markets)]
        orderbooks = await asyncio.gather(*tasks)
        
        tick_sizes = []
        for market, orderbook in zip(markets, orderbooks):
            tick_size = float(orderbook['orderbook_units'][0]['ask_price']) - float(orderbook['orderbook_units'][0]['bid_price'])
            tick_sizes.append({
                'symbol': market['market'],
                'market_type': 'spot',  # Upbit only has spot market
                'tick_size': tick_size
            })
        return tick_sizes

    async def update_database(self):
        exchanges = ['binance', 'binance_spot', 'okx', 'okx_spot', 'upbit']
        tasks = [self.fetch_tick_sizes(exchange) for exchange in exchanges]
        results = await asyncio.gather(*tasks)
        
        async with aiosqlite.connect(self.db_path) as db:
            for exchange, tick_sizes in zip(exchanges, results):
                for item in tick_sizes:
                    await db.execute('''
                    INSERT OR REPLACE INTO tick_sizes 
                    (exchange, symbol, market_type, tick_size, last_updated)
                    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ''', (exchange, item['symbol'], item['market_type'], item['tick_size']))
            await db.commit()
        await self.update_cache()
        
    async def update_cache(self):
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute('SELECT * FROM tick_sizes') as cursor:
                async for row in cursor:
                    key = f"{row[0]}:{row[1]}:{row[2]}"  # exchange:symbol:market_type
                    await self.redis_client.set(key, row[3])  # tick_size
        
    async def get_tick_size(self, exchange_name, symbol, market_type=None):
        if market_type is None:
            market_type = 'futures' if exchange_name in ['binance', 'okx'] else 'spot'
        
        key = f"{exchange_name}:{symbol}:{market_type}"
        cached_value = await self.redis_client.get(key)
        if cached_value:
            return float(cached_value)
        else:
            # 캐시에 없는 경우 DB에서 조회
            async with aiosqlite.connect(self.db_path) as db:
                async with db.execute('''
                SELECT tick_size FROM tick_sizes 
                WHERE exchange = ? AND symbol = ? AND market_type = ?
                ''', (exchange_name, symbol, market_type)) as cursor:
                    result = await cursor.fetchone()
                    if result:
                        await self.redis_client.set(key, result[0])
                        return result[0]
            return None
        
    def start_scheduler(self):
        self.scheduler.add_job(self.update_database, 'interval', days=3)
        self.scheduler.start()
        
    def stop_scheduler(self):
        self.scheduler.shutdown()
        
async def main():
    try:
        manager = AsyncTickSizeManager()
        await manager.setup_database()
        await manager.update_database()  # 초기 데이터 로드
        manager.start_scheduler()

        # 사용 예시
        print(await manager.get_tick_size('binance', 'BTCUSDT'))
        print(await manager.get_tick_size('binance_spot', 'BTCUSDT'))
        print(await manager.get_tick_size('okx', 'BTC-USDT-SWAP'))
        print(await manager.get_tick_size('okx_spot', 'BTC-USDT'))
        print(await manager.get_tick_size('upbit', 'KRW-BTC'))

        await manager.redis_client.close()
    except Exception as e:
        print(f"An error occurred81: {e}")
        print(traceback.format_exc())

if __name__ == "__main__":
    asyncio.run(main())