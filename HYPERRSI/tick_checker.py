"""
Tick Size Manager - PostgreSQL Version

Manages tick size data for multiple exchanges using PostgreSQL and Redis cache.
"""

import asyncio
import traceback

import aiohttp
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from redis.asyncio import Redis
from sqlalchemy import and_, select
from sqlalchemy.dialects.postgresql import insert

from HYPERRSI.src.core.config import settings
from shared.database.session import get_transactional_db
from HYPERRSI.src.core.models.database import TickSizeModel
from shared.logging import get_logger

logger = get_logger(__name__)


class AsyncTickSizeManager:
    def __init__(self):
        self.redis_client = Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            db=settings.REDIS_DB,
            password=settings.REDIS_PASSWORD if settings.REDIS_PASSWORD else None
        )
        self.scheduler = AsyncIOScheduler()

    async def fetch_tick_sizes(self, exchange_name):
        """Fetch tick sizes from specific exchange"""
        if exchange_name in ['binance', 'binance_spot']:
            return await self.fetch_binance_tick_sizes(exchange_name)
        elif exchange_name in ['okx', 'okx_spot']:
            return await self.fetch_okx_tick_sizes(exchange_name)
        elif exchange_name == 'upbit':
            return await self.fetch_upbit_tick_sizes()
        else:
            raise ValueError(f"Unsupported exchange: {exchange_name}")

    async def fetch_binance_tick_sizes(self, exchange_name):
        """Fetch Binance tick sizes"""
        market_type = 'futures' if exchange_name == 'binance' else 'spot'
        url = (
            'https://api.binance.com/api/v3/exchangeInfo'
            if market_type == 'spot'
            else 'https://fapi.binance.com/fapi/v1/exchangeInfo'
        )

        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                data = await response.json()

        tick_sizes = []
        for symbol_data in data['symbols']:
            symbol = symbol_data['symbol']
            for filter_item in symbol_data['filters']:
                if filter_item['filterType'] == 'PRICE_FILTER':
                    tick_size = float(filter_item['tickSize'])
                    tick_sizes.append({
                        'symbol': symbol,
                        'market_type': market_type,
                        'tick_size': tick_size
                    })
                    break
        return tick_sizes

    async def fetch_okx_tick_sizes(self, exchange_name):
        """Fetch OKX tick sizes"""
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

    async def fetch_upbit_tick_sizes(self):
        """Fetch Upbit tick sizes"""
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

        tasks = [fetch_orderbook(market) for market in krw_markets]
        orderbooks = await asyncio.gather(*tasks)

        tick_sizes = []
        for market_data, orderbook in zip([m for m in markets if m['market'].startswith('KRW-')], orderbooks):
            tick_size = (
                float(orderbook['orderbook_units'][0]['ask_price']) -
                float(orderbook['orderbook_units'][0]['bid_price'])
            )
            tick_sizes.append({
                'symbol': market_data['market'],
                'market_type': 'spot',  # Upbit only has spot market
                'tick_size': tick_size
            })
        return tick_sizes

    async def update_database(self):
        """Fetch and update tick sizes in PostgreSQL"""
        exchanges = ['binance', 'binance_spot', 'okx', 'okx_spot', 'upbit']
        tasks = [self.fetch_tick_sizes(exchange) for exchange in exchanges]
        results = await asyncio.gather(*tasks)

        async with get_transactional_db() as session:
            for exchange, tick_sizes in zip(exchanges, results):
                for item in tick_sizes:
                    # Upsert using PostgreSQL INSERT ... ON CONFLICT
                    stmt = insert(TickSizeModel).values(
                        exchange=exchange,
                        symbol=item['symbol'],
                        market_type=item['market_type'],
                        tick_size=item['tick_size']
                    )
                    # Update if exists based on unique combination
                    stmt = stmt.on_conflict_do_update(
                        index_elements=['exchange', 'symbol', 'market_type'],
                        set_={
                            'tick_size': stmt.excluded.tick_size,
                            'last_updated': stmt.excluded.last_updated
                        }
                    )
                    await session.execute(stmt)

            await session.commit()

        await self.update_cache()
        logger.info(f"✅ Updated tick sizes for {len(exchanges)} exchanges")

    async def update_cache(self):
        """Update Redis cache from PostgreSQL"""
        async with get_transactional_db() as session:
            result = await session.execute(select(TickSizeModel))
            tick_sizes = result.scalars().all()

            for tick in tick_sizes:
                key = f"{tick.exchange}:{tick.symbol}:{tick.market_type}"
                await self.redis_client.set(key, str(tick.tick_size))

        logger.info("✅ Updated Redis cache with tick sizes")

    async def get_tick_size(self, exchange_name: str, symbol: str, market_type: str = None) -> float:
        """Get tick size from cache or database"""
        if market_type is None:
            market_type = 'futures' if exchange_name in ['binance', 'okx'] else 'spot'

        key = f"{exchange_name}:{symbol}:{market_type}"
        cached_value = await self.redis_client.get(key)

        if cached_value:
            return float(cached_value)
        else:
            # Cache miss - fetch from database
            async with get_transactional_db() as session:
                result = await session.execute(
                    select(TickSizeModel).where(
                        and_(
                            TickSizeModel.exchange == exchange_name,
                            TickSizeModel.symbol == symbol,
                            TickSizeModel.market_type == market_type
                        )
                    )
                )
                tick = result.scalar_one_or_none()

                if tick:
                    # Update cache
                    await self.redis_client.set(key, str(tick.tick_size))
                    return tick.tick_size

        return None

    def start_scheduler(self):
        """Start periodic update scheduler (every 3 days)"""
        self.scheduler.add_job(self.update_database, 'interval', days=3)
        self.scheduler.start()
        logger.info("✅ Scheduler started - updates every 3 days")

    def stop_scheduler(self):
        """Stop scheduler"""
        self.scheduler.shutdown()
        logger.info("Scheduler stopped")


async def main():
    """Test tick size manager"""
    try:
        manager = AsyncTickSizeManager()
        await manager.update_database()  # Initial data load
        manager.start_scheduler()

        # Usage examples
        btc_binance = await manager.get_tick_size('binance', 'BTCUSDT')
        btc_binance_spot = await manager.get_tick_size('binance_spot', 'BTCUSDT')
        btc_okx = await manager.get_tick_size('okx', 'BTC-USDT-SWAP')
        btc_okx_spot = await manager.get_tick_size('okx_spot', 'BTC-USDT')
        btc_upbit = await manager.get_tick_size('upbit', 'KRW-BTC')

        logger.info(f"Binance BTCUSDT (futures): {btc_binance}")
        logger.info(f"Binance BTCUSDT (spot): {btc_binance_spot}")
        logger.info(f"OKX BTC-USDT-SWAP: {btc_okx}")
        logger.info(f"OKX BTC-USDT (spot): {btc_okx_spot}")
        logger.info(f"Upbit KRW-BTC: {btc_upbit}")

        await manager.redis_client.close()

    except Exception as e:
        logger.error(f"An error occurred: {e}")
        logger.error(traceback.format_exc())


if __name__ == "__main__":
    asyncio.run(main())
