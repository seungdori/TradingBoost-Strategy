"""GRID Trading Initialization Module

트레이딩 세션 초기화 관련 함수들:
- initialize_trading_session: 트레이딩 세션 초기화
- get_exchange_instance: 거래소 인스턴스 가져오기
- initialize_symbol_data: 심볼 데이터 초기화
"""

from shared.database.redis_patterns import redis_context, RedisTTL
import json
import logging
import traceback
from typing import Any, Dict, Optional, Tuple

import pandas as pd

from GRID.core.redis import get_redis_connection
from GRID.database.redis_database import (
    get_user,
    initialize_active_grid,
    update_active_grid,
    update_take_profit_orders_info,
)
from GRID.routes.logs_route import add_log_endpoint as add_user_log
from GRID.services.balance_service import get_balance_of_symbol
from GRID.services.order_service import get_take_profit_orders_info
from GRID.services.user_management_service import (
    decode_value,
    ensure_symbol_initialized,
    ensure_symbol_initialized_old_struc,
)
from GRID.trading import instance_manager as instance
from GRID.trading.shared_state import cancel_state, user_keys
from GRID.utils.price import get_min_notional
from GRID.utils.quantity import calculate_order_quantity
from GRID.utils.redis_helpers import get_order_placed
from shared.utils import retry_async
from shared.utils.exchange_precision import get_price_precision

logger = logging.getLogger(__name__)


async def initialize_trading_session(
    exchange_name: str,
    user_id: str,
    symbol: str,
    grid_num: int,
    initial_investment: list
) -> Dict[str, Any]:
    """트레이딩 세션 초기화

    Args:
        exchange_name: 거래소 이름
        user_id: 사용자 ID
        symbol: 심볼
        grid_num: 그리드 수
        initial_investment: 초기 투자금

    Returns:
        초기화된 세션 데이터
    """
    try:
        # Redis 연결
        async with redis_context() as redis:
            user_key = f'{exchange_name}:user:{user_id}'
            symbol_key = f'{user_key}:symbol:{symbol}'

            # 사용자 및 심볼 데이터 로드
            user_data = await redis.hgetall(user_key)
            symbol_data = await redis.hgetall(symbol_key)

            # 기본 설정값 추출
            numbers_to_entry = int(user_data.get(b'numbers_to_entry', b'5').decode())
            running_symbols = set(json.loads(user_data.get('running_symbols', '[]')))
            completed_symbols = set(json.loads(user_data.get('completed_trading_symbols', '[]')))

            # 심볼 초기화
            await ensure_symbol_initialized(exchange_name, user_id, symbol, grid_num)
            ensure_symbol_initialized_old_struc(user_id, symbol, grid_num)
            await initialize_active_grid(redis, exchange_name, int(user_id), symbol)

            # running_symbols 업데이트
            if symbol not in running_symbols:
                running_symbols.add(symbol)
                print(f"Debug: Symbol {symbol} added to running_symbols")

            await redis.hset(user_key, 'running_symbols', json.dumps(list(running_symbols)))

            # 로그 메시지
            trading_message = f"== Grid Trading Strategy Start == \n 심볼 : {symbol} 거래소 : {exchange_name}"
            print(trading_message)
            await add_user_log(user_id, trading_message)

            # 세션 데이터 반환
            session_data = {
                'redis': redis,
                'user_key': user_key,
                'symbol_key': symbol_key,
                'user_data': user_data,
                'symbol_data': symbol_data,
                'numbers_to_entry': numbers_to_entry,
                'running_symbols': running_symbols,
                'completed_symbols': completed_symbols,
                'order_buffer': float(numbers_to_entry / 25),
                'max_notional_value': initial_investment[1] * 20,
            }

            return session_data

        except Exception as e:
            print(f"An error occurred in initialize_trading_session: {e}")
            print(traceback.format_exc())
            raise


async def get_exchange_instance(
    exchange_name: str,
    user_id: str,
    symbol: str,
    initial_investment: list,
    current_price: float,
    redis: Any
) -> Tuple[Any, str, list]:
    """거래소 인스턴스 및 관련 데이터 가져오기

    Args:
        exchange_name: 거래소 이름
        user_id: 사용자 ID
        symbol: 심볼
        initial_investment: 초기 투자금
        current_price: 현재 가격
        redis: Redis 연결

    Returns:
        (exchange_instance, symbol_name, order_quantities) 튜플
    """
    symbol_name = symbol
    symbol_key = f'{exchange_name}:user:{user_id}:symbol:{symbol}'
    order_quantities = initial_investment

    try:
        exchange_instance = await instance.get_exchange_instance(exchange_name, user_id)

        if exchange_name in ['bitget', 'bitget_spot']:
            symbol_name = symbol.replace('USDT', '') + '/USDT:USDT'
        elif exchange_name in ['okx', 'okx_spot']:
            order_quantities = await retry_async(
                calculate_order_quantity,
                symbol,
                initial_investment,
                current_price,
                redis
            )
            try:
                await redis.hset(symbol_key, 'order_quantities', json.dumps(order_quantities))
            except Exception as e:
                print(f"An error on making redis list: {e}")

        return exchange_instance, symbol_name, order_quantities

    except Exception as e:
        print(f"An error occurred in get_exchange_instance: {e}")
        raise


async def initialize_symbol_data(
    exchange_name: str,
    user_id: str,
    symbol: str,
    symbol_name: str,
    grid_num: int,
    exchange_instance: Any,
    redis: Any,
    grid_levels: pd.DataFrame,
    force_restart: bool = False
) -> Dict[str, Any]:
    """심볼 데이터 초기화

    Args:
        exchange_name: 거래소 이름
        user_id: 사용자 ID
        symbol: 심볼
        symbol_name: 거래소별 심볼 이름
        grid_num: 그리드 수
        exchange_instance: 거래소 인스턴스
        redis: Redis 연결
        grid_levels: 그리드 레벨 데이터
        force_restart: 강제 재시작 여부

    Returns:
        초기화된 심볼 데이터
    """
    try:
        # 가격 정밀도 및 최소 거래량 가져오기
        price_precision = await retry_async(get_price_precision, symbol, exchange_instance, redis)
        min_notional = await retry_async(get_min_notional, symbol_name, exchange_instance, redis)

        # 거래소 타입 확인
        spot_exchange = exchange_name in ['upbit', 'binance_spot', 'bitget_spot', 'okx_spot']

        # 주문 배치 상태 초기화
        try:
            order_placed = await get_order_placed(exchange_name, user_id, symbol_name, grid_num)
        except Exception as e:
            print(f"An error occurred initializing order_placed: {e}")
            order_placed = {n: False for n in range(0, grid_num + 1)}

        # 주문 ID 초기화
        try:
            order_ids_key = f'{exchange_name}:user:{user_id}:symbol:{symbol_name}:order_ids'
            stored_data = await redis.hgetall(order_ids_key)
            if stored_data:
                order_ids = {k: decode_value(v) for k, v in stored_data.items()}
            else:
                order_ids = {str(n): None for n in range(0, grid_num + 1)}
        except Exception as e:
            print(f"An error occurred initializing order_ids: {e}")
            order_ids = {str(n): None for n in range(0, grid_num + 1)}

        # 레벨별 수량 정보
        level_quantities = user_keys[user_id]["symbols"][symbol_name]["level_quantities"]

        # 초기 잔고 가져오기
        initial_balance_of_symbol = await retry_async(
            get_balance_of_symbol,
            exchange_instance,
            symbol_name,
            user_id
        )

        # 익절 주문 정보 가져오기
        take_profit_orders_info = await get_take_profit_orders_info(
            redis,
            exchange_name,
            user_id,
            symbol_name,
            grid_num,
            force_restart
        )

        # ADX 4H 상태 확인
        adx_4h = 0
        try:
            if not grid_levels.empty and 'adx_state_4h' in grid_levels.columns:
                adx_4h_series = grid_levels.get('adx_state_4h', pd.DataFrame())
                adx_4h = adx_4h_series.iloc[-1] if not adx_4h_series.empty else 0
        except Exception as e:
            logger.warning(f"Error getting ADX 4H state: {e}")
            adx_4h = 0

        # is_running 상태 업데이트
        user_key = f'{exchange_name}:user:{user_id}'
        await redis.hset(user_key, 'is_running', '1')

        symbol_data = {
            'price_precision': price_precision,
            'min_notional': min_notional,
            'spot_exchange': spot_exchange,
            'order_placed': order_placed,
            'order_ids': order_ids,
            'level_quantities': level_quantities,
            'initial_balance_of_symbol': initial_balance_of_symbol,
            'take_profit_orders_info': take_profit_orders_info,
            'adx_4h': adx_4h,
            'overbought': False,
            'oversold': False,
            'upper_levels': [],
            'lower_levels': [],
            'pnl_percent': 0.0,
            'temporally_waiting_long_order': False,
            'temporally_waiting_short_order': False,
            'current_pnl': 0.0,
        }

        return symbol_data

    except Exception as e:
        print(f"An error occurred in initialize_symbol_data: {e}")
        print(traceback.format_exc())
        # 기본값 반환
        return {
            'price_precision': 0.0,
            'min_notional': 10.0,
            'spot_exchange': False,
            'order_placed': {n: False for n in range(0, grid_num + 1)},
            'order_ids': {str(n): None for n in range(0, grid_num + 1)},
            'level_quantities': {},
            'initial_balance_of_symbol': 0.0,
            'take_profit_orders_info': {},
            'adx_4h': 0,
            'overbought': False,
            'oversold': False,
            'upper_levels': [],
            'lower_levels': [],
            'pnl_percent': 0.0,
            'temporally_waiting_long_order': False,
            'temporally_waiting_short_order': False,
            'current_pnl': 0.0,
        }
