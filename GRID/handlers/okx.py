"""GRID OKX 핸들러 (하위 호환성)

이 파일은 하위 호환성을 위해 유지되며, shared.exchange를 재export합니다.
"""
import asyncio
import json
import random
from typing import Optional

from redis.asyncio import Redis

from shared.exchange.helpers.cache_helper import get_cached_data
from shared.exchange.helpers.position_helper import process_position_data
from shared.exchange.okx.client import OKXClient


async def handle_okx(
    exchange,
    symbol: str,
    user_id: str,
    redis: Redis,
    cache_key: str
) -> float:
    """
    OKX 포지션을 조회합니다 (Redis 캐싱 지원)

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
    retry_delay = 2

    try:
        # 캐시된 포지션 데이터 조회
        await asyncio.sleep(random.random())
        cached_data = await get_cached_data(redis, cache_key)

        if cached_data:
            print("Using cached position data for OKX")
            return process_position_data(cached_data, symbol)

        # 캐시 미스 - API 호출
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

                    # 캐시에 저장
                    await redis.set(cache_key, json.dumps(positions_data), ex=300)

                    quantity = process_position_data(positions_data, symbol)
                    await asyncio.sleep(random.random() + 0.4)

                break
            except Exception as e:
                print(f"An error occurred in handle_okx: {e}")
                if 'too many requests' in str(e).lower() and attempt < max_retries - 1:
                    print(f"Retrying in {retry_delay} seconds...")
                    await asyncio.sleep(retry_delay)
                else:
                    return 0.0

    except Exception as e:
        print(f"Unexpected error in handle_okx: {e}")
        return 0.0

    return quantity


# 기존 함수 유지 (하위 호환성)
process_okx_position_data = process_position_data
