"""GRID Trading Bot - Grid Trading Core Logic Module (Refactored)

핵심 그리드 트레이딩 로직 (모듈화됨):
- calculate_grid_levels: 그리드 레벨 계산
- place_grid_orders: 그리드 주문 배치 메인 로직 (오케스트레이션)

상세 로직은 grid_modules에 분리:
- grid_initialization: 초기화 및 설정
- grid_orders: 주문 생성
- grid_entry_logic: 진입 로직 (long/short)
- grid_periodic_logic: 주기적 로직
- grid_monitoring: 주문 모니터링
"""

# ==================== 표준 라이브러리 ====================
import asyncio
import json
import logging
import random
import time
import traceback
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

# ==================== 외부 라이브러리 ====================
import ccxt
import pandas as pd
from ccxt.async_support import NetworkError, ExchangeError

# ==================== 프로젝트 모듈 ====================
from GRID.database import redis_database
from GRID.database.redis_database import (
    get_user,
    update_take_profit_orders_info,
    update_active_grid,
    initialize_active_grid
)
from GRID.main import periodic_analysis
from GRID.routes.logs_route import add_log_endpoint as add_user_log
from GRID.trading.get_minimum_qty import round_to_qty, get_lot_sizes, get_perpetual_instruments
from GRID.trading import instance_manager as instance
from GRID.trading.shared_state import cancel_state, user_keys
from GRID.strategies import strategy
from HYPERRSI import telegram_message
from shared.constants.error import TradingErrorName
from shared.dtos.bot_state import BotStateDto, BotStateKeyDto, BotStateError
from shared.utils import retry_async

# ==================== Core 모듈 ====================
from GRID.core.redis import get_redis_connection
from GRID.core.websocket import log_exception
from GRID.core.exceptions import QuitException, AddAnotherException

# ==================== Services ====================
from GRID.services.balance_service import get_balance_of_symbol, get_position_size
from GRID.services.order_service import (
    fetch_order_with_retry,
    okay_to_place_order,
    get_take_profit_orders_info,
)
from GRID.services.user_management_service import (
    ensure_symbol_initialized,
    ensure_symbol_initialized_old_struc,
    decode_value,
)
from shared.utils import parse_bool

# ==================== Monitoring ====================
from GRID.monitoring.monitor_tp_orders import monitor_tp_orders_websocekts

# ==================== Utils ====================
from shared.utils.exchange_precision import adjust_price_precision, get_price_precision
from GRID.utils.price import get_min_notional, get_order_price_unit_upbit, round_to_upbit_tick_size, get_corrected_rounded_price
from GRID.utils.quantity import calculate_order_quantity
from GRID.utils.redis_helpers import (
    get_order_placed,
    set_order_placed,
    is_order_placed,
    is_price_placed,
    add_placed_price,
    reset_order_placed,
)
from shared.utils import (parse_timeframe, calculate_current_timeframe_start, calculate_next_timeframe_start, calculate_sleep_duration)

# ==================== Grid Modules (새로운 모듈들) ====================
from GRID.trading.grid_modules.grid_initialization import (
    initialize_trading_session,
    get_exchange_instance,
    initialize_symbol_data
)
from GRID.trading.grid_modules.grid_orders import create_long_order
from GRID.trading.grid_modules.grid_entry_logic import long_logic, short_logic
from GRID.trading.grid_modules.grid_periodic_logic import periodic_15m_logic
from GRID.trading.grid_modules.grid_monitoring import check_order_status

logger = logging.getLogger(__name__)


# ==============================================================================
#                          Grid Core Functions
# ==============================================================================

async def calculate_grid_levels(direction, grid_num, symbol, exchange_name, user_id, exchange_instance):
    """그리드 레벨 계산 (래퍼 함수)"""
    try:
        return await periodic_analysis.calculate_grid_logic(
            direction,
            grid_num=grid_num,
            symbol=symbol,
            exchange_name=exchange_name,
            user_id=user_id,
            exchange_instance=exchange_instance
        )
    except Exception as e:
        print(f"{user_id} : Error calculating grid levels for {symbol}: {e}")
        print(traceback.format_exc())
        return None

async def place_grid_orders(symbol, initial_investment, direction, grid_levels, symbol_queue, grid_num,leverage, exchange_name, user_id, force_restart = False):
    global user_keys    
    max_retries = 3
    retry_delay = 5  # seconds
    circulation_count = 0
    print("place grid order로직에 들어감. ", symbol)

    try:
        for attempt in range(max_retries):
            try:
                order_placed = {}
                adx_4h = 0
                redis = await get_redis_connection()
                user_key = f'{exchange_name}:user:{user_id}'
                symbol_key = f'{user_key}:symbol:{symbol}'
                max_notional_value = initial_investment[1]*20
                user_data = await redis.hgetall(user_key)
                symbol_data = await redis.hgetall(symbol_key)
                numbers_to_entry = int(user_data.get(b'numbers_to_entry', b'5').decode())
                position_size = 0.0
                running_symbols = set(json.loads(user_data.get('running_symbols', '[]')))
                completed_symbols = set(json.loads(user_data.get('completed_trading_symbols', '[]')))
                #print(f"Debug: Before update - running_symbols = {running_symbols}")  # 디버그 출력
                await ensure_symbol_initialized(exchange_name, user_id, symbol, grid_num)
                ensure_symbol_initialized_old_struc(user_id, symbol, grid_num)
                await initialize_active_grid(redis, exchange_name, user_id, symbol)
                order_buffer = float((numbers_to_entry / 25))
                temporally_waiting_long_order = False
                temporally_waiting_short_order = False
                symbol_name = symbol
                short_order = None
                price_precision = 0.0
                min_notional = 0.0
                if symbol not in running_symbols:
                    running_symbols.add(symbol)
                    print(f"Debug: Symbol {symbol} added to running_symbols")  # 디버그 출력
                print(f"Debug: After update - running_symbols = {running_symbols}")  # 디버그 출력
                running_symbol = symbol in running_symbols
                await redis.hset(user_key, 'running_symbols', json.dumps(list(running_symbols)))
                print(f"{user_id} : {symbol} Debug: running_symbol = {running_symbol}")  # 디버그 출력
                print(running_symbol)
                long_order = None
                exchange_instance = None
                possible_order_id_keys = ['order_id', 'uuid', 'orderId', 'ordId']
                trading_message = (f"== Grid Trading Strategy Start == \n 심볼 : {symbol_name} 거래소 : {exchange_name}")
                print(trading_message)
                order_id = None
                await add_user_log(user_id, trading_message)
                ws_data = await symbol_queue.get()
                current_price, server_time = ws_data
                current_price = float(current_price)
                over_20_grid = False
                under_1_grid = False
                message_only_at_time = False
                minimum_volatility = True
                message_time_count = 0
                last_execution_time = 0
                order_quantity = initial_investment[0]
                order_quantities = initial_investment
            except Exception as e:
                print(f"An error occurred10000: {e}")
                print(traceback.format_exc())
            try:
                if exchange_name == 'binance':
                    exchange_instance = await instance.get_binance_instance(user_id)
                elif exchange_name == 'binance_spot':
                    exchange_instance = await instance.get_binance_spot_instance(user_id)
                elif exchange_name == 'upbit':
                    exchange_instance = await instance.get_upbit_instance(user_id)
                    direction = 'long'
                elif exchange_name == 'bitget':
                    exchange_instance = await instance.get_bitget_instance(user_id)
                    symbol_name = symbol.replace('USDT', '') + '/USDT:USDT'
                elif exchange_name == 'bitget_spot':
                    exchange_instance = await instance.get_bitget_spot_instance(user_id)
                    symbol_name = symbol.replace('USDT', '') + '/USDT:USDT'
                elif exchange_name == 'okx':
                    #print(f"exchange_name check! : {exchange_name}")
                    try:
                        exchange_instance = await instance.get_okx_instance(user_id)
                        order_quantities = await retry_async(calculate_order_quantity, symbol, initial_investment, current_price, redis)
                        try:
                            await redis.hset(symbol_key, 'order_quantities', json.dumps(order_quantities))
                        except Exception as e:
                            error = str(e)
                            print(f"An error on making redis list: {error}")
                    except Exception as e:
                        print(f"An error occurred17!: {e}")
                        raise Exception("remove")
                elif exchange_name == 'okx_spot':
                    try:
                        exchange_instance = await instance.get_okx_spot_instance(user_id)
                    except Exception as e:
                        print(f"An error occurred16: {e}")
                        raise e
                try:
                    price_precision = await retry_async(get_price_precision, symbol, exchange_instance, redis)
                    min_notional = await retry_async(get_min_notional, symbol_name, exchange_instance, redis)
                except Exception as e:
                    print(f"An error occurred18: {e}")
                    price_precision = 0.0
                    min_notional = 10.0
                try:
                    spot_exchange = False
                    if exchange_name == 'upbit' or exchange_name == 'binance_spot' or exchange_name == 'bitget_spot' or exchange_name == 'okx_spot':
                        spot_exchange = True
                    else:
                        spot_exchange = False
                    grid_level = None
                    upper_levels = []
                    lower_levels = []
                    pnl_percent = 0.0
                    temporally_waiting_long_order = False
                    temporally_waiting_short_order = False
                    current_pnl = 0.0
                    try:
                        order_placed = await get_order_placed(exchange_name, user_id, symbol_name, grid_num)
                        #order_placed = user_keys.get(user_id, {}).get("symbol", {}).get(symbol_name, {}).get("order_placed", {n: False for n in range(0, grid_num + 1)})
                    except Exception as e:
                        print(f"An error occurred1001: {e}")
                        order_placed = {n: False for n in range(0, grid_num + 1)}
                    try:
                        order_ids_key = f'{exchange_name}:user:{user_id}:symbol:{symbol_name}:order_ids'
                        stored_data = await redis.hgetall(order_ids_key)
                        if stored_data:
                            
                            order_ids = {k: decode_value(v) for k, v in stored_data.items()}
                        else:
                            order_ids = {str(n): None for n in range(0, grid_num + 1)}
                    except Exception as e:
                        print(f"An error occurred1002: {e}")
                        order_ids = {str(n): None for n in range(0, grid_num + 1)}
                    level_quantities = user_keys[user_id]["symbols"][symbol_name]["level_quantities"]
                    initial_balance_of_symbol = await retry_async(get_balance_of_symbol,exchange_instance, symbol_name, user_id)
                    last_position_size = 0.0
                    new_position_size = 0.0
                    take_profit_orders_info = await get_take_profit_orders_info(redis, exchange_name, user_id, symbol_name, grid_num, force_restart)
                    quantity_list: list[Any] = []
                    update_flag = True
                    overbought = False
                    oversold = False
                    last_execution_time = 0  # 마지막 실행 시간을 저장할 변수 추가
                    adx_4h = 0
                    try:
                        if not grid_levels.empty and 'adx_state_4h' in grid_levels.columns:
                            adx_4h_series = grid_levels.get('adx_state_4h', pd.DataFrame())
                            adx_4h = adx_4h_series.iloc[-1] if not adx_4h_series.empty else 0
                    except Exception as e:
                        adx_4h = 0
                    is_running = await redis.hset(user_key, 'is_running', '1')
                    #running = user_data.get(b'is_running', b'0').decode() == '1'
                    print(f"Trading started for user {user_id} : {symbol} on {exchange_name}")
                    try:
                        sum_of_initial_capital = sum(initial_investment)
                        max_notional_value = sum_of_initial_capital * 1.05
                    except Exception as e:
                        print(f"An error occurred11: {e}")
                        initial_investment_str = await redis.hget(user_key, 'initial_capital')
                        initial_investment = json.loads(initial_investment_str)
                        sum_of_initial_capital = sum(initial_investment)
                        max_notional_value = sum_of_initial_capital * 1.05 
                    for i in range(grid_num):
                        initial_capital = initial_investment[i]
                        order_quantity = order_quantities[i]
                    active_grid = await redis_database.get_active_grid(redis, exchange_name, user_id, symbol_name)
                    if 'grid_level_20' in grid_levels:
                        grid_levels['grid_level_21'] = grid_levels['grid_level_20'] * (1 + 0.008)
                    if grid_num > 20:
                        for i in range(21, grid_num + 1):
                            grid_levels[f'grid_level_{i}'] = grid_levels['grid_level_20'] * (1 + 0.008 * (i - 20))
                    
                    if 'grid_level_1' in grid_levels:
                        grid_levels['grid_level_0'] = grid_levels['grid_level_1'] * (1 - 0.008)
                    else:
                        await redis_database.remove_running_symbol(user_id, symbol, exchange_name, redis)
                        return False
                except Exception as e:
                    print(f"An error occurred1001: {e}")
                    print(traceback.format_exc())
                running_symbol = symbol in running_symbols

                print(f"running symbol : {running_symbol}")
                print(running_symbols)
                break

            except Exception as e:
                print(f"An error occurred (attempt {attempt + 1}/{max_retries}): {e}")
                print(traceback.format_exc())
                
                if attempt < max_retries - 1:
                    wait_time = retry_delay + random.uniform(0, 2)  # Add some randomness to avoid thundering herd
                    print(f"Retrying in {wait_time:.2f} seconds...")
                    await asyncio.sleep(wait_time)
                else:
                    print("Max retries reached. Failing...")
                    await redis_database.remove_running_symbol(user_id, symbol, exchange_name, redis)
                    return False
        while True:
            try:
                await asyncio.sleep(0.1)
                #is_running = await redis.hget(user_key, 'is_running')
                #is_running = is_running.decode('utf-8') if isinstance(is_running, bytes) else is_running
                #is_running = bool(int(is_running or '0'))
                running_symbols = set(json.loads(await redis.hget(user_key, 'running_symbols') or '[]'))
                running_symbol = symbol in running_symbols

                user_data = await redis.hgetall(user_key)
                is_running = parse_bool(user_data.get('is_running', '0'))
                #print("CHECK CHECK ! ! ",running_symbol)
                if not is_running or not running_symbol:
                    print(f"Stopping loop. is_running: {is_running}, symbol {symbol} in running_symbols: {running_symbol}")
                    break
                ws_data = await symbol_queue.get()
                current_price, server_time = ws_data
                current_price = float(current_price)
                #current_price = await global_price_subscriber.get_current_price(exchange_name, symbol)
                current_time = int(time.time())
                current_minute = current_time // 60 % 60  # 현재 분 계산
                current_second = current_time % 60  # 현재 초 계산
                
                # Redis에서 symbol 관련 데이터 가져오기
                key = f"{exchange_name}:user:{user_id}:symbol:{symbol_name}"

                # 'grid_count'가 없는 경우 0으로 처리하여 합산
                total_grid_count = await redis_database.get_total_grid_count(redis, exchange_name, user_id, symbol_name)
                position_size = await get_position_size('okx', user_id, symbol_name)
                #================================================================================================
                # PERIODIC LOGIC
                #================================================================================================
                if current_minute % 15 == 0 and update_flag:  # 15분마다 한 번씩 실행되도록 수정
                    if current_time - last_execution_time >= 60:  # 마지막 실행 시간과 현재 시간의 차이가 60초 이상인 경우에만 실행
                        try:
                            #order_placed = user_keys.get(user_id, {}).get("symbol", {}).get(symbol_name, {}).get("order_placed", {n: False for n in range(0, grid_num + 1)})
                            order_placed_key = f'orders:{exchange_name}:user:{user_id}:symbol:{symbol}:order_placed'
                            order_placed_data = await redis.hgetall(order_placed_key)
                            order_placed = {}
                        except Exception as e:
                            print(f"An error occurred1001: {e}")
                        order_placed = {n: False for n in range(0, grid_num + 1)}
                        start_time = time.time()
                        await periodic_15m_logic(exchange_name, user_id, symbol_name, symbol, grid_num, price_precision, max_notional_value, initial_investment, order_quantities, direction, take_profit_orders_info, level_quantities, min_notional, adx_4h, overbought, oversold, order_buffer, exchange_instance, redis, possible_order_id_keys, order_ids, total_grid_count,current_price, current_time, position_size, sum_of_initial_capital)
                        end_time = time.time()
                        elapsed_time = end_time - start_time
                        if elapsed_time > 1:
                            print(f"{user_id} : {symbol} 15분 주기 로직 소요 시간: {round(elapsed_time,4)}")
                        update_flag = False
                else:
                    update_flag = True  # 15분이 되면 update_flag를 다시 True로 설정
                #================================================================================================
                # PERIODIC LOGIC END
                #================================================================================================
                try:
                    if grid_levels is None:
                        grid_levels = await periodic_analysis.calculate_grid_logic(direction = direction, grid_num = grid_num, symbol = symbol_name,exchange_name = exchange_name,  user_id = user_id , exchange_instance=exchange_instance)
                    quantity_list = []  # quantity_list 초기화
                    for i in range(grid_num):
                        initial_capital = initial_investment[i]
                        order_quantity = order_quantities[i]
                        if exchange_name == 'upbit':
                            order_price_unit = get_order_price_unit_upbit(current_price)
                            quantity_former = initial_capital / current_price
                            processing_qty = round_to_upbit_tick_size(quantity_former)
                            quantity = processing_qty
                        elif exchange_name == 'okx':
                            quantity = order_quantity
                        else:
                            quantity = (initial_capital / current_price)

                        quantity_list.append(quantity)  # 리스트에 quantity 값 추가

                except Exception as e:
                    print(f"An error occurred on {symbol} calculating order quantity: {e}")
                
                # 가장 가까운 4개의 그리드 레벨 찾기
                # 가장 가까운 4개의 그리드 레벨 찾기
                try:
                    closest_levels = []
                    if grid_num > 20:
                        for i in range(21, grid_num + 1):
                            grid_levels[f'grid_level_{i}'] = grid_levels['grid_level_20'] * (1 + 0.008 * (i - 20))
                    for n in range(0, grid_num + 1):
                        grid_level = grid_levels[f'grid_level_{n}'].iloc[-1]
                        if exchange_name == 'upbit':
                            grid_level = get_corrected_rounded_price(grid_level)
                        else:
                            grid_level = round(grid_level, int(price_precision))
                        closest_levels.append((n, grid_level))

                    closest_levels.sort(key=lambda x: abs(x[1] - current_price))
                    closest_levels = closest_levels[:4]
                    # 상위 2개와 하위 2개의 그리드 레벨 출력
                    upper_levels = [level for level in closest_levels if level[1] >= current_price][:2]
                    lower_levels = [level for level in closest_levels if level[1] < current_price][:2]
                    #print(f"근접 찾기 {symbol} current_price : {current_price}({grid_level}), upper levels: {upper_levels} , lowerlevels : {lower_levels}")
                    if direction == 'long':
                        upper_levels = [level for level in closest_levels if level[1] >= current_price][:1]
                        lower_levels = [level for level in closest_levels if level[1] < current_price][:2]
                    elif direction == 'short':
                        upper_levels = [level for level in closest_levels if level[1] >= current_price][:2]
                        lower_levels = [level for level in closest_levels if level[1] < current_price][:1]
                except Exception as e:
                    print(f"An error occurred on calculating closest levels: {e}")

                #print(f"{symbol} current_price : {current_price}({grid_level}), levels: {upper_levels} , {lower_levels}")

                #-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
                #===========================================숏 주문 생성 로직 시작========================================
                #-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
                short_logic_start_time = time.time()
                try:
                    order_placed = await get_order_placed(exchange_name, user_id, symbol_name, grid_num)
                    #order_placed = user_keys.get(user_id, {}).get("symbol", {}).get(symbol_name, {}).get("order_placed", {n: False for n in range(0, grid_num + 1)})
                    #print(f"{symbol} : order_placed", order_placed)
                except Exception as e:
                    print(f"An error occurred1001: {e}")
                    order_placed = {n: False for n in range(0, grid_num + 1)}
                try:
                    await short_logic(exchange_name, user_id, symbol_name, symbol, upper_levels, current_price, grid_levels, order_placed, grid_num,
                                         price_precision, max_notional_value, initial_investment, order_quantities, quantity_list, new_position_size,
                                         direction, take_profit_orders_info, level_quantities, min_notional, temporally_waiting_short_order,
                                         adx_4h, overbought, oversold, order_buffer, exchange_instance, redis, possible_order_id_keys, order_ids, position_size, over_20_grid)
                except Exception as e:
                    print(f"{user_id} : {symbol} An error occurred on short logic: {e}")
                short_logic_end_time = time.time()
                if short_logic_end_time - short_logic_start_time > 1:
                    print(f"{symbol} 숏 로직 소요 시간: {round(short_logic_end_time - short_logic_start_time,4)}")
                #-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
                #===========================================숏 주문 생성 로직 끝==========================================
                #-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
                current_datetime = datetime.now()
                if current_datetime.minute % 5 == 0 and (current_datetime.second == 0 or current_datetime.second == 1 or current_datetime.second == 2 or current_datetime.second == 3 or current_datetime.second == 4):
                    filtered_order_placed = {k: v for k, v in order_placed.items() if v}
                    print(f'{user_id} : {symbol} order placed list :', filtered_order_placed)
                
                #-------------------------------------------------------------------------------------------------------
                #===========================================롱 주문 생성 로직 시작===========================================
                #-------------------------------------------------------------------------------------------------------
                long_logic_start_time = time.time()

                try:
                    await long_logic(exchange_name, user_id, symbol_name, symbol, lower_levels, current_price, grid_levels, order_placed, grid_num,
                     price_precision, max_notional_value, initial_investment, order_quantities, quantity_list,
                     direction, take_profit_orders_info, level_quantities, min_notional, temporally_waiting_long_order,
                     adx_4h, overbought, oversold, order_buffer, exchange_instance, redis, possible_order_id_keys, order_ids, position_size, under_1_grid)
                except Exception as e:
                    print(f"{user_id} : An error occurred on long logic: {e}")
                long_logic_end_time = time.time()
                if long_logic_end_time - long_logic_start_time > 1 :
                    print(f"{symbol} 롱 로직 소요 시간: {round(long_logic_end_time - long_logic_start_time,4)}")
                await asyncio.sleep(2.5)  # 주문 생성 간격 (예: 1초)

                #current_time = int(time.time())
                #current_minute = current_time // 60 % 60  # 현재 분 계산
                #seconds = current_time % 60  # 현재 초 
                #if current_minute % 1 == 0 and seconds == 0:  # 1분마다 한 번씩 실행되도록 수정
                #    if current_time - last_execution_time > 50:
                #        print(f"순회 확인: {symbol} {current_minute}분 {seconds}초")
                #        circulation_count += 1
                #        print(f"순회 횟수: {circulation_count}")
                #        last_execution_time = time.time()
            except Exception as e:
                error_message = str(e)
                if 'KeyError' in error_message:
                    print(f"KeyError: {error_message}")
                    raise e
                elif 'UnboundLocalError' in error_message:
                    print(f"UnboundLocalError: {error_message}")
                    raise e
                elif "'NoneType' object is not subscriptable" in error_message:
                    print(f"Error placing {symbol} grid orders: {error_message}")
                else:
                    print(f"🟡 :{take_profit_orders_info}")
                    print(f"An error occurred on placing {symbol} grid orders: {error_message}")
                traceback.print_exc()

                

        #================================================================================================
        # 루프 종료
        #================================================================================================
        print('종료.')
        return

    except Exception as e:
        if 'remove' in str(e):
            print(f"{user_id} : remove the symbol {symbol}: {e}")
            await strategy.close(exchange_instance, symbol_name, message = f'{user_id} : 종목을 제거하고 재탐색 합니다.',user_id = user_id,)
            completed_symbols.add(symbol)

            raise Exception(f"remove")
        print(f"An error occurred008: {e}")
        traceback.print_exc()
        return

    finally:
        recovery_mode = False
        try:
            user_key = f'{exchange_name}:user:{user_id}'
            user_data = await redis.hgetall(user_key)
            stop_task_only = parse_bool(user_data.get('stop_task_only', '0'))
        except Exception as e :
            print(f"exception on stop_task_only: {e}")
            stop_task_only = False
        try:
            recovery_state = await redis.get('recovery_state')
            recovery_mode = True if recovery_state == 'True' else False
        except Exception as e:
            print(f"An error occurred: {e}")
            recovery_mode = False
        print(f"recovery_state: {recovery_state}")
        print(f"recovery_mode: {recovery_mode}")
        print(f"stop_task_only: {stop_task_only}")
        if exchange_name is not None:
            if stop_task_only or recovery_mode:
                print(f"{user_id} : stop_task_only 혹은 recovery_mode가 활성화 되어 포지션 종료 없이 {symbol} 심볼 테스크만 취소합니다.")
                
                pass
            else:
                print(f"{user_id} : 포지션 종료")
                await strategy.close(exchange = exchange_name, symbol = symbol_name, user_id = user_id)
            await strategy.cancel_all_limit_orders(exchange_name, symbol_name, user_id)
            #global_messages.trading_message.put(f"{symbol_name}의 모든 주문이 취소되었습니다.")
            message = f"{symbol_name}의 모든 주문이 취소되었습니다."
            #await manager.add_user_message(user_id, message)
            await add_user_log(user_id, message)
            if exchange_instance is not None:
                await exchange_instance.close()
        if not recovery_mode and not stop_task_only:
            completed_symbols.add(symbol)
            running_symbols.remove(symbol)
            await redis.hset(user_key, 'completed_trading_symbols', json.dumps(list(completed_symbols)))
            await redis.hset(user_key, 'running_symbols', json.dumps(list(running_symbols)))
            print(f"{user_id} : {symbol} 종료 후 completed_symbols : {completed_symbols}")
            print(f"{user_id} : {symbol} 종료 후 running_symbols : {running_symbols}")
        #await redis.hset(user_key, 'is_running', '0')
        #await redis.close()
        return
