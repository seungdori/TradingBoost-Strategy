"""Redis 헬퍼 함수"""

import json
from typing import List

from shared.database.redis_patterns import redis_context, RedisTTL


async def set_running_symbols(redis, user_key, symbols):
    """실행 중인 심볼 목록을 업데이트합니다."""
    current_symbols = await redis.hget(user_key, 'running_symbols')
    current_symbols = json.loads(current_symbols.decode('utf-8') if isinstance(current_symbols, bytes) else current_symbols or '[]')
    current_symbols.extend([s for s in symbols if s not in current_symbols])
    await redis.hset(user_key, 'running_symbols', json.dumps(current_symbols))
    print(f"Updated running_symbols: {current_symbols}")


async def check_running_symbols(redis, user_key, symbol):
    """심볼이 실행 중인지 확인합니다."""
    running_symbols = await redis.hget(user_key, 'running_symbols')
    running_symbols = json.loads(running_symbols.decode('utf-8') if isinstance(running_symbols, bytes) else running_symbols or '[]')
    running_symbol = symbol in running_symbols
    print(f"Debug: running_symbols = {running_symbols}, symbol {symbol} in running_symbols: {running_symbol}")
    return running_symbol


async def get_placed_prices(exchange_name: str, user_id: int, symbol_name: str) -> List[float]:
    """배치된 주문 가격 목록을 조회합니다."""
    async with redis_context() as redis:
        redis_key = f'placed_prices:{exchange_name}:{user_id}:{symbol_name}'
        prices = await redis.lrange(redis_key, 0, -1)
        return [float(price) for price in prices]


async def add_placed_price(exchange_name: str, user_id: int, symbol_name: str, price: float) -> None:
    """배치된 주문 가격을 추가합니다."""
    async with redis_context() as redis:
        redis_key = f'placed_prices:{exchange_name}:{user_id}:{symbol_name}'
        await redis.rpush(redis_key, str(price))
        # TTL 설정 - 7일 후 자동 삭제 (ORDER_DATA)
        await redis.expire(redis_key, RedisTTL.ORDER_DATA)


async def is_order_placed(exchange_name: str, user_id: int, symbol_name: str, grid_level: int) -> bool:
    """특정 그리드 레벨에 주문이 배치되었는지 확인합니다."""
    async with redis_context() as redis:
        redis_key = f'order_placed:{exchange_name}:{user_id}:{symbol_name}'
        order_placed = await redis.hget(redis_key, str(grid_level))
        return order_placed is not None and order_placed != b'0'


async def is_price_placed(exchange_name: str, user_id: int, symbol_name: str, price: float, grid_level: int | None = None, grid_num: int = 20) -> bool:
    """특정 가격에 주문이 배치되었는지 확인합니다."""
    placed_prices = await get_placed_prices(exchange_name, user_id, symbol_name)
    return price in placed_prices


async def set_order_placed(exchange_name, user_id, symbol, grid_level, level_index=None):
    """주문 배치 상태를 설정합니다."""
    async with redis_context() as redis:
        redis_key = f'order_placed:{exchange_name}:{user_id}:{symbol}'
        if level_index is not None:
            await redis.hset(redis_key, str(level_index), '1')
        else:
            await redis.hset(redis_key, str(grid_level), '1')
        # TTL 설정 - 7일 후 자동 삭제 (ORDER_DATA)
        await redis.expire(redis_key, RedisTTL.ORDER_DATA)


async def get_order_placed(exchange_name, user_id, symbol, grid_num):
    """주문 배치 상태를 조회합니다."""
    async with redis_context() as redis:
        redis_key = f'order_placed:{exchange_name}:{user_id}:{symbol}'
        order_placed = {}
        for i in range(grid_num):
            value = await redis.hget(redis_key, str(i))
            if value:
                order_placed[i] = value.decode('utf-8') if isinstance(value, bytes) else value
        return order_placed


async def reset_order_placed(exchange_name, user_id, symbol, grid_num):
    """주문 배치 상태를 초기화합니다."""
    async with redis_context() as redis:
        redis_key = f'order_placed:{exchange_name}:{user_id}:{symbol}'
        await redis.delete(redis_key)
        print(f"Reset order_placed for {symbol}")
