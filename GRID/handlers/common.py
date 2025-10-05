"""공통 거래소 핸들러"""

import asyncio
import json
import random
import traceback


def process_other_exchange_position(positions, symbol):
    """
    기타 거래소(Binance, Bitget 등)의 포지션 데이터를 처리합니다.

    Args:
        positions: 포지션 데이터 리스트
        symbol: 심볼

    Returns:
        float: 포지션 수량
    """
    for position in positions:
        if position.get('symbol') == symbol:
            quantity = float(position.get('contracts', 0))
            return quantity
    return 0.0


async def handle_other_exchanges(exchange, symbol, user_id, redis, cache_key):
    """
    기타 거래소의 포지션을 조회합니다. (Redis 캐싱 지원)

    Args:
        exchange: 거래소 인스턴스
        symbol: 심볼
        user_id: 사용자 ID
        redis: Redis 클라이언트
        cache_key: 캐시 키

    Returns:
        float: 포지션 수량
    """
    max_retries = 3
    retry_delay = 2  # seconds
    quantity = 0.0

    try:
        # Try to get cached position data
        await asyncio.sleep(random.random())
        cached_data = await redis.get(cache_key)
        if cached_data:
            positions = json.loads(cached_data)
            print("Using cached position data for other exchange")
            return process_other_exchange_position(positions, symbol)

        # If no valid cache, proceed with API call
        for attempt in range(max_retries):
            try:
                positions = await exchange.fetch_positions([symbol])

                # Cache the position data with TTL
                await redis.set(cache_key, json.dumps(positions), ex=300)  # 5분 캐시

                quantity = process_other_exchange_position(positions, symbol)
                await asyncio.sleep(random.random() + 0.4)
                break  # Exit the loop if no exception occurs

            except Exception as e:
                print(f"An error occurred in handle_other_exchanges: {e}")
                print(traceback.format_exc())
                if 'too many requests' in str(e).lower() and attempt < max_retries - 1:
                    print(f"Retrying in {retry_delay} seconds...")
                    await asyncio.sleep(retry_delay)
                else:
                    return 0.0

    except Exception as e:
        print(f"Unexpected error in handle_other_exchanges: {e}")
        print(traceback.format_exc())
        return 0.0

    return quantity
