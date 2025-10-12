"""
Exchange symbol fetching utilities
"""
import ssl
from typing import Any

import aiohttp

from GRID.trading.instance_manager import get_exchange_instance


async def get_all_okx_usdt_swap_symbols():
    """OKX 거래소의 모든 USDT 선물 마켓 종목과 거래량을 비동기적으로 가져오는 함수"""
    # OKX 선물 API 엔드포인트
    url = "https://www.okx.com/api/v5/market/tickers?instType=SWAP"

    # SSL 검증 비활성화
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE

    async with aiohttp.ClientSession() as session:
        async with session.get(url, ssl=ssl_context) as response:
            data = await response.json()

        # OKX에서의 응답 데이터 구조에 맞게 파싱
        usdt_symbols_data = []
        for item in data['data']:
            # USDT-SWAP 마켓 종목 확인
            if 'USDT-SWAP' in item['instId']:
                symbol = item['instId']
                volume = float(item['volCcy24h']) * float(item['last'])  # 해당 마켓의 24시간 거래량 (거래된 금액량)
                usdt_symbols_data.append((symbol, volume))

        # 거래량(volume)으로 내림차순 정렬
        sorted_usdt_symbols_data = sorted(usdt_symbols_data, key=lambda x: x[1], reverse=True)
        return [item[0] for item in sorted_usdt_symbols_data]


async def get_all_okx_usdt_spot_symbols():
    """OKX 거래소의 모든 USDT 스팟 마켓 종목과 거래량을 비동기적으로 가져오는 함수"""
    # OKX 스팟 API 엔드포인트
    url = "https://www.okx.com/api/v5/market/tickers?instType=SPOT"

    # SSL 검증 비활성화
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE

    async with aiohttp.ClientSession() as session:
        async with session.get(url, ssl=ssl_context) as response:
            data = await response.json()

        # OKX에서의 응답 데이터 구조에 맞게 파싱
        usdt_symbols_data = []
        for item in data['data']:
            # USDT 스팟 마켓 종목 확인
            if 'USDT' in item['instId']:
                symbol = item['instId']
                volume = float(item['volCcy24h']) * float(item['last'])  # 해당 마켓의 24시간 거래량 (거래된 코인의 양)
                usdt_symbols_data.append((symbol, volume))

        # 거래량(volume)으로 내림차순 정렬
        sorted_usdt_symbols_data = sorted(usdt_symbols_data, key=lambda x: x[1], reverse=True)[:200]
        return [item[0] for item in sorted_usdt_symbols_data]


async def get_all_binance_usdt_symbols():
    """바이낸스 퓨처스의 모든 USDT 종목과 거래량을 비동기적으로 가져오는 함수"""
    url = "https://fapi.binance.com/fapi/v1/ticker/24hr"

    # SSL 검증 비활성화
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE

    async with aiohttp.ClientSession() as session:
        async with session.get(url, ssl=ssl_context) as response:
            data = await response.json()

    usdt_volume_data = []
    for item in data:
        if item['symbol'].endswith('USDT'):
            symbol = item['symbol']
            volume = float(item['volume'])
            price = float(item['lastPrice'])
            usdt_volume = volume * price
            usdt_volume_data.append((symbol, usdt_volume))

    sorted_usdt_volume_data = sorted(usdt_volume_data, key=lambda x: x[1], reverse=True)
    return [item[0] for item in sorted_usdt_volume_data]


async def get_all_binance_usdt_spot_symbols():
    """바이낸스 스팟의 모든 USDT 종목과 거래량을 비동기적으로 가져오는 함수"""
    url = "https://api.binance.com/api/v3/ticker/24hr"

    # SSL 검증 비활성화
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE

    async with aiohttp.ClientSession() as session:
        async with session.get(url, ssl=ssl_context) as response:
            data = await response.json()

    usdt_volume_data = []
    for item in data:
        if item['symbol'].endswith('USDT'):
            symbol = item['symbol']
            volume = float(item['volume'])
            price = float(item['lastPrice'])
            usdt_volume = volume * price  # 24시간 동안의 USDT 기준 거래량 계산
            usdt_volume_data.append((symbol, usdt_volume))

    sorted_usdt_volume_data = sorted(usdt_volume_data, key=lambda x: x[1], reverse=True)
    return [item[0] for item in sorted_usdt_volume_data]


async def get_all_upbit_krw_symbols():
    """Upbit의 모든 KRW 마켓 심볼을 가져오는 함수"""
    exchange = None
    try:
        exchange = await get_exchange_instance('upbit', user_id='999999999')
        if exchange is None:
            return []
        markets = await exchange.fetch_markets()
        # 수정된 부분: 심볼 포맷 변경
        krw_market_symbols = ['KRW-' + market['symbol'].replace('KRW', '').rstrip('/') for market in markets if market['symbol'].endswith('KRW')]
    except Exception as e:
        print(f"An error occurred fetching Upbit symbols: {e}")
        krw_market_symbols = []
        return krw_market_symbols
    finally:
        if exchange is not None:
            await exchange.close()
    return krw_market_symbols


async def fetch_symbols(exchange_name: str) -> list[Any]:
    """
    거래소별 심볼 목록을 가져옵니다.

    Parameters:
    -----------
    exchange_name : str
        거래소 이름 ('okx', 'binance', 'upbit', 'okx_spot', 'binance_spot')

    Returns:
    --------
    list[Any]
        심볼 목록
    """
    symbols: list[Any]
    try:
        if exchange_name == 'binance':
            symbols = await get_all_binance_usdt_symbols()
        elif exchange_name == 'upbit':
            symbols = await get_all_upbit_krw_symbols()
        elif exchange_name == 'okx':
            symbols = await get_all_okx_usdt_swap_symbols()
        elif exchange_name == 'binance_spot':
            symbols = await get_all_binance_usdt_spot_symbols()
        elif exchange_name == 'okx_spot':
            symbols = await get_all_okx_usdt_spot_symbols()
        else:
            print(f"Unknown exchange: {exchange_name}")
            symbols = []
    except Exception as e:
        print(f"Error fetching symbols for {exchange_name}: {e}")
        symbols = []

    return symbols
