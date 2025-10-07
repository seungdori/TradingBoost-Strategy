"""
Symbol Management Service Module

Handles symbol-related operations including symbol search, filtering, and market data.
Extracted from grid_original.py for better maintainability.
"""

import json
import aiohttp
import pandas as pd
from typing import List, Optional
from shared.dtos.trading import WinrateDto
from shared.utils import path_helper


async def get_redis_connection():
    """Get Redis connection from GRID.core.redis"""
    from GRID.core.redis import get_redis_connection as core_get_redis
    return await core_get_redis()


# ==================== Symbol Data Processing ====================

def sort_ai_trading_data(exchange_name, direction):
    """
    Sort AI trading data by win rate from CSV.

    Args:
        exchange_name: Exchange name
        direction: Trading direction

    Returns:
        DataFrame with name and win_rate columns
    """
    if exchange_name is None:
        raise ValueError("exchange 변수가 None입니다. 올바른 값을 제공해야 합니다.")

    summary_path = path_helper.grid_dir / str(exchange_name) / str(direction) / f"{exchange_name}_summary_trading_results.csv"
    print(summary_path)
    df_summary = pd.read_csv(summary_path)

    # 'symbol' 열을 'name'으로 이름 변경
    df_summary.rename(columns={'symbol': 'name'}, inplace=True)
    # 'total_profit' 열을 'win_rate'로 이름 변경하여 사용하기
    df_summary.rename(columns={'total_profit': 'win_rate'}, inplace=True)

    return df_summary[['name', 'win_rate']]


async def build_sort_ai_trading_data(exchange_name: str, enter_strategy: str) -> List[WinrateDto]:
    """
    Build sorted AI trading data as WinrateDto list.

    Args:
        exchange_name: Exchange name
        enter_strategy: Entry strategy direction

    Returns:
        List of WinrateDto objects
    """
    direction = str(enter_strategy).lower()
    if exchange_name is None:
        raise ValueError("exchange 변수가 None입니다. 올바른 값을 제공해야 합니다.")
    if direction is None:
        raise ValueError("direction 변수가 None입니다. 올바른 값을 제공해야 합니다.")

    exchange_name = str(exchange_name).lower()
    summary_path = path_helper.grid_dir / str(exchange_name) / direction / f"{exchange_name}_summary_trading_results.csv"
    # summary_trading_results.csv 파일에서 데이터 읽기
    df_summary = pd.read_csv(summary_path)

    # 'total_profit' 열을 기반으로 각 win_rate 값 설정, assuming 'total_profit' column exists
    df_summary['long_win_rate'] = df_summary['total_profit']
    df_summary['short_win_rate'] = df_summary['total_profit']
    df_summary['total_win_rate'] = df_summary['total_profit']

    # Ensure that 'symbol' column is correctly renamed to 'name'
    df_summary_renamed = df_summary.rename(columns={'symbol': 'name'})

    # Create WinrateDto objects from the DataFrame
    win_rate_data = [
        WinrateDto(
            name=row['name'],  # Correctly reference the 'name' column after renaming
            long_win_rate=row['long_win_rate'],
            short_win_rate=row['short_win_rate'],
            total_win_rate=row['total_win_rate']
        )
        for _, row in df_summary_renamed.iterrows()
    ]

    return win_rate_data


# ==================== Exchange Symbol Fetching ====================

async def get_all_binance_usdt_symbols():
    """
    Get all Binance futures USDT symbols sorted by volume.

    Returns:
        List of symbol names
    """
    url = "https://fapi.binance.com/fapi/v1/ticker/24hr"

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
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
    """
    Get all Binance spot USDT symbols sorted by volume.

    Returns:
        List of symbol names
    """
    url = "https://api.binance.com/api/v3/ticker/24hr"

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
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


async def get_all_bitget_usdt_symbols(future=True):
    """
    Get all Bitget USDT futures symbols sorted by volume.

    Args:
        future: Whether to get futures (True) or spot (False)

    Returns:
        List of symbol names
    """
    # 비트겟 선물 API 엔드포인트
    url = "https://api.bitget.com/api/mix/v1/market/tickers?productType=umcbl"

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            data = await response.json()

        # 응답 데이터 구조 확인
        if data['code'] != '00000':
            print(f"Error: {data['msg']}")
            return []

        if 'data' not in data or not isinstance(data['data'], list):
            print("Error: Unexpected response structure")
            return []

        # 비트겟에서의 응답 데이터 구조에 맞게 파싱
        usdt_volume_data = []
        for item in data['data']:
            if 'USDT' in item['symbol']:  # USDT 선물 마켓 확인
                original_symbol = item['symbol']
                symbol = original_symbol.replace('USDT_UMCBL', '/USDT')
                usdt_volume = float(item['usdtVolume'])  # USDT 24시간 거래량
                usdt_volume_data.append((symbol, usdt_volume))

        sorted_usdt_volume_data = sorted(usdt_volume_data, key=lambda x: x[1], reverse=True)
        return [item[0] for item in sorted_usdt_volume_data]


async def get_upbit_market_data():
    """
    Get Upbit market data sorted by change rate.

    Returns:
        Dict mapping symbol to change rate
    """
    url = "https://api.upbit.com/v1/market/all"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            markets = await response.json()

    krw_markets = [market['market'] for market in markets if market['market'].startswith('KRW-')]

    url = "https://api.upbit.com/v1/ticker"
    params = {"markets": ",".join(krw_markets)}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params) as response:
            tickers = await response.json()
    # 변화율을 절대값이 아닌 실제 값으로 가져오기
    market_data = {ticker['market']: ticker['signed_change_rate'] for ticker in tickers}

    # 변화율이 높은 것부터 낮은 순서대로 소팅
    sorted_market_data = dict(sorted(market_data.items(), key=lambda item: item[1], reverse=True))

    return sorted_market_data


# ==================== Symbol Selection & Filtering ====================

async def generate_profit_data(exchange_name, direction, market_data):
    """
    Generate profit data for symbol selection.

    Args:
        exchange_name: Exchange name
        direction: Trading direction
        market_data: Market data (for Upbit)

    Returns:
        Tuple of (profit_data DataFrame, sorted_column name)
    """
    from GRID.strategies.grid_original import summarize_trading_results

    if exchange_name == 'upbit':
        profit_data = pd.DataFrame(market_data.items(), columns=['name', 'change_rate'])
        sorted_column = 'change_rate'
    else:
        summarize_trading_results(exchange_name=exchange_name, direction=direction)
        profit_data = sort_ai_trading_data(exchange_name=exchange_name, direction=direction)
        sorted_column = 'win_rate'

    return profit_data, sorted_column


async def process_exchange_data(exchange_name, direction, ban_list, white_list, market_data=None):
    """
    Process exchange data with filtering and caching.

    Args:
        exchange_name: Exchange name
        direction: Trading direction
        ban_list: List of banned symbols
        white_list: List of whitelisted symbols
        market_data: Optional market data

    Returns:
        Tuple of (filtered symbols DataFrame, sorted_column name)
    """
    redis_client = await get_redis_connection()

    # 캐시 키 생성
    cache_key = f"{exchange_name}:summarize:{direction}"

    # 캐시 확인
    cached_data = await redis_client.get(cache_key)

    if cached_data:
        # 캐시된 데이터가 있으면 역직렬화
        cached_result = json.loads(cached_data)
        if 'symbols' in cached_result:
            profit_data = pd.DataFrame(cached_result['symbols'])
            sorted_column = 'win_rate'  # 'win_rate'로 고정
        else:
            # 'symbols'가 없으면 캐시를 무시하고 새로 데이터를 생성
            profit_data, sorted_column = await generate_profit_data(exchange_name, direction, market_data)
    else:
        # 캐시된 데이터가 없으면 새로 데이터를 생성
        profit_data, sorted_column = await generate_profit_data(exchange_name, direction, market_data)

    # 결과를 캐시에 저장 (90초 TTL 설정)
    cache_data = {
        'symbols': profit_data.to_dict(orient='records')
    }
    await redis_client.set(cache_key, json.dumps(cache_data), ex=90)  # 'ex' 파라미터로 90초 TTL 설정

    # 거래소별 필터링 적용
    if exchange_name in ['binance', 'bitget', 'binance_spot', 'bitget_spot', 'okx_spot']:
        symbols = profit_data[(profit_data['name'].astype(str).str.endswith('USDT')) &
                              ~(profit_data['name'].astype(str).str.contains('USDC')) &
                              ~(profit_data['name'].astype(str).str.contains('USTC'))]
    elif exchange_name == 'okx':
        symbols = profit_data[(profit_data['name'].astype(str).str.endswith('USDT-SWAP')) &
                              ~(profit_data['name'].astype(str).str.contains('USDC')) &
                              ~(profit_data['name'].astype(str).str.contains('USTC'))]
    else:
        symbols = profit_data

    # ban_list 적용
    for ban_word in ban_list:
        symbols = symbols[~symbols['name'].str.contains(ban_word, case=False)]

    return symbols, sorted_column


async def get_running_symbols(exchange_id: str, user_id: str) -> list:
    """
    Get currently running symbols for a user.

    Args:
        exchange_id: Exchange ID
        user_id: User ID

    Returns:
        List of running symbols
    """
    redis = await get_redis_connection()
    redis_key = f"running_symbols:{exchange_id}:{user_id}"
    running_symbols_json = await redis.get(redis_key)

    if running_symbols_json:
        await redis.delete(redis_key)
        result: list = json.loads(running_symbols_json)
        return result
    return []


async def get_completed_symbols(user_id, exchange_name):
    """
    Get completed symbols for a user.

    Args:
        user_id: User ID
        exchange_name: Exchange name

    Returns:
        List of completed symbols
    """
    redis = await get_redis_connection()
    user_key = f'{exchange_name}:user:{user_id}'
    completed_symbols = await redis.hget(user_key, 'completed_trading_symbols')
    if completed_symbols:
        return json.loads(completed_symbols)
    return []


async def get_top_symbols(user_id, exchange_name, direction='long-short', limit=20, force_restart=False, get_new_only_symbols=False):
    """
    Get top symbols for trading based on various filters and rankings.

    Args:
        user_id: User ID
        exchange_name: Exchange name
        direction: Trading direction
        limit: Maximum number of symbols
        force_restart: Whether to include former running symbols
        get_new_only_symbols: Whether to exclude completed symbols

    Returns:
        List of top symbols
    """
    from GRID.repositories.symbol_repository import get_ban_list_from_db, get_white_list_from_db
    from GRID.services.balance_service import get_all_positions

    try:
        ban_list = await get_ban_list_from_db(user_id, exchange_name)
        print(f"{user_id} ban_list : ", ban_list)
    except FileNotFoundError:
        ban_list = []
        print('ban_list.json 파일이 존재하지 않습니다. 빈 리스트로 초기화합니다.')

    ban_list.extend(['XEC', 'USTC', 'USDC', 'TRY', 'CEL', 'GAL', 'OMG', 'SPELL', 'KSM', 'GPT', 'BLOCK', 'FRONT', 'TURBO', 'ZERO', 'MSN', 'FET'])

    try:
        white_list = await get_white_list_from_db(user_id, exchange_name)
    except FileNotFoundError:
        white_list = []
        print('white_list.json 파일이 존재하지 않습니다. 빈 리스트로 초기화합니다.')

    if exchange_name == 'upbit':
        market_data = await get_upbit_market_data()
    else:
        market_data = None

    symbols, sorted_column = await process_exchange_data(exchange_name, direction, ban_list, white_list, market_data)

    if white_list:
        if exchange_name in ['binance', 'bitget', 'binance_spot', 'bitget_spot']:
            white_list = [symbol + 'USDT' for symbol in white_list]
        elif exchange_name == 'upbit':
            white_list = ['KRW-' + symbol for symbol in white_list]
        elif exchange_name == 'okx':
            white_list = [symbol + '-USDT-SWAP' for symbol in white_list]
        elif exchange_name == 'okx_spot':
            white_list = [symbol + '-USDT' for symbol in white_list]

    # get_all_positions 함수를 사용하여 현재 포지션 정보 가져오기
    positions = await get_all_positions(exchange_name, user_id)
    excluded_symbols = ['BTC-USDT-SWAP', 'ETH-USDT-SWAP', 'SOL-USDT-SWAP']
    positions = {k: v for k, v in positions.items() if k not in excluded_symbols}
    print(f"Current positions (after exclusion): {positions}")

    try:
        if force_restart:
            former_running_symbols = await get_running_symbols(exchange_name, user_id)
            print(f"former_running_symbols : {former_running_symbols}")
        else:
            former_running_symbols = []
    except Exception as e:
        print(f"{user_id} : An error occurred while fetching running symbols: {e}")
        former_running_symbols = []

    # ban_list에 없는 심볼만 포함
    top_symbols = [symbol for symbol in former_running_symbols if symbol not in ban_list]

    # positions에서 ban_list에 없는 심볼 추가
    for symbol in positions.keys():
        if symbol not in ban_list and symbol not in top_symbols:
            top_symbols.append(symbol)

    # 기존에 completed symbol이었던 것은 우선 제외
    if get_new_only_symbols:
        try:
            completed_symbols = await get_completed_symbols(user_id, exchange_name)
            top_symbols = [symbol for symbol in top_symbols if symbol not in completed_symbols]
        except Exception as e:
            print(f"An error occurred while fetching completed symbols: {e}")

    remaining_limit = max(limit - len(top_symbols), 0)
    print(f"remaining_limit : {remaining_limit}")

    if remaining_limit > 0:
        # white_list에서 남은 종목 선택 (ban_list에 없는 것만)
        white_list_symbols = symbols[symbols['name'].str.lower().isin([w.lower() for w in white_list]) & ~symbols['name'].isin(ban_list)]
        white_list_top_symbols = white_list_symbols.sort_values(by=sorted_column, ascending=False).head(remaining_limit)
        top_symbols.extend([symbol for symbol in white_list_top_symbols['name'].tolist() if symbol not in top_symbols])
        remaining_limit = limit - len(top_symbols)

        if remaining_limit > 0:
            # 나머지 종목에서 선택 (ban_list에 없는 것만)
            non_selected_symbols = symbols[~symbols['name'].isin(top_symbols) & ~symbols['name'].isin(ban_list)]
            non_selected_top_symbols = non_selected_symbols.sort_values(by=sorted_column, ascending=False).head(remaining_limit)
            top_symbols.extend(non_selected_top_symbols['name'].tolist())

    print(f"{user_id} : ban_list : {ban_list}")
    print(f"{user_id} : Final top_symbols: {top_symbols}")
    return top_symbols


# ==================== Symbol Utilities ====================

async def get_new_symbols(user_id, exchange_name, direction, limit):
    """
    Get new symbols for trading.

    Args:
        user_id: User ID
        exchange_name: Exchange name
        direction: Trading direction
        limit: Maximum number of symbols

    Returns:
        List of new symbols
    """
    return await get_top_symbols(user_id, exchange_name, direction, limit, force_restart=False, get_new_only_symbols=True)


def modify_symbols(exchange_name, symbols):
    """
    Modify symbols based on exchange requirements.

    Args:
        exchange_name: Exchange name
        symbols: List of symbols

    Returns:
        List of modified symbols
    """
    if exchange_name == 'bitget':
        return [symbol.replace('/USDT', '') + '/USDT:USDT' for symbol in symbols]
    elif exchange_name == 'bitget_spot':
        return [symbol.replace('/USDT', '') + '/USDT:USDT' for symbol in symbols]
    return symbols


def format_symbols(symbols):
    """
    Format symbols for display.

    Args:
        symbols: List of symbols

    Returns:
        Formatted string
    """
    return ', '.join(symbols)
