"""
Balance & Position Service Module

Handles balance and position-related operations for grid trading.
Extracted from grid_original.py for better maintainability.
"""

import asyncio
import base64
import hashlib
import hmac
import json
import random
import time
import traceback
from typing import Any, Dict, Optional

import websockets

from GRID.core.redis import get_redis_connection
from shared.config import OKX_API_KEY, OKX_PASSPHRASE, OKX_SECRET_KEY


# ==================== Position Data Processors ====================

def process_okx_position_data(positions_data, symbol):
    """
    Process OKX position data from various sources (Redis/WebSocket).

    Args:
        positions_data: Position data from Redis or WebSocket
        symbol: Trading symbol (e.g., 'BTC-USDT-SWAP')

    Returns:
        float: Position quantity, 0.0 if not found
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


def process_upbit_balance(balance, symbol):
    """
    Process Upbit balance data.

    Args:
        balance: Balance data from Upbit API
        symbol: Trading symbol (e.g., 'KRW-ETC')

    Returns:
        float: Free balance amount
    """
    base_currency = symbol.split('-')[1]  # 'KRW-ETC'에서 'ETC'를 추출
    free_balance = balance['free'].get(base_currency, 0.0)  # 사용 가능 잔고 추출
    print(f'{symbol}의 balance: {free_balance}')
    return free_balance


def process_other_exchange_position(positions, symbol):
    """
    Process position data for exchanges other than OKX/Upbit.

    Args:
        positions: Position data from exchange
        symbol: Trading symbol

    Returns:
        float: Position quantity
    """
    if positions and len(positions) > 0:
        position = positions[0]  # 첫 번째 포지션 정보 사용
        quantity = float(position['info']['positionAmt'])  # 포지션 양 추출
        print(f"{symbol}의 position : {quantity}")
        return quantity
    else:
        print(f"포지션 없음: {symbol}")
        return 0.0


# ==================== Exchange-Specific Handlers ====================

async def handle_upbit(exchange, symbol, user_id, redis, cache_key):
    """
    Handle Upbit balance fetching with caching and retry logic.

    Args:
        exchange: CCXT exchange instance
        symbol: Trading symbol
        user_id: User ID
        redis: Redis connection
        cache_key: Cache key for Redis

    Returns:
        float: Balance amount
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
                await redis.set(cache_key, json.dumps(balance), ex=300)  # 300 seconds = 5 minutes

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


async def handle_okx(exchange, symbol, user_id, redis, cache_key):
    """
    Handle OKX position fetching with WebSocket fallback and caching.

    Args:
        exchange: CCXT exchange instance
        symbol: Trading symbol
        user_id: User ID
        redis: Redis connection
        cache_key: Cache key for Redis

    Returns:
        float: Position quantity
    """
    market_type = exchange.options.get('defaultType', 'No market type set')
    quantity = 0.0
    max_retries = 3
    retry_delay = 2  # seconds
    user_key = f'okx:user:{user_id}'
    user_data = await redis.hgetall(user_key)

    # WebSocket connection details
    uri = "wss://ws.okx.com:8443/ws/v5/private"
    API_KEY = OKX_API_KEY
    SECRET_KEY = OKX_SECRET_KEY
    PASSPHRASE = OKX_PASSPHRASE

    async def get_position_from_websocket():
        async with websockets.connect(uri) as websocket:
            # Perform authentication
            timestamp = str(int(time.time()))
            message = timestamp + 'GET' + '/users/self/verify'
            signature = base64.b64encode(
                hmac.new(
                    SECRET_KEY.encode('utf-8'),
                    message.encode('utf-8'),
                    hashlib.sha256
                ).digest()
            ).decode('utf-8')

            login_data = {
                "op": "login",
                "args": [{
                    "apiKey": API_KEY,
                    "passphrase": PASSPHRASE,
                    "timestamp": timestamp,
                    "sign": signature
                }]
            }
            await websocket.send(json.dumps(login_data))

            # Subscribe to position channel
            subscribe_data = {
                "op": "subscribe",
                "args": [{
                    "channel": "positions",
                    "instType": "SWAP"
                }]
            }
            await websocket.send(json.dumps(subscribe_data))

            while True:
                response = await websocket.recv()
                data = json.loads(response)

                if 'data' in data:
                    positions_data = data['data']
                    quantity = process_okx_position_data(positions_data, symbol)
                    if quantity != 0.0:
                        await redis.set(cache_key, json.dumps(positions_data), ex=300)
                        return quantity

    try:
        # Try to get cached position data
        await asyncio.sleep(random.random())
        cached_data = await redis.get(cache_key)
        if cached_data:
            positions_data = json.loads(cached_data)
            print("Using cached position data for OKX")
            return process_okx_position_data(positions_data, symbol)

        # If no valid cache, try WebSocket
        try:
            quantity = await asyncio.wait_for(get_position_from_websocket(), timeout=10.0)
            if quantity != 0.0:
                return quantity
        except asyncio.TimeoutError:
            print("WebSocket connection timed out, falling back to API")

        # If WebSocket fails or returns 0, proceed with API call
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
                    await redis.set(cache_key, json.dumps(positions_data), ex=300)  # 300 seconds = 5 minutes
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
        print(f"An unexpected error occurred: {e}")
        print(traceback.format_exc())
        return 0.0

    return quantity


async def handle_other_exchanges(exchange, symbol, user_id, redis, cache_key):
    """
    Handle position fetching for exchanges other than OKX/Upbit.

    Args:
        exchange: CCXT exchange instance
        symbol: Trading symbol
        user_id: User ID
        redis: Redis connection
        cache_key: Cache key for Redis

    Returns:
        float: Position quantity
    """
    max_retries = 3
    retry_delay = 2  # seconds

    try:
        # Try to get cached position data
        cached_data = await redis.get(cache_key)
        if cached_data:
            positions = json.loads(cached_data)
            print("Using cached position data for other exchanges")
            return process_other_exchange_position(positions, symbol)

        # If no valid cache, proceed with API call
        for attempt in range(max_retries):
            try:
                positions = await exchange.fetch_positions([symbol])

                # Cache the position data with TTL
                await redis.set(cache_key, json.dumps(positions), ex=300)  # 300 seconds = 5 minutes

                return process_other_exchange_position(positions, symbol)
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


# ==================== Main Balance & Position Functions ====================

async def get_balance_of_symbol(exchange, symbol, user_id):
    """
    Get balance for a specific symbol across different exchanges.

    Args:
        exchange: CCXT exchange instance
        symbol: Trading symbol
        user_id: User ID

    Returns:
        float: Balance or position quantity
    """
    redis = await get_redis_connection()
    try:
        if exchange.id.lower() == 'upbit':
            cache_key = f"upbit:balance:{user_id}:{symbol}"
            return await handle_upbit(exchange, symbol, user_id, redis, cache_key)
        elif exchange.id.lower() == 'okx':
            cache_key = f"okx:positions:{user_id}"
            return await handle_okx(exchange, symbol, user_id, redis, cache_key)
        else:
            cache_key = f"{exchange.id.lower()}:positions:{user_id}:{symbol}"
            return await handle_other_exchanges(exchange, symbol, user_id, redis, cache_key)
    except Exception as e:
        print(f"An error occurred9: {e}")
        return 0.0


async def get_all_positions(exchange_name, user_id):
    """
    Get all positions for a user on a specific exchange.

    Args:
        exchange_name: Name of the exchange
        user_id: User ID

    Returns:
        dict: Dictionary of {symbol: position_quantity}
    """
    redis = await get_redis_connection()

    # Try new Hash pattern first (Phase 2)
    index_key = f'positions:index:{user_id}:{exchange_name}'
    position_keys = await redis.smembers(index_key)

    if position_keys:
        # New Hash pattern: individual positions
        result = {}
        excluded_symbols = ['BTC-USDT-SWAP', 'ETH-USDT-SWAP', 'SOL-USDT-SWAP']

        for pos_key in position_keys:
            # pos_key format: "{symbol}:{side}"
            try:
                symbol, side = pos_key.split(':')
                position_key = f'positions:{user_id}:{exchange_name}:{symbol}:{side}'

                # Get position hash
                position = await redis.hgetall(position_key)
                if position:
                    pos = float(position.get('pos', 0))
                    notional_usd = float(position.get('notionalUsd', 0))

                    if pos != 0 and notional_usd < 10000 and symbol not in excluded_symbols:
                        # Aggregate positions by symbol (sum long and short)
                        result[symbol] = result.get(symbol, 0) + pos
            except (ValueError, KeyError) as e:
                print(f"Error processing position key {pos_key}: {e}")
                continue

        return result

    # Fallback to legacy JSON array pattern
    legacy_key = f'{exchange_name}:positions:{user_id}'
    position_data = await redis.get(legacy_key)

    if position_data is None:
        return {}  # 포지션 정보가 없으면 빈 딕셔너리 반환

    try:
        positions = json.loads(position_data)
        result = {}
        excluded_symbols = ['BTC-USDT-SWAP', 'ETH-USDT-SWAP', 'SOL-USDT-SWAP']

        if isinstance(positions, list):
            for position in positions:
                if isinstance(position, dict):
                    symbol = position.get('instId')
                    pos = float(position.get('pos', 0))
                    notional_usd = float(position.get('notionalUsd', 0))
                    if pos != 0 and notional_usd < 10000 and symbol not in excluded_symbols:
                        result[symbol] = pos
        elif isinstance(positions, dict):
            for symbol, position in positions.items():
                if isinstance(position, dict):
                    pos = float(position.get('pos', 0))
                    notional_usd = float(position.get('notionalUsd', 0))
                    if pos != 0 and notional_usd < 10000 and symbol not in excluded_symbols:
                        result[symbol] = pos

        return result  # 0이 아닌 포지션만 포함된 딕셔너리 반환

    except (json.JSONDecodeError, ValueError, AttributeError) as e:
        print(f"Error processing position data: {e}")
        return {}  # 데이터 파싱 오류 시 빈 딕셔너리 반환


async def get_position_size(exchange_name, user_id, symbol):
    """
    Get position size for a specific symbol.

    Args:
        exchange_name: Name of the exchange
        user_id: User ID
        symbol: Trading symbol

    Returns:
        float: Position size, 0.0 if no position found
    """
    redis = await get_redis_connection()

    # Try new Hash pattern first (Phase 2)
    index_key = f'positions:index:{user_id}:{exchange_name}'
    position_keys = await redis.smembers(index_key)

    if position_keys:
        # New Hash pattern: check for this specific symbol
        total_pos = 0.0

        for pos_key in position_keys:
            # pos_key format: "{symbol}:{side}"
            try:
                pos_symbol, side = pos_key.split(':')
                if pos_symbol == symbol:
                    position_key = f'positions:{user_id}:{exchange_name}:{symbol}:{side}'
                    position = await redis.hgetall(position_key)
                    if position:
                        pos = float(position.get('pos', 0))
                        # Sum both long and short positions for the symbol
                        total_pos += pos
            except (ValueError, KeyError) as e:
                print(f"Error processing position key {pos_key}: {e}")
                continue

        return total_pos

    # Fallback to legacy JSON array pattern
    position_key = f'{exchange_name}:positions:{user_id}'
    position_data = await redis.get(position_key)

    if position_data is None:
        return 0.0  # 포지션 정보가 없으면 0 반환

    try:
        positions = json.loads(position_data)
        if isinstance(positions, list):
            for position in positions:
                if isinstance(position, dict) and position.get('instId') == symbol:
                    return float(position.get('pos', 0))
        elif isinstance(positions, dict):
            position = positions.get(symbol)
            if position:
                return float(position.get('pos', 0))
        return 0.0  # 해당 심볼에 대한 포지션이 없으면 0 반환
    except (json.JSONDecodeError, ValueError, AttributeError) as e:
        print(f"Error processing position data: {e}")
        return 0.0  # 데이터 파싱 오류 시 0 반환
