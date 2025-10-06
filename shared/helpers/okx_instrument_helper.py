"""
OKX 영구 선물 계약 정보 조회 유틸리티

OKX Perpetual Swap (USDT-SWAP) 계약 정보를 조회하고 처리하는 기능 제공
"""
import json
import aiohttp
import math
import traceback
from typing import Optional, Dict, Tuple

from shared.utils.redis_utils import set_redis_data, get_redis_data


async def get_perpetual_instruments(redis_client) -> Optional[list]:
    """
    OKX 영구 선물 계약 정보를 가져옵니다 (Redis 캐시 사용)

    Args:
        redis_client: Redis 클라이언트 인스턴스

    Returns:
        list: 계약 정보 목록 또는 실패 시 None
    """
    try:
        # Redis에서 데이터 확인
        cached_data = await get_redis_data(redis_client, 'perpetual_instruments')
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

        # 데이터를 Redis에 저장 (40시간 = 144000초)
        if data and 'data' in data:
            await set_redis_data(redis_client, 'perpetual_instruments', data['data'], expiry=144000)
            return data['data']
        else:
            print("Invalid response from OKX API")
            return None

    except Exception as e:
        traceback.print_exc()
        print(f"Error in get_perpetual_instruments: {str(e)}")
        return None


def get_lot_sizes(instruments: list) -> Dict[str, Tuple[float, float, str]]:
    """
    종목별 계약 단위 정보를 정리합니다

    Args:
        instruments: OKX 계약 정보 목록

    Returns:
        dict: {symbol: (lot_size, contract_value, base_currency)}
    """
    lot_sizes = {}
    for instrument in instruments:
        symbol = instrument['instId']
        lot_size = float(instrument['lotSz'])
        contract_value = float(instrument['ctVal'])
        base_currency = symbol.split('-')[0]
        lot_sizes[symbol] = (lot_size, contract_value, base_currency)
    return lot_sizes


async def get_symbol_info(redis_client, symbol: str) -> Optional[dict]:
    """
    주문 심볼 정보를 Redis에서 조회합니다

    Args:
        redis_client: Redis 클라이언트 인스턴스
        symbol: 조회할 심볼

    Returns:
        dict: 심볼 정보 또는 None
    """
    all_info_key = f"symbol_info:contract_specifications"
    all_info = await redis_client.get(all_info_key)
    if not all_info:
        return None
    all_info = json.loads(all_info)

    symbol_info = all_info.get(symbol)
    if not symbol_info:
        return None

    return symbol_info


async def round_to_qty(symbol: str, qty: float, lot_sizes: Dict[str, Tuple[float, float, str]]) -> int:
    """
    실제 수량을 계약 수로 변환합니다 (내림)

    Args:
        symbol: 심볼 (예: 'BTC-USDT-SWAP')
        qty: 실제 수량 (예: 0.02 BTC)
        lot_sizes: get_lot_sizes()로 얻은 계약 정보

    Returns:
        int: 계약 수 (내림)

    Raises:
        ValueError: 유효하지 않은 심볼
    """
    if symbol not in lot_sizes:
        raise ValueError(f"{symbol} is not a valid Perpetual instrument.")
    if not symbol.endswith('-USDT-SWAP'):
        raise ValueError(f"{symbol} is not a USDT-SWAP instrument.")

    lot_size, contract_value, _ = lot_sizes[symbol]

    # qty는 실제 수량(예: 0.02 BTC)
    # contract_value는 한 계약당 기초자산의 양(예: BTC의 경우 0.01 BTC)
    contracts = qty / contract_value  # 계약 수 계산
    rounded_contracts = math.floor(contracts)  # 계약 수 내림

    print(f"입력 수량: {qty}")
    print(f"계약 가치: {contract_value}")
    print(f"계산된 계약 수: {contracts}")
    print(f"반올림된 계약 수: {rounded_contracts}")

    return rounded_contracts


async def contracts_to_qty(redis_client, symbol: str, contracts: int) -> Optional[float]:
    """
    계약 수를 실제 수량으로 변환합니다

    Args:
        redis_client: Redis 클라이언트 인스턴스
        symbol: 심볼 (예: 'BTC-USDT-SWAP')
        contracts: 계약 수

    Returns:
        float: 실제 수량 또는 None
    """
    try:
        perpetual_instruments = await get_perpetual_instruments(redis_client)
        lot_sizes = get_lot_sizes(perpetual_instruments)
        if not symbol.endswith('-USDT-SWAP'):
            raise ValueError(f"{symbol} is not a USDT-SWAP instrument.")
        lot_size, contract_value, _ = lot_sizes[symbol]
        qty = contracts * contract_value  # 계약 수에 계약 가치를 곱해서 실제 수량 계산
        return qty
    except Exception as e:
        traceback.print_exc()
        print(f"Error in contracts_to_qty: {str(e)}")
        return None


def split_contracts(total_contracts: int) -> Tuple[int, int, int]:
    """
    계약 수를 30%, 30%, 40%로 분할합니다

    Args:
        total_contracts: 총 계약 수

    Returns:
        tuple: (qty1, qty2, qty3) - 30%, 30%, 40% 분할
    """
    qty1 = math.floor(total_contracts * 0.3)
    print(f"qty1: {qty1}")
    qty2 = math.ceil(total_contracts * 0.3)
    print(f"qty2: {qty2}")
    qty3 = total_contracts - (qty1 + qty2)
    print(f"qty3: {qty3}")
    return qty1, qty2, qty3


# 테스트 함수
async def testing(redis_client):
    """
    OKX 영구 선물 계약 정보 조회 테스트 함수
    """
    try:
        perpetual_instruments = await get_perpetual_instruments(redis_client)
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

        total_contracts = await round_to_qty(symbol, qty, lot_sizes)
        print(f"total_contracts: {total_contracts}")

        position_qty = await contracts_to_qty(redis_client, symbol, total_contracts)
        print(f"position_qty: {position_qty}")

        qty1, qty2, qty3 = split_contracts(total_contracts)
        print(f"{symbol}에 대해 {qty}개의 포지션 크기는 {total_contracts}계약으로 변환됩니다.")
        print(f"{total_contracts}개의 계약은 {position_qty}의 {symbol}로 변환됩니다.")
        print(f"분할 결과: qty1={qty1}, qty2={qty2}, qty3={qty3}")
    except Exception as e:
        traceback.print_exc()
        print(f"Error in testing: {str(e)}")


if __name__ == "__main__":
    import asyncio
    # Testing requires redis_client setup
    print("This module requires redis_client to be passed as parameter")
