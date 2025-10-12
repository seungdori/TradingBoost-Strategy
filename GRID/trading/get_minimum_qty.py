import json
import math
import os
import traceback

import aiohttp
import redis.asyncio as redis

from shared.config import settings


# Redis 클라이언트 생성
async def get_redis_client():
    if settings.REDIS_PASSWORD:
        return redis.from_url(
            f"redis://:{settings.REDIS_PASSWORD}@{settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB}",
            encoding='utf-8',
            decode_responses=True
        )
    else:
        return redis.from_url(
            f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB}",
            encoding='utf-8',
            decode_responses=True
        )

# Redis에 데이터 저장 함수
async def set_redis_data(key, data, expiry=144000):  # 기본 만료 시간 1시간
    redis_client = await get_redis_client()
    await redis_client.set(key, json.dumps(data), ex=expiry)
    await redis_client.aclose()

# Redis에서 데이터 가져오는 함수
async def get_redis_data(key):
    redis_client = await get_redis_client()
    data = await redis_client.get(key)
    await redis_client.aclose()
    return json.loads(data) if data else None

# Perpetual 종목 정보를 가져오는 함수
async def get_perpetual_instruments():
    try:
        # Redis에서 데이터 확인
        cached_data = await get_redis_data('perpetual_instruments')
        if cached_data:
            return cached_data

        # 캐시된 데이터가 없으면 API 호출
        base_url = "https://www.okx.com"
        # SSL 검증을 비활성화하는 옵션 추가
        conn = aiohttp.TCPConnector(ssl=False)
        async with aiohttp.ClientSession(connector=conn) as session:
            url = f"{base_url}/api/v5/public/instruments?instType=SWAP"
            async with session.get(url) as response:
                data = await response.json()
                print(data)
                
        # 데이터를 Redis에 저장
        if data and 'data' in data:
            await set_redis_data('perpetual_instruments', data['data'])
            return data['data']
        else:
            print("Invalid response from OKX API")
            return None
            
    except Exception as e:
        traceback.print_exc()
        print(f"Error in get_perpetual_instruments: {str(e)}")
        return None

# 종목별 계약 단위 정보를 정리하는 함수
def get_lot_sizes(instruments):
    lot_sizes = {}
    for instrument in instruments:
        symbol = instrument['instId']
        lot_size = float(instrument['lotSz'])
        contract_value = float(instrument['ctVal'])
        base_currency = symbol.split('-')[0]
        lot_sizes[symbol] = (lot_size, contract_value, base_currency)
    return lot_sizes

# 수량을 최소 주문 단위에 맞게 변환하는 함수
def round_to_qty(symbol, qty, lot_sizes):
    if symbol not in lot_sizes:
        raise ValueError(f"{symbol} is not a valid Perpetual instrument.")
    if not symbol.endswith('-USDT-SWAP'):
        raise ValueError(f"{symbol} is not a USDT-SWAP instrument.")
    lot_size, contract_value, _ = lot_sizes[symbol]
    contracts = qty / contract_value
    rounded_contracts = math.floor(contracts)
    rounded_qty = rounded_contracts * lot_size #<-- 실제 주문가능한 수량
    return rounded_contracts

# 계약 수를 30%, 30%, 40%로 분할하고 최소 계약 단위로 내림하는 함수
def split_contracts(total_contracts):
    qty1 = math.floor(total_contracts * 0.3)
    print(f"qty1: {qty1}")
    qty2 = math.ceil(total_contracts * 0.3)
    print(f"qty2: {qty2}")
    qty3 = total_contracts - (qty1 + qty2)
    print(f"qty3: {qty3}")
    return qty1, qty2, qty3

async def testing():
    try:
        perpetual_instruments = await get_perpetual_instruments()
        if not perpetual_instruments:
            print("Failed to get perpetual instruments")
            return
            
        lot_sizes = get_lot_sizes(perpetual_instruments)
        
        print("USDT-SWAP Lot Sizes:")
        for symbol, (lot_size, contract_value, base_currency) in lot_sizes.items():
            if symbol.endswith('-USDT-SWAP'):
                print(f"{symbol}: {lot_size}({contract_value} {base_currency})")

        symbol = "BTC-USDT-SWAP"
        qty = 0.02

        total_contracts = round_to_qty(symbol, qty, lot_sizes)
        qty1, qty2, qty3 = split_contracts(total_contracts)
        print(f"{symbol}에 대해 {qty}개의 포지션 크기는 {total_contracts}계약으로 변환됩니다.")
        print(f"분할 결과: qty1={qty1}, qty2={qty2}, qty3={qty3}")
    except Exception as e:
        traceback.print_exc()
        print(f"Error in testing: {str(e)}")

if __name__ == "__main__":
    import asyncio
    asyncio.run(testing())