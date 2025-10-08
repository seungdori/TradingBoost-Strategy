"""Upbit 거래소 핸들러 (통합 헬퍼 사용)

이 파일은 shared.exchange.helpers를 사용하도록 업데이트되었습니다.
"""
import asyncio
import json
import random
import traceback
from redis.asyncio import Redis

from shared.exchange.helpers.balance_helper import process_upbit_balance
from shared.exchange.helpers.cache_helper import get_cached_data, set_cached_data


async def handle_upbit(
    exchange,
    symbol: str,
    user_id: str,
    redis: Redis,
    cache_key: str
) -> float:
    """
    Upbit 잔고를 조회합니다 (Redis 캐싱 지원)

    Args:
        exchange: 거래소 인스턴스
        symbol: 심볼
        user_id: 사용자 ID
        redis: Redis 클라이언트
        cache_key: 캐시 키

    Returns:
        float: 잔고
    """
    max_retries = 3
    retry_delay = 2

    try:
        # 캐시된 잔고 데이터 조회
        cached_data = await get_cached_data(redis, cache_key)
        if cached_data:
            print("Using cached balance data for Upbit")
            return process_upbit_balance(cached_data, symbol)

        # 캐시 미스 - API 호출
        for attempt in range(max_retries):
            try:
                await asyncio.sleep(random.random())
                balance = await exchange.fetch_balance()

                # 캐시에 저장
                await set_cached_data(redis, cache_key, balance, ttl=300)

                return process_upbit_balance(balance, symbol)
            except Exception as e:
                print(f"An error occurred in handle_upbit: {e}")
                print(traceback.format_exc())
                if 'too many requests' in str(e).lower() and attempt < max_retries - 1:
                    print(f"Retrying in {retry_delay} seconds...")
                    await asyncio.sleep(retry_delay)
                else:
                    return 0.0

    except Exception as e:
        print(f"Unexpected error in handle_upbit: {e}")
        print(traceback.format_exc())
        return 0.0
