"""OKX 거래소 전용 핸들러"""

import asyncio
import json
import random
import traceback


def process_okx_position_data(positions_data, symbol):
    """
    OKX 포지션 데이터를 처리합니다.

    Args:
        positions_data: 포지션 데이터
        symbol: 심볼

    Returns:
        float: 포지션 수량
    """
    # Redis에서 가져온 데이터 처리
    if isinstance(positions_data, list):
        for position in positions_data:
            if position.get('instId') == symbol:
                quantity = float(position.get('pos', '0'))
                return quantity

    # 웹소켓에서 받은 데이터 처리
    elif isinstance(positions_data, dict) and 'data' in positions_data:
        for position in positions_data['data']:
            if position.get('instId') == symbol:
                quantity = float(position.get('pos', '0'))
                return quantity

    # 예상치 못한 데이터 구조
    else:
        print(f"Unexpected data structure: {type(positions_data)}")
        print(f"Data: {positions_data}")

    return 0.0


async def handle_okx(exchange, symbol, user_id, redis, cache_key):
    """
    OKX 포지션을 조회합니다. (Redis 캐싱 지원)

    Args:
        exchange: 거래소 인스턴스
        symbol: 심볼
        user_id: 사용자 ID
        redis: Redis 클라이언트
        cache_key: 캐시 키

    Returns:
        float: 포지션 수량
    """
    market_type = exchange.options.get('defaultType', 'No market type set')
    quantity = 0.0
    max_retries = 3
    retry_delay = 2  # seconds

    try:
        # Try to get cached position data
        await asyncio.sleep(random.random())
        cached_data = await redis.get(cache_key)
        if cached_data:
            positions_data = json.loads(cached_data)
            print("Using cached position data for OKX")
            return process_okx_position_data(positions_data, symbol)

        # If no valid cache, proceed with API call
        for attempt in range(max_retries):
            try:
                if market_type == 'spot':
                    await asyncio.sleep(random.random())
                    balance_data = await exchange.fetch_balance()
                    base_currency = symbol.split('-')[0]
                    if base_currency in balance_data:
                        quantity = float(balance_data[base_currency]['free'])
                        print(f"{symbol}의 type : {type(quantity)}, {symbol}position value : {quantity}")
                else:
                    positions_data = await exchange.private_get_account_positions()

                    # Cache the position data with TTL
                    await redis.set(cache_key, json.dumps(positions_data), ex=300)  # 5분 캐시

                    quantity = process_okx_position_data(positions_data, symbol)
                    await asyncio.sleep(random.random() + 0.4)

                break  # Exit the loop if no exception occurs
            except Exception as e:
                print(f"An error occurred in handle_okx: {e}")
                print(traceback.format_exc())
                if 'too many requests' in str(e).lower() and attempt < max_retries - 1:
                    print(f"Retrying in {retry_delay} seconds...")
                    await asyncio.sleep(retry_delay)
                else:
                    return 0.0

    except Exception as e:
        print(f"Unexpected error in handle_okx: {e}")
        print(traceback.format_exc())
        return 0.0

    return quantity
