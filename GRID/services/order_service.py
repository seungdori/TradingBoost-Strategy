"""
Order Management Service Module

Handles order-related operations for grid trading.
Extracted from grid_original.py for better maintainability.
"""

import asyncio
import json
import logging
from decimal import Decimal
from typing import Any, Dict, List, Optional

from shared.database.redis_patterns import redis_context, RedisTTL

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def parse_bool(value):
    """Parse various value types to boolean"""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.lower() in ('true', '1', 'yes', 'on')
    return False


# ==================== Order Placement Tracking ====================

async def get_placed_prices(exchange_name: str, user_id: int, symbol_name: str) -> List[float]:
    """
    Get list of placed order prices from cache.

    Args:
        exchange_name: Exchange name
        user_id: User ID
        symbol_name: Symbol name

    Returns:
        List of placed prices
    """
    async with redis_context() as redis_client:
        key = f"orders:{exchange_name}:user:{user_id}:symbol:{symbol_name}:orders"
        cached_data = await redis_client.get(key)
        if cached_data:
            try:
                data = json.loads(cached_data)
                return [float(price) for price in data if price is not None]  # None 값 필터링 및 float 변환
            except (json.JSONDecodeError, ValueError) as e:
                logging.error(f"Error decoding cached data: {e}")
                return []
        return []


async def add_placed_price(exchange_name: str, user_id: int, symbol_name: str, price: float) -> None:
    """
    Add a price to the list of placed orders.

    Args:
        exchange_name: Exchange name
        user_id: User ID
        symbol_name: Symbol name
        price: Order price
    """
    async with redis_context() as redis_client:
        key = f"orders:{exchange_name}:user:{user_id}:symbol:{symbol_name}:orders"
        prices = await get_placed_prices(exchange_name, user_id, symbol_name)
        if price not in prices:
            prices.append(price)
            await redis_client.setex(key, 45, json.dumps(prices))  # 45초 동안 캐시 유지


async def is_order_placed(exchange_name: str, user_id: int, symbol_name: str, grid_level: int) -> bool:
    """
    Check if an order is already placed at a specific grid level.

    Args:
        exchange_name: Exchange name
        user_id: User ID
        symbol_name: Symbol name
        grid_level: Grid level

    Returns:
        True if order is placed, False otherwise
    """
    async with redis_context() as redis_client:
        key = f'orders:{exchange_name}:user:{user_id}:symbol:{symbol_name}:order_placed_index'

        cached_data = parse_bool(await redis_client.hget(key, str(grid_level)))
        if cached_data == True:
            await asyncio.sleep(0.1)
            return True
        return False


async def is_price_placed(exchange_name: str, user_id: int, symbol_name: str, price: float, grid_level: int | None = None, grid_num: int = 20) -> bool:
    """
    Check if a price is already placed (with tolerance).

    Args:
        exchange_name: Exchange name
        user_id: User ID
        symbol_name: Symbol name
        price: Price to check
        grid_level: Optional grid level
        grid_num: Grid number

    Returns:
        True if price is already placed, False otherwise
    """
    prices = await get_placed_prices(exchange_name, user_id, symbol_name)
    logging.debug(f"Received prices: {prices}")
    try:
        placed = any(abs(float(p) - price) / price < 0.0003 for p in prices)  # 명시적 float 변환
        if placed is True:
            logging.info(f"{user_id} : Price {price} already placed for {symbol_name} on {grid_level}")
            await asyncio.sleep(0.3)
            return True
        if grid_level is not None:
            placed_index = await get_order_placed(exchange_name, user_id, symbol_name, grid_num)
            if placed_index[grid_level] == True:
                logging.info(f"🍋{user_id} : Price {price} already placed for {symbol_name} on {grid_level}")
                await asyncio.sleep(0.3)
                return True
        return False
    except (ValueError, TypeError) as e:
        logging.error(f"Error in price comparison: {e}")
        return False


async def set_order_placed(exchange_name, user_id, symbol, grid_level, level_index=None):
    """
    Mark an order as placed in Redis.

    Args:
        exchange_name: Exchange name
        user_id: User ID
        symbol: Symbol
        grid_level: Grid level
        level_index: Optional level index
    """
    async with redis_context() as redis:
        order_placed_key = f'orders:{exchange_name}:user:{user_id}:symbol:{symbol}:order_placed'
        if level_index is not None:
            order_placed_index = f'orders:{exchange_name}:user:{user_id}:symbol:{symbol}:order_placed_index'
            await redis.hset(order_placed_index, str(level_index), str("true").lower())
            stored_level_index = parse_bool(await redis.hget(order_placed_index, str(level_index)))
            await redis.expire(order_placed_index, 120)
        await redis.hset(order_placed_key, str(grid_level), str("true").lower())
        stored_value = parse_bool(await redis.hget(order_placed_key, str(grid_level)))
        await redis.expire(order_placed_key, 120)  # 만료 시간 갱신


async def get_order_placed(exchange_name, user_id, symbol, grid_num):
    """
    Get order placement status for all grid levels.

    Args:
        exchange_name: Exchange name
        user_id: User ID
        symbol: Symbol
        grid_num: Grid number

    Returns:
        Dict mapping grid level to placement status
    """
    async with redis_context() as redis:
        order_placed_key = f'orders:{exchange_name}:user:{user_id}:symbol:{symbol}:order_placed_index'

        # Redis에서 해시 전체를 가져옵니다
        order_placed_data = await redis.hgetall(order_placed_key)

        # 결과를 적절한 형식으로 변환합니다
        order_placed = {}
        for n in range(0, grid_num + 1):
            value = order_placed_data.get(str(n), '') or order_placed_data.get(str(float(n)), '')
            order_placed[n] = value.lower() == 'true'

        return order_placed


async def reset_order_placed(exchange_name, user_id, symbol, grid_num):
    """
    Reset order placement status.

    Args:
        exchange_name: Exchange name
        user_id: User ID
        symbol: Symbol
        grid_num: Grid number
    """
    async with redis_context() as redis:
        order_placed_key = f'orders:{exchange_name}:user:{user_id}:symbol:{symbol}:order_placed'
        order_placed_index = f'orders:{exchange_name}:user:{user_id}:symbol:{symbol}:order_placed_index'

        # Reset all grid levels
        for n in range(0, grid_num + 1):
            await redis.hset(order_placed_key, str(n), str("false").lower())
            await redis.hset(order_placed_index, str(n), str("false").lower())


# ==================== Order Checking ====================

async def check_existing_order_at_price(
    redis: Any,
    exchange_name: str,
    user_id: str,
    symbol: str,
    price: Decimal,
    side: Optional[str] = None,
    tolerance: Decimal = Decimal('0.0001')
) -> List[Dict[str, Any]]:
    """
    Check if there's an existing order at the given price for a specific symbol.

    Args:
        redis: Redis connection
        exchange_name: Name of the exchange
        user_id: User ID
        symbol: Trading symbol (e.g., 'BTC/USDT')
        price: Price to check
        side: Optional. 'buy' or 'sell'. If not provided, checks both sides.
        tolerance: Price tolerance for matching (default is 0.01%)

    Returns:
        List of matching orders
    """
    redis_key = f"{exchange_name}:user:{user_id}:{symbol}"
    matching_orders = []

    try:
        # Fetch all orders for the symbol
        all_orders = await redis.hgetall(redis_key)

        for order_id, order_json in all_orders.items():
            order = json.loads(order_json)
            order_price = Decimal(str(order['price']))
            order_side = order['side'].lower()

            # Check if the order price is within the tolerance of the given price
            price_diff = abs(order_price - price) / price
            if price_diff <= tolerance:
                # If side is specified, check if it matches
                if side is None or order_side == side.lower():
                    matching_orders.append(order)

        return matching_orders

    except Exception as e:
        print(f"Error checking existing orders: {e}")
        return []


def check_order_validity(notional_usd, pos, max_notional_value, order_direction):
    """
    Check if an order is valid based on position and notional value.

    Args:
        notional_usd: Current notional USD value
        pos: Current position size
        max_notional_value: Maximum allowed notional value
        order_direction: Order direction ('long' or 'short')

    Returns:
        True if order is valid, False otherwise
    """
    if pos > 0:  # 현재 롱 포지션
        if order_direction == 'long' and notional_usd >= max_notional_value:
            return False  # 주문 불가 (이미 최대 notional 값에 도달)
        elif order_direction == 'short':
            return True  # 주문 가능 (반대 방향으로 주문)
    elif pos < 0:  # 현재 숏 포지션
        if order_direction == 'short' and abs(notional_usd) >= max_notional_value:
            return False  # 주문 불가 (이미 최대 notional 값에 도달)
        elif order_direction == 'long':
            return True  # 주문 가능 (반대 방향으로 주문)
    else:  # pos == 0, 현재 포지션 없음
        return True  # 주문 가능

    return True  # 기본적으로 주문 가능


async def okay_to_place_order(exchange_name, user_id, symbol, check_price, max_notional_value, order_direction):
    """
    Check if it's okay to place a new order.

    Args:
        exchange_name: Exchange name
        user_id: User ID
        symbol: Symbol
        check_price: Price to check
        max_notional_value: Maximum notional value
        order_direction: Order direction

    Returns:
        True if okay to place order, False otherwise
    """
    async with redis_context() as redis:
        # 기존 주문 확인 로직
        order_placed_key = f'orders:{exchange_name}:user:{user_id}:symbol:{symbol}:order_placed'
        all_prices = await redis.hgetall(order_placed_key)
        for stored_price, value in all_prices.items():
            stored_price = float(stored_price)
            if abs(stored_price - check_price) / stored_price <= 0.001:
                return False  # 이미 해당 가격에 주문이 있음

        # 포지션 정보 확인 - Try new Hash pattern first (Phase 2)
        index_key = f'positions:index:{user_id}:{exchange_name}'
        position_keys = await redis.smembers(index_key)

        if position_keys:
            # New Hash pattern: check for this specific symbol
            total_pos = 0.0
            total_notional_usd = 0.0

            for pos_key in position_keys:
                # pos_key format: "{symbol}:{side}"
                try:
                    pos_symbol, side = pos_key.split(':')
                    if pos_symbol == symbol:
                        position_key = f'positions:{user_id}:{exchange_name}:{symbol}:{side}'
                        position = await redis.hgetall(position_key)
                        if position:
                            pos = float(position.get('pos', 0))
                            notional_usd = float(position.get('notionalUsd', 0))
                            # Sum positions (long is positive, short is negative)
                            total_pos += pos
                            total_notional_usd += abs(notional_usd)
                except (ValueError, KeyError) as e:
                    print(f"Error processing position key {pos_key}: {e}")
                    continue

            if total_pos != 0:
                able_to_order = check_order_validity(total_notional_usd, total_pos, max_notional_value, order_direction)
                return able_to_order
            return True  # No position found for this symbol, order allowed

        # Fallback to legacy JSON array pattern
        position_key = f'{exchange_name}:positions:{user_id}'
        position_data = await redis.get(position_key)

        if position_data is None:
            return True  # 포지션 정보가 없으므로, 주문 가능

        try:
            positions = json.loads(position_data)
            if isinstance(positions, list):
                for position in positions:
                    if isinstance(position, dict) and position.get('instId') == symbol:
                        notional_usd = float(position.get('notionalUsd', 0))
                        pos = float(position.get('pos', 0))
                        able_to_order = check_order_validity(notional_usd, pos, max_notional_value, order_direction)
                        return able_to_order
            elif isinstance(positions, dict):
                position = positions.get(symbol)
                if position:
                    notional_usd = float(position.get('notionalUsd', 0))
                    pos = float(position.get('pos', 0))
                    able_to_order = check_order_validity(notional_usd, pos, max_notional_value, order_direction)
                    return able_to_order
            return True  # 주문 가능 (해당 심볼에 대한 포지션이 없음)
        except (json.JSONDecodeError, ValueError, AttributeError) as e:
            print(f"Error processing position data: {e}")
            return True  # 데이터 파싱 오류 시 주문 허용


# ==================== Order Creation ====================

async def create_short_order(exchange_instance, exchange_name, symbol, amount, price, **kwargs):
    """
    Create a short order with exchange-specific handling.

    Args:
        exchange_instance: CCXT exchange instance
        exchange_name: Exchange name
        symbol: Symbol
        amount: Order amount
        price: Order price
        **kwargs: Additional parameters

    Returns:
        Order object
    """
    order_params = {
        'symbol': symbol,
        'type': 'limit',
        'side': 'sell',
        'amount': amount,
        'price': price
    }

    if exchange_name in ['binance', 'binance_spot', 'okx_spot']:
        return await exchange_instance.create_order(**order_params)

    elif exchange_name == 'okx':
        if kwargs.get('direction') == 'long':
            order_params['params'] = {'reduceOnly': True}
        return await exchange_instance.create_order(**order_params)

    elif exchange_name == 'bitget':
        order_params['symbol'] = kwargs.get('symbol_name', symbol)  # bitget uses symbol_name
        order_params['params'] = {
            'contract_type': 'swap',
            'position_mode': 'single',
            'marginCoin': 'USDT',
        }
        return await exchange_instance.create_order(**order_params)

    elif exchange_name == 'bitget_spot':
        order_params['symbol'] = kwargs.get('symbol_name', symbol)  # bitget uses symbol_name
        return await exchange_instance.create_order(**order_params)

    else:
        raise ValueError(f"Unsupported exchange: {exchange_name}")


async def create_short_orders(exchange_instance, symbol, short_level, adjusted_quantity, min_quantity, user_id, reduce_only=False):
    """
    Create short orders with optional reduce-only mode.

    Args:
        exchange_instance: CCXT exchange instance
        symbol: Symbol
        short_level: Price level for short order
        adjusted_quantity: Adjusted quantity
        min_quantity: Minimum quantity
        user_id: User ID
        reduce_only: Whether to create reduce-only order

    Returns:
        Order object
    """
    try:
        if reduce_only:
            short_order = await exchange_instance.create_order(
                symbol=symbol,
                type='limit',
                side='sell',
                amount=max(adjusted_quantity, min_quantity),
                price=short_level,
                params={'reduceOnly': True}
            )
            print(f'{symbol} long direction short_order11✔︎')
        else:
            short_order = await exchange_instance.create_order(
                symbol=symbol,
                type='limit',
                side='sell',
                amount=max(adjusted_quantity, min_quantity),
                price=short_level
            )
            print(f"{user_id} : {symbol} direction short_order22✔︎")

        return short_order
    except Exception as e:
        print(f"{user_id} : An error occurred in create_short_orders2: {e}")
        raise e


async def fetch_order_with_retry(exchange_instance, order_id, symbol, max_retries=3):
    """
    Fetch order with retry logic.

    Args:
        exchange_instance: CCXT exchange instance
        order_id: Order ID
        symbol: Symbol
        max_retries: Maximum retry attempts

    Returns:
        Order object
    """
    for attempt in range(max_retries):
        try:
            return await exchange_instance.fetch_order(order_id, symbol)
        except Exception as e:
            if 'Order does not exist' in str(e):
                return {'status': 'closed'}
            if attempt == max_retries - 1:
                raise
            print(f"Fetch order attempt {attempt + 1} failed: {e}")
            await asyncio.sleep(5)


# ==================== Take Profit Orders ====================

async def get_take_profit_orders_info(redis, exchange_name, user_id, symbol_name, grid_num, force_restart=False):
    """
    Get or initialize take profit orders information.

    Args:
        redis: Redis connection
        exchange_name: Exchange name
        user_id: User ID
        symbol_name: Symbol name
        grid_num: Grid number
        force_restart: Whether to force restart

    Returns:
        Take profit orders info dict
    """
    symbol_key = f"{exchange_name}:user:{user_id}:symbol:{symbol_name}"

    # Redis에서 기존 정보 불러오기
    stored_info = await redis.hget(symbol_key, 'take_profit_orders_info')
    if stored_info:
        take_profit_orders_info = json.loads(stored_info)
    else:
        # 저장된 정보가 없으면 새로 생성
        take_profit_orders_info = {
            str(n): {
                "order_id": None,
                "quantity": 0.0,
                "target_price": 0.0,
                "active": False,
                "side": None
            } for n in range(0, grid_num + 1)
        }

    # 변경된 정보를 Redis에 저장
    await redis.hset(symbol_key, 'take_profit_orders_info', json.dumps(take_profit_orders_info))

    return take_profit_orders_info


# ==================== Order Cancellation ====================

async def cancel_user_limit_orders(user_id, exchange_name):
    """
    Cancel all user limit orders.

    Args:
        user_id: User ID
        exchange_name: Exchange name
    """
    from GRID.trading.instance_manager import get_exchange_instance

    try:
        exchange = await get_exchange_instance(exchange_name, user_id)
        if not exchange:
            return

        open_orders = await exchange.fetch_open_orders()
        for order in open_orders:
            try:
                await exchange.cancel_order(order['id'], order['symbol'])
                print(f"Cancelled order: {order['id']} for {order['symbol']}")
            except Exception as e:
                print(f"Error cancelling order {order['id']}: {e}")

        if exchange:
            await exchange.close()
    except Exception as e:
        print(f"Error in cancel_user_limit_orders: {e}")
