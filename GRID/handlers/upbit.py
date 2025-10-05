"""Upbit 거래소 전용 핸들러"""

import asyncio
import json
import random
import traceback


def process_upbit_balance(balance, symbol):
    """
    Upbit 잔고 데이터를 처리합니다.

    Args:
        balance: 잔고 데이터
        symbol: 심볼 (예: 'KRW-BTC')

    Returns:
        float: 사용 가능 잔고
    """
    base_currency = symbol.split('-')[1]  # 'KRW-ETC'에서 'ETC'를 추출
    free_balance = balance['free'].get(base_currency, 0.0)  # 사용 가능 잔고 추출
    print(f'{symbol}의 balance: {free_balance}')
    return free_balance


async def handle_upbit(exchange, symbol, user_id, redis, cache_key):
    """
    Upbit 잔고를 조회합니다. (Redis 캐싱 지원)

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
    retry_delay = 2  # seconds

    try:
        # Try to get cached balance data
        cached_data = await redis.get(cache_key)
        if cached_data:
            balance = json.loads(cached_data)
            print("Using cached balance data for Upbit")
            return process_upbit_balance(balance, symbol)

        # If no valid cache, proceed with API call
        for attempt in range(max_retries):
            try:
                await asyncio.sleep(random.random())
                balance = await exchange.fetch_balance()

                # Cache the balance data with TTL
                await redis.set(cache_key, json.dumps(balance), ex=300)  # 5분 캐시

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
