"""
Data fetching utilities for OHLCV data
"""
import asyncio
import json
import logging
import traceback
from typing import Any

import pandas as pd

from GRID.data.cache import get_cache, set_cache
from shared.database.redis_patterns import redis_context
from shared.utils import retry_decorator


async def get_last_timestamp(exchange_name: str, symbol: str, timeframe: str) -> int | None:
    """Redis에서 마지막 타임스탬프를 가져옵니다."""
    try:
        key = f"{exchange_name}:{symbol}:{timeframe}"

        async with redis_context() as redis_client:
            list_length = await redis_client.llen(key)

            if list_length == 0:
                return None

            last_record_json = await redis_client.lindex(key, -1)
            if last_record_json:
                last_record = json.loads(last_record_json)
                if 'timestamp' in last_record:
                    timestamp: int = last_record['timestamp']
                    return timestamp

        return None
    except Exception as e:
        logging.error(f"마지막 타임스탬프 가져오기 오류: {str(e)}")
        return None


@retry_decorator(max_retries=5, delay=3)
async def fetch_ohlcvs(exchange_instance: Any, symbol: str, timeframe: str, since: int, limit: int) -> list[list[Any]]:
    """거래소에서 OHLCV 데이터를 가져옵니다."""
    try:
        ohlcv: list[list[Any]] = await exchange_instance.fetch_ohlcv(
            symbol,
            timeframe=timeframe,
            since=since,
            limit=limit
        )
        return ohlcv
    except Exception as e:
        logging.error(f"OHLCV 가져오기 실패: {symbol} {timeframe} - {str(e)}")
        raise


async def fetch_all_ohlcvs(exchange_name: str, exchange_instance: Any, symbol: str, timeframe: str,
                           last_timestamp: int, user_id: int, max_retries: int = 3) -> pd.DataFrame:
    """모든 OHLCV 데이터를 페이지네이션으로 가져옵니다."""
    all_ohlcv = []
    since = last_timestamp

    try:
        while True:
            ohlcv = await fetch_ohlcvs(exchange_instance, symbol, timeframe, since, 1000)

            if not ohlcv:
                break

            all_ohlcv.extend(ohlcv)

            if len(ohlcv) < 1000:
                break

            since = ohlcv[-1][0] + 1

            await asyncio.sleep(0.1)

        if all_ohlcv:
            df = pd.DataFrame(all_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            return df

        return pd.DataFrame()

    except Exception as e:
        logging.error(f"fetch_all_ohlcvs 오류: {symbol} - {str(e)}")
        traceback.print_exc()
        return pd.DataFrame()


async def fetching_data(exchange_instance: Any, exchange_name: str, symbol: str, user_id: int, force_refetch: bool = False) -> tuple[pd.DataFrame | None, pd.DataFrame | None]:
    """데이터를 가져오고 캐시합니다."""
    try:
        timeframes = ['15m', '4h']
        data_dict = {}

        for tf in timeframes:
            cached_data = await get_cache(exchange_name, symbol, tf)

            if cached_data is not None and not force_refetch:
                data_dict[tf] = cached_data
                continue

            last_timestamp = await get_last_timestamp(exchange_name, symbol, tf)
            if last_timestamp is None:
                last_timestamp = int(pd.Timestamp.now().timestamp() * 1000) - (90 * 24 * 60 * 60 * 1000)

            new_data = await fetch_all_ohlcvs(exchange_name, exchange_instance, symbol, tf, last_timestamp, user_id)

            if not new_data.empty:
                await set_cache(exchange_name, symbol, new_data, tf)
                data_dict[tf] = new_data

        return data_dict.get('15m'), data_dict.get('4h')

    except Exception as e:
        logging.error(f"데이터 페칭 오류: {exchange_name}:{symbol} - {str(e)}")
        return None, None


async def fetch_symbol_data(exchange_instance: Any, symbol: str, timeframes: list[str], semaphore: asyncio.Semaphore, exchange_name: str, user_id: int, force_refetch: bool = False) -> None:
    """심볼별 데이터를 가져옵니다."""
    async with semaphore:
        try:
            await fetching_data(exchange_instance, exchange_name, symbol, user_id, force_refetch)
        except Exception as e:
            logging.error(f"심볼 데이터 페칭 오류: {symbol} - {str(e)}")
