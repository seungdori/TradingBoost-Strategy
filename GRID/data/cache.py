"""
Redis caching utilities for OHLCV data and indicators

Uses async context managers for proper connection management.
"""
import json
import logging
import time
import traceback

import pandas as pd

from shared.config import settings
from shared.database.redis_patterns import redis_context, redis_pipeline, RedisTTL

# Note: All Redis operations use context managers for proper cleanup


def get_ttl_for_timeframe(timeframe: str) -> int:
    """타임프레임에 따른 TTL(Time To Live) 값을 반환합니다."""
    ttl_map = {
        '1m': 60 * 60 * 24,         # 1분 데이터는 1일 보관
        '5m': 60 * 60 * 24 * 3,      # 5분 데이터는 3일 보관
        '15m': 60 * 60 * 24 * 7,     # 15분 데이터는 7일 보관
        '30m': 60 * 60 * 24 * 14,    # 30분 데이터는 14일 보관
        '1h': 60 * 60 * 24 * 30,     # 1시간 데이터는 30일 보관
        '4h': 60 * 60 * 24 * 60,     # 4시간 데이터는 60일 보관
        '1d': 60 * 60 * 24 * 90,     # 일봉 데이터는 90일 보관
        'long': 60 * 60 * 24 * 30,   # 거래 결과는 30일 보관
        'short': 60 * 60 * 24 * 30,  # 거래 결과는 30일 보관
        'long-short': 60 * 60 * 24 * 30  # 거래 결과는 30일 보관
    }
    return ttl_map.get(timeframe, 60 * 60 * 24 * 7)


async def set_cache(exchange_name: str, symbol: str, data: pd.DataFrame, timeframe: str = '1d') -> bool:
    """
    Redis에 데이터를 저장합니다 (context manager 사용).

    Args:
        exchange_name: 거래소 이름
        symbol: 심볼
        data: 저장할 데이터프레임
        timeframe: 타임프레임

    Returns:
        bool: 저장 성공 여부
    """
    try:
        if data is None or data.empty:
            logging.warning(f"저장할 데이터가 없습니다: {exchange_name}:{symbol}:{timeframe}")
            return False

        key = f"{exchange_name}:{symbol}:{timeframe}"

        # Context manager for proper connection management
        async with redis_context() as redis_client:
            # 기존 데이터 삭제
            await redis_client.delete(key)

            # DataFrame을 레코드 리스트로 변환
            records = data.to_dict(orient='records')

            # Pipeline for batch operations
            async with redis_client.pipeline(transaction=False) as pipeline:
                for record in records:
                    if 'timestamp' in record and isinstance(record['timestamp'], pd.Timestamp):
                        record['timestamp'] = int(record['timestamp'].timestamp() * 1000)
                    pipeline.rpush(key, json.dumps(record))

                await pipeline.execute()

            # 마지막 업데이트 시간 저장
            await redis_client.set(f"{key}:last_update", int(time.time()))

            # TTL 설정
            ttl = get_ttl_for_timeframe(timeframe)
            if ttl > 0:
                await redis_client.expire(key, ttl)
                await redis_client.expire(f"{key}:last_update", ttl)

        logging.info(f"데이터 캐시 설정 완료: {key} (총 {len(records)}개 레코드)")
        return True
    except Exception as e:
        logging.error(f"캐시 설정 중 오류: {str(e)}")
        traceback.print_exc()
        return False


async def get_cache(exchange_name: str, symbol: str, timeframe: str = '1d') -> pd.DataFrame:
    """
    Redis에서 데이터를 가져옵니다 (context manager 사용).

    Args:
        exchange_name: 거래소 이름
        symbol: 심볼
        timeframe: 타임프레임

    Returns:
        pd.DataFrame: 캐시된 데이터 또는 None
    """
    try:
        key = f"{exchange_name}:{symbol}:{timeframe}"

        # Context manager for proper connection management
        async with redis_context() as redis_client:
            list_length = await redis_client.llen(key)

            if list_length == 0:
                return None

            records_json = await redis_client.lrange(key, 0, -1)
            if not records_json:
                return None

        # Parse records outside of context manager
        records = []
        for record_json in records_json:
            try:
                record = json.loads(record_json)
                records.append(record)
            except json.JSONDecodeError as e:
                logging.error(f"JSON 파싱 오류: {key} - {str(e)}")
                continue

        if not records:
            return None

        df = pd.DataFrame(records)
        if 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')

        return df
    except Exception as e:
        logging.error(f"캐시 가져오기 오류: {str(e)}")
        traceback.print_exc()
        return None


async def get_cache_range(exchange_name: str, symbol: str, timeframe: str = '1d',
                          start: int = 0, end: int = -1) -> pd.DataFrame:
    """
    Redis에서 특정 범위의 데이터를 가져옵니다 (context manager 사용).

    Args:
        exchange_name: 거래소 이름
        symbol: 심볼
        timeframe: 타임프레임
        start: 시작 인덱스
        end: 종료 인덱스

    Returns:
        pd.DataFrame: 범위 내 데이터 또는 None
    """
    try:
        key = f"{exchange_name}:{symbol}:{timeframe}"

        # Context manager for proper connection management
        async with redis_context() as redis_client:
            records_json = await redis_client.lrange(key, start, end)

        if not records_json:
            return None

        records = [json.loads(r) for r in records_json]
        df = pd.DataFrame(records)

        if 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')

        return df
    except Exception as e:
        logging.error(f"캐시 범위 가져오기 오류: {str(e)}")
        return None


async def save_ohlcv_to_redis(ohlcv_df: pd.DataFrame, exchange_name: str, symbol: str, timeframe: str) -> bool:
    """OHLCV 데이터를 Redis에 저장합니다."""
    return await set_cache(exchange_name, symbol, ohlcv_df, timeframe)


async def save_indicators_to_redis(df: pd.DataFrame, exchange_name: str, symbol: str, timeframe: str) -> bool:
    """
    지표 데이터를 Redis에 저장합니다 (context manager 사용).

    Args:
        df: 저장할 지표 데이터프레임
        exchange_name: 거래소 이름
        symbol: 심볼
        timeframe: 타임프레임

    Returns:
        bool: 저장 성공 여부
    """
    key = f"{exchange_name}:{symbol}:{timeframe}:indicators"
    try:
        # Context manager for proper connection management
        async with redis_context() as redis_client:
            await redis_client.delete(key)

            # Pipeline for batch operations
            async with redis_client.pipeline(transaction=False) as pipeline:
                records = df.to_dict(orient='records')
                for record in records:
                    if 'timestamp' in record and isinstance(record['timestamp'], pd.Timestamp):
                        record['timestamp'] = int(record['timestamp'].timestamp() * 1000)
                    pipeline.rpush(key, json.dumps(record))

                await pipeline.execute()

            await redis_client.expire(key, get_ttl_for_timeframe(timeframe))

        logging.info(f"지표 저장 완료: {key}")
        return True
    except Exception as e:
        logging.error(f"지표 저장 오류: {str(e)}")
        return False


async def get_indicators_from_redis(exchange_name: str, symbol: str, timeframe: str) -> pd.DataFrame:
    """
    Redis에서 지표 데이터를 가져옵니다 (context manager 사용).

    Args:
        exchange_name: 거래소 이름
        symbol: 심볼
        timeframe: 타임프레임

    Returns:
        pd.DataFrame: 지표 데이터 또는 None
    """
    key = f"{exchange_name}:{symbol}:{timeframe}:indicators"
    try:
        # Context manager for proper connection management
        async with redis_context() as redis_client:
            records_json = await redis_client.lrange(key, 0, -1)
            if not records_json:
                return None

        records = [json.loads(r) for r in records_json]
        df = pd.DataFrame(records)

        if 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')

        return df
    except Exception as e:
        logging.error(f"지표 가져오기 오류: {str(e)}")
        return None


async def save_grid_results_to_redis(df: pd.DataFrame, exchange_name: str, symbol: str, timeframe: str) -> bool:
    """그리드 거래 결과를 Redis에 저장합니다."""
    return await set_cache(exchange_name, symbol, df, timeframe)
