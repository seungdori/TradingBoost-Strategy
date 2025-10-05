"""GRID Trading Bot - Grid Trading Core Logic Module

핵심 그리드 트레이딩 로직:
- calculate_grid_levels: 그리드 레벨 계산
- create_short_orders: 숏 주문 생성
- place_grid_orders: 그리드 주문 배치 메인 로직
- periodic_15m_logic: 15분 주기 로직
- long_logic: 롱 진입 로직
- short_logic: 숏 진입 로직
- check_order_status: 주문 상태 모니터링
"""

# ==================== 표준 라이브러리 ====================
import asyncio
import json
import logging
import random
import traceback
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

# ==================== 외부 라이브러리 ====================
import ccxt
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
from GRID.trading.instance_manager import get_exchange_instance
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
)

# ==================== Utils ====================
from GRID.utils.precision import adjust_price_precision, get_price_precision
from GRID.utils.price import get_min_notional
from GRID.utils.redis_helpers import (
    get_order_placed,
    set_order_placed,
    is_order_placed,
    is_price_placed,
    add_placed_price,
    reset_order_placed,
)
from shared.utils import (parse_timeframe, calculate_current_timeframe_start, calculate_next_timeframe_start, calculate_sleep_duration)

logger = logging.getLogger(__name__)


# ==============================================================================
#                          Grid Core Functions
# ==============================================================================

async def calculate_grid_levels(direction, grid_num, symbol, exchange_name, user_id, exchange_instance):
    try:
        return await periodic_analysis.calculate_grid_logic(direction, grid_num=grid_num, symbol=symbol, exchange_name=exchange_name, user_id=user_id, exchange_instance=exchange_instance)
    except Exception as e:
        print(f"{user_id} : Error calculating grid levels for {symbol}: {e}")
        print(traceback.format_exc())
        return None


async def create_short_orders(exchange_instance, symbol, short_level, adjusted_quantity, min_quantity, user_id, reduce_only=False):
    try:
        if reduce_only:
            short_order = await exchange_instance.create_order(
                symbol=symbol,
                type='limit',
                side='sell',
                amount= max(adjusted_quantity, min_quantity),
                price=short_level,
                params={'reduceOnly': True}
            )
            print(f'{symbol} long direction short_order11✔︎')
        else:
            short_order = await exchange_instance.create_order(
                symbol=symbol,
                type='limit',
                side='sell',
                amount= max(adjusted_quantity, min_quantity),
                price=short_level
            )
            print(f"{user_id} : {symbol} direction short_order22✔︎")
        
        return short_order
    except Exception as e:
        
        print(f"{user_id} : An error occurred in create_short_orders2: {e}")

        raise e


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
                        raise "remove"
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
                        stored_data = await redis_client.hgetall(order_ids_key)
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
                    quantity_list = []
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
                if current_price is None:
                    print(f"Error: 🔴current_price is None. Skipping this iteration.")
                    continue
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
                current_time = datetime.now()
                if current_time.minute % 5 == 0 and (current_time.second == 0 or current_time.second == 1 or current_time.second == 2 or current_time.second == 3 or current_time.second == 4):
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
                print(traceback.print_exc())

                

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
        print(traceback.print_exc())
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
        



async def periodic_15m_logic(exchange_name, user_id, symbol_name, symbol, grid_num, price_precision, max_notional_value, initial_investment, order_quantities, direction, take_profit_orders_info, level_quantities, min_notional, adx_4h, overbought, oversold, order_buffer, exchange_instance, redis, possible_order_id_keys, order_ids, total_grid_count,current_price, current_time, position_size, sum_of_initial_capital):
    
    current_timestamp = int(time.time())
    temporally_waiting_short_order = False
    print(f"{symbol} 이 15분로직에 들어옴")
    #last_placed_price = {n: 0.0 for n in range(0, grid_num + 1)}
    await reset_order_placed(exchange_name, user_id, symbol_name, grid_num)
    print(f"현재 {symbol}의 그리드 카운트 총 합 : {total_grid_count}")
    await asyncio.sleep(0.1)
    #print(f"{symbol}의 current price: {current_price}, currnet_time : {current_time}, server_time : {server_time}")
    print(f"{symbol}의 current price: {current_price}, currnet_time : {current_time}")
    # 그리드 레벨 업데이트
    try:
        await asyncio.sleep(random.random())
        if exchange_name == 'okx' or exchange_name == 'okx_spot':
            grid_levels = await periodic_analysis.calculate_grid_logic(direction, grid_num = grid_num, symbol = symbol, exchange_name = exchange_name, user_id = user_id, exchange_instance=exchange_instance)
        else:
            grid_levels = await periodic_analysis.calculate_grid_logic(direction, grid_num = grid_num, symbol = symbol, exchange_name = exchange_name, user_id = user_id, exchange_instance=exchange_instance)
    except Exception as e:
        print(f"An error in getting {symbol} Dataframe: {e}")
        await asyncio.sleep(3)
        grid_levels =await periodic_analysis.calculate_grid_logic(direction, grid_num = grid_num, symbol = symbol, exchange_name = exchange_name, user_id = user_id, exchange_instance=exchange_instance)
    end_timestamp = int(time.time())
    elapsed_time = end_timestamp - current_timestamp
    print(f"🐻🌟🥇{symbol} Elapsed time 000 : {elapsed_time} seconds")
    if grid_levels is None:
    #    await redis_database.remove_running_symbol(user_id, symbol, exchange_name, redis)
        print(f"🔴{user_id} : {symbol} : 종목을 제대로 받아올 수 없음. 확인 필요.")
        await asyncio.sleep(20)
    #    raise Exception("remove")
    if not grid_levels.empty:
        # grid_level_0와 grid_level_21 추가
        grid_levels.loc[:, 'grid_level_0'] = grid_levels['grid_level_1'] * (1 - 0.008)
        grid_levels.loc[:, 'grid_level_21'] = grid_levels['grid_level_20'] * (1 + 0.008)
        # grid_num이 20보다 큰 경우 추가 레벨 계산
        if grid_num > 20:
            for i in range(21, grid_num + 1):
                grid_levels.loc[:, f'grid_level_{i}'] = grid_levels['grid_level_20'] * (1 + 0.008 * (i - 20))
        
        # ADX 4H 상태 확인
        if 'adx_state_4h' in grid_levels.columns:
            adx_4h = grid_levels['adx_state_4h'].iloc[-1]
        else:
            adx_4h = 0
            print(f"Error: 🔴ADX 4H state not found in grid_levels for {symbol}. Setting ADX 4H to 0.")
    else:
        await asyncio.sleep(2)
        #raise ValueError("grid_levels is empty")
    
    # 기존 주문 취소
    try:
        current_time = int(time.time())
        current_minute = current_time // 60 % 60  # 현재 분 계산
        current_second = current_time % 60  # 현재 초 계산
        order_placed = {n: False for n in range(0, grid_num + 1)}

        current_position_size = await get_balance_of_symbol(exchange_instance, symbol_name, user_id)
        
        # Redis에서 symbol 관련 데이터 가져오기
        user_key = f'{exchange_name}:user:{user_id}'
        user_data = await redis.hgetall(user_key)
        symbol_key = f'{user_key}:symbol:{symbol_name}'
        #symbol_data = json.loads(await redis.hget(symbol_key, 'data') or '{}')
        take_profit_orders_info = await get_take_profit_orders_info(redis, exchange_name, user_id, symbol_name, grid_num, force_restart=False)
        initial_balance = 0.0
        #initial_balance = user_data.get('initial_balance', 0)
        #<-- Initial Balance를 제거
        #previous_position_size = symbol_data.get('previous_new_position_size', 0) #<--p- 당장 key문제.

        new_position_size = (current_position_size) if current_position_size is not None else 0.0 #<-- 우선, OKX선물만 진행하니까, Initial Balance를 제거. 
        ordered_position_size = 0.0
        last_entry_size = new_position_size - user_keys[user_id]["symbols"][symbol]["previous_new_position_size"]
        user_keys[user_id]["symbols"][symbol]["last_entry_size"] = new_position_size
        user_keys[user_id]["symbols"][symbol]["previous_new_position_size"] = new_position_size
        #print(f"{symbol}의 현재 포지션 사이즈 : {last_entry_size}, 마지막 진입 사이즈 : {last_entry_size}") 
        if exchange_name == 'upbit' or exchange_name == 'binance_spot' or exchange_name == 'bitget_spot' or exchange_name == 'okx_spot':
            if new_position_size < 0.0:
                initial_balance_of_symbol = 0.0
        try:
            maxi_position_size = (sum_of_initial_capital / current_price)
        except Exception as e:
            initial_investment = json.loads(await redis.hget(user_key, 'initial_capital'))
            sum_of_initial_capital = sum(initial_investment)
            maxi_position_size = (sum_of_initial_capital / current_price)
        if (new_position_size) > maxi_position_size*0.95:
            overbought = True
            if current_minute % 60 == 0:
                print(f"현재 포지션 사이즈 : {new_position_size}, 최대 롱 포지션 사이즈 : {maxi_position_size}")

        elif (new_position_size < -maxi_position_size*0.95):
            oversold = True
            if current_minute % 60 == 0:
                print(f"현재 포지션 사이즈 : {new_position_size}, 최대 숏 포지션 사이즈 : -{maxi_position_size}")
        else:
            overbought = False
            oversold = False
    except Exception as e:
        print(f"{user_id} : An error occurred105: {e}")
        print(traceback.format_exc())
        overbought = False
        oversold = False
    end_timestamp = int(time.time())
    elapsed_time = end_timestamp - current_timestamp
    print(f"😇{symbol} Elapsed time 01 : {elapsed_time} seconds")
    ### 익절 주문 로직 ###
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
        print(f"15분 로직 {symbol} current_price : {current_price}({grid_level}), levels: {upper_levels} , {lower_levels}")
        if direction == 'long':
            upper_levels = [level for level in closest_levels if level[1] > current_price][:1]
            lower_levels = [level for level in closest_levels if level[1] <= current_price][:2]
        elif direction == 'short':
            upper_levels = [level for level in closest_levels if level[1] >= current_price][:2]
            lower_levels = [level for level in closest_levels if level[1] < current_price][:1]
    except Exception as e:
        print(f"{user_id} : An error occurred on 익절 계산 로직: {e}")
    try:
        #print(type(level))
        orders_count = 0 
        max_orders = 4
        if (abs(new_position_size) > 0.0) or abs(last_entry_size > 0.0):
            tp_order_side = 'sell' if new_position_size > 0 else 'buy'
            if new_position_size == 0.0:
                tp_order_side = 'sell' if last_entry_size > 0 else 'buy'
            print(f"{symbol} 익절 주문 사이드 : {tp_order_side}")
            #print(f"{symbol} 익절 주문 정보 : {take_profit_orders_info}")
            #for level, info in user_keys[user_id]["symbols"][symbol_name]["take_profit_orders_info"].items(): # <--원본. 07181640

            for level, info in take_profit_orders_info.items(): 
                level_index = int(level)  # level을 정수로 변환
                level_str = str(level)
                #if (direction == 'long-short' and position_size != 0) or info["active"]: #<-- Take Profit Order Info에서, 익절주문이 활성화되는 경우.
                if info["active"]: #<-- Take Profit Order Info에서, 익절주문이 활성화되는 경우.
                    saved_quantity = info['quantity']
                    if info["active"]:
                        print(f"{symbol}의 {level}번째 active된 익절 주문 정보 : {info}. 현재 포지션 사이즈 : {new_position_size}")
                    
                        print(f"{symbol}이 {level}에서 활성화된 익절 주문이 있습니다. 정보 : {info}")
                    if saved_quantity == 0.0 and info["active"]:
                        print(f"{level}에서 활성화된 익절 주문이 있지만, 수량이 0입니다. 정보 : {info}")
                        await telegram_message.send_telegram_message(f"{symbol}에서 {level}에서 활성화된 익절 주문이 있지만, 수량이 0입니다. 정보 : {info}", exchange_name, debug = True)
                        #continue
                    await asyncio.sleep(random.uniform(0.05, order_buffer+0.1))
                    try:
                        if level_index > 1 and level_index < int(grid_num):
                            new_price = grid_levels[f'grid_level_{level_index-1}'].iloc[-1] if tp_order_side == 'buy' else grid_levels[f'grid_level_{level_index+1}'].iloc[-1]
                            if isinstance(new_price, tuple):
                                print(f"Level: {level_index}, tp_order_side: {tp_order_side}, price is a tuple: {new_price}")
                                new_price = float(new_price) if not isinstance(new_price, tuple) else float(new_price[0])
                            else:
                                if level_index > 1 and level_index < int(grid_num):
                                    new_price = float(grid_levels[f'grid_level_{level_index-1}'].iloc[-1]) if tp_order_side == 'buy' else float(grid_levels[f'grid_level_{level_index+1}'].iloc[-1])
                                    if isinstance(new_price, tuple):
                                        print(f"🔥튜플1 Level: {level_index}, tp_order_side: {tp_order_side}, price is a tuple: {new_price}")
                                        new_price = float(new_price[0])  # 튜플의 첫 번째 값을 사용
                                    else:
                                        new_price = float(new_price)
                                elif level_index == 1 and tp_order_side == 'buy':
                                    new_price = float(grid_levels[f'grid_level_{1}'].iloc[-1])*0.99
                                    if instance(new_price, tuple):
                                        print(f"🔥튜플2 Level: {level}, tp_order_side: {tp_order_side}, price is a tuple: {new_price}")
                                        new_price = float(new_price[0])
                                elif level_index == grid_num and tp_order_side == 'sell':
                                    new_price = float(grid_levels[f'grid_level_{grid_num}'].iloc[-1])*1.01
                                    if isinstance(new_price, tuple):
                                        print(f"🔥튜플3 Level: {level_index}, tp_order_side: {tp_order_side}, price is a tuple: {new_price}")
                                        new_price = float(new_price[0])
                                        # 디버깅을 위해 추가된 출력
                                    print(f"Level: {level_index}, new_price: {new_price}, info: {info}")
                    except Exception as e:
                        print(f"{user_id} : An error occurred on tp order23 : {e}")
                        traceback.print_exc()
                    try:
                        #take_profit_side = 'buy' if take_profit_orders_info.get(level, {}).get('side') == 'buy' else 'sell'
                        #take_profit_side = 'buy' if user_keys[user_id]["symbols"][symbol_name]["take_profit_orders_info"][level]['side'] == 'buy' else 'sell'# <-- 이게 원본07181642
                        take_profit_side = 'buy' if info['side'] == 'buy' else 'sell'
                        okay_to_order = await okay_to_place_order(exchange_name, user_id, symbol, new_price, max_notional_value, order_direction = tp_order_side)
                        if (okay_to_order):
                            if (current_price > new_price) and (take_profit_side == 'sell'):
                                new_price = current_price*(1 + 0.007*orders_count)
                            elif (current_price < new_price) and (take_profit_side == 'buy'):
                                new_price = current_price*(1 - 0.007*orders_count)
                            if ((current_price < new_price) and (take_profit_side == 'sell')) or ((current_price > new_price) and (take_profit_side == 'buy')) and orders_count < max_orders : 
                                if (not await is_price_placed(exchange_name, user_id, symbol, new_price, grid_level = level_index)) and (not await is_order_placed(exchange_name, user_id, symbol, level)):
                                    await asyncio.sleep(random.uniform(0.05, order_buffer+0.5))
                                    print(f"{symbol}이 order_buffer만큼 대기합니다1. {order_buffer}")
                                    if exchange_name == 'upbit':
                                        new_price = get_corrected_rounded_price(new_price)
                                    else:
                                        new_price = round(new_price, price_precision)
                                    if exchange_name == 'bitget':
                                        tp_order = await exchange_instance.create_order(
                                            symbol=symbol_name,
                                            type='limit',
                                            side=tp_order_side, #<-- side는, 이전 주문의 반대로 해야함. 일단은 sell 설정.
                                            amount=info["quantity"],
                                            price=new_price,
                                            params={
                                            'contract_type': 'swap',
                                            'position_mode': 'single',
                                            'marginCoin': 'USDT',
                                            'reduce_only': True
                                            }
                                        )
                                    elif exchange_name == 'binance':
                                        try:
                                            tp_order = await exchange_instance.create_order(
                                                symbol=symbol_name,
                                                type='limit',
                                                side=tp_order_side, 
                                                amount=abs(info["quantity"]),
                                                price=new_price,
                                                params={'reduceOnly': True}
                                            )
                                        except Exception as e:
                                            if ('margin' in str(e)) or ('Insufficient' in str(e)):
                                                print(f"{user_id} : An error occurred on tp order : {e}")
                                                temporally_waiting_long_order = True
                                                temporally_waiting_short_order = True
                                            else:
                                                print(f"{user_id} : An error occurred on tp order : {e}")
                                    elif exchange_name == 'binance_spot':
                                        try:
                                            tp_order = await exchange_instance.create_order(
                                                symbol=symbol_name,
                                                type='limit',
                                                side='sell', #<-- 현물이므로, sell 설정.
                                                amount=info["quantity"],
                                                price=new_price
                                            )
                                        except Exception as e:
                                            print(f"{user_id} : An error occurred18: {e}")
                                    elif exchange_name == 'okx':
                                        try:
                                            tp_order = await exchange_instance.create_order(
                                                symbol=symbol_name,
                                                type='limit',
                                                side=tp_order_side, #<-- side는, 이전 주문의 반대로 해야함. 일단은 sell 설정.
                                                amount=abs(info["quantity"]),
                                                price=new_price,
                                                params={'reduceOnly': True}
                                            )
                                            print('tp_order09')
                                        except Exception as e:
                                            if 'margin' in str(e) or 'insufficient' in str(e):
                                                print(f"{user_id} : An error occurred on tp order : {e}")
                                                temporally_waiting_long_order = True
                                                temporally_waiting_short_order = True
                                            else:
                                                print(f"{user_id} : An error occurred on tp order : {e}")
                                    elif exchange_name == 'okx_spot':
                                        print('exchange okx_spot')
                                        try:
                                            tp_order = await exchange_instance.create_order(
                                                symbol=symbol_name,
                                                type='limit',
                                                side='sell', #<-- side는, 현물이므로 sell.
                                                amount=info["quantity"],
                                                price=new_price,
                                            )

                                        except Exception as e:
                                            print(f"An error occurred on limitorder: {e}")
                                    elif exchange_name == 'bitget_spot':
                                        tp_order = await exchange_instance.create_order(
                                            symbol=symbol_name,
                                            type='limit',
                                            side='sell', #<-- side는, 이전 주문의 반대로 해야함. 일단은 sell 설정.
                                            amount=info["quantity"],
                                            price=new_price,
                                        )
                                    elif exchange_name == 'upbit':
                                        try:
                                            print(f"amount 확인 : {info['quantity']}. new_price : {new_price}")
                                            if info['quantity'] <= 0:
                                                print(f'🚨익절물량이 0보다 작으므로 확인해봐야한다. 함수 시작saved : {saved_quantity}')
                                                await telegram_message.send_telegram_message(f'🚨{symbol}의 {level} 익절물량이 0보다 작으므로 확인해봐야한다. 함수 시작saved : {saved_quantity}', exchange_name = 'upbit', user_id = user_id, debug = True)

                                            tp_order = await retry_async(strategy.place_order, exchange = exchange_instance, symbol=symbol_name,order_type='limit',side='sell',amount=info["quantity"],price=new_price)
                                        except Exception as e: 
                                            print(f"{user_id} : An error occurred for tp : {e}")
                                            return
                                    else:
                                        print(f"{symbol}에서, {exchange_name}가 이상하게 설정됨..")
                                        tp_order = await exchange_instance.create_order(
                                            symbol=symbol_name,
                                            type='limit',
                                            side=tp_order_side, #<-- 여기, side는 이전 주문의 반대로 설정해야함
                                            amount=info["quantity"],
                                            price=new_price
                                        )
                                        print('tp_orer10')
                                    for key in possible_order_id_keys:
                                        if tp_order is not None and 'info' in tp_order and key in tp_order['info']:
                                            order_id = tp_order['info'][key]
                                            break
                                    try:
                                        asyncio.create_task(monitor_tp_orders_websocekts(exchange_name,symbol_name ,user_id, level, take_profit_orders_info))
                                        await add_placed_price(exchange_name, user_id, symbol, new_price)
                                        await set_order_placed(exchange_name, user_id, symbol, grid_level, level_index=level_index)
                                        print(f"🔥여기에서, grid_level이 어떻게 표현되는지 확인. {grid_level}")
                                        
                                        #take_profit_orders_info = user_keys[user_id]["symbols"][symbol_name]["take_profit_orders_info"]
                                        #user_keys[user_id]["symbols"][symbol_name]["take_profit_orders_info"][level]['order_id'] = order_id
                                        #user_keys[user_id]["symbols"][symbol_name]["take_profit_orders_info"][level]['target_price'] = new_price
                                        #user_keys[user_id]["symbols"][symbol_name]["take_profit_orders_info"][level]['quantity'] = (info["quantity"])
                                        #user_keys[user_id]["symbols"][symbol_name]["take_profit_orders_info"][level]['active'] = True
                                        take_profit_orders_info[level_str].update({
                                            'order_id': order_id,
                                            'target_price': new_price,
                                            'quantity': info["quantity"],
                                            'active': True
                                        })
                                        print(f"{symbol}의 {level}번째 익절 주문이 활성화되었습니다. 정보 : {take_profit_orders_info[str(level)]}")
                                        await update_take_profit_orders_info(redis, exchange_name,user_id,symbol_name,level,order_id,new_price,info["quantity"], active = True, side = tp_order_side)
                                        #symbol_data['take_profit_orders_info'] = take_profit_orders_info
                                        #await redis.hset(symbol_key, 'take_profit_orders_info', json.dumps(symbol_data))
                                        order_placed[level] = True
                                        orders_count += 1  # 주문 생성 후 수를 증가
                                        print(f" {symbol}의 order count : {orders_count}")
                                    except Exception as e:
                                        print(f"{user_id} : An error occurred on tp order 15m logic : {e}")
                                        #raise e

                            elif ((current_price < new_price) and (take_profit_side == 'buy')) and (not await is_price_placed(exchange_name, user_id, symbol_name, new_price, grid_level = level)): #<-- 숏 주문에 대한 익절 주문 가격 설정
                                if level > 1:
                                    new_price = float(grid_levels[f'grid_level_{level-1}'].iloc[-1])
                                    print(f"분기5. 숏 주문에 대한 new_price : {new_price}")
                                elif level == 1:
                                    new_price = float(grid_levels[f'grid_level_{1}'].iloc[-1])*0.993
                                    print(f"분기6. 숏 주문에 대한 new_price : {new_price}")
                                else:
                                    new_price = float(current_price)*0.995
                                    print(f"분기7. 숏 주문에 대한 new_price : {new_price}. current_price : {current_price}")
                                if exchange_name == 'upbit':
                                    new_price = get_corrected_rounded_price(new_price)
                                else:
                                    new_price = round(new_price, price_precision)
                                if exchange_name == 'bitget':
                                    tp_order = await exchange_instance.create_order(
                                        symbol=symbol_name,
                                        type='limit',
                                        side='buy', #<-- side는, 이전 주문의 반대로 해야함. 일단은 sell 설정.
                                        amount=abs(info["quantity"]),
                                        price=new_price,
                                        params={
                                        'contract_type': 'swap',
                                        'position_mode': 'single',
                                        'marginCoin': 'USDT',
                                        'reduce_only': True
                                        }
                                    )
                                elif exchange_name == 'binance':
                                    try:
                                        tp_order = await exchange_instance.create_order(
                                            symbol=symbol_name,
                                            type='limit',
                                            side=take_profit_side, 
                                            amount=abs(info["quantity"]),
                                            price=new_price,
                                            params={'reduceOnly': True}
                                        )
                                    except Exception as e:
                                        print(f"An error occurred on tp order : {e}")
                                elif exchange_name == 'okx':
                                    try:
                                        tp_order = await exchange_instance.create_order(
                                            symbol=symbol_name,
                                            type='limit',
                                            side=take_profit_side, #<-- side는, 이전 주문의 반대로 해야함. 일단은 sell 설정.
                                            amount=abs(info["quantity"]),
                                            price=new_price,
                                            params={'reduceOnly': True}
                                        )
                                        await add_placed_price(exchange_name, user_id, symbol_name, price=new_price)
                                        await set_order_placed(exchange_name, user_id, symbol_name, new_price, level_index = level_index)
                                        print('tp_order11')
                                    except Exception as e:
                                        print(f"{user_id} : An error occurred on limitorder: {e}")
                                else:
                                    tp_order = await exchange_instance.create_order(
                                        symbol=symbol_name,
                                        type='limit',
                                        side=take_profit_side, #<-- 여기, side는 이전 주문의 반대로 설정해야함
                                        amount=info["quantity"],
                                        price=new_price
                                    )
                                for key in ['order_id', 'uuid', 'orderId', 'ordId']:
                                    if 'info' in tp_order and key in tp_order['info']:
                                        order_id = tp_order['info'][key]
                                        break
                                asyncio.create_task(monitor_tp_orders_websocekts(exchange_name,symbol_name ,user_id, level, take_profit_orders_info))
                                #user_keys[user_id]["symbols"][symbol_name]["take_profit_orders_info"][level]['order_id'] = order_id
                                #user_keys[user_id]["symbols"][symbol_name]["take_profit_orders_info"][level]['target_price'] = new_price
                                #user_keys[user_id]["symbols"][symbol_name]["take_profit_orders_info"][level]['quantity'] = (info["quantity"])
                                #user_keys[user_id]["symbols"][symbol_name]["take_profit_orders_info"][level]['active'] = True
                                take_profit_orders_info[str(level)].update({
                                            'order_id': order_id,
                                            'target_price': new_price,
                                            'quantity': info["quantity"],
                                            'active': True
                                        })
                                await add_placed_price(exchange_name, user_id, symbol, new_price)
                                await set_order_placed(exchange_name, user_id, symbol, new_price, level_index = level_index)
                                await update_take_profit_orders_info(redis, exchange_name,user_id,symbol_name,level,order_id,new_price,info["quantity"], True, side = take_profit_side)
                                order_placed[level_index] = True
                                orders_count += 1  # 주문 생성 후 수를 증가

                            elif ((current_price > new_price) and (take_profit_side == 'sell')) :
                                if level < grid_num:
                                    new_price = float(grid_levels[f'grid_level_{level+1}'].iloc[-1])
                                elif level == grid_num:
                                    new_price = float(grid_levels[f'grid_level_{grid_num}'].iloc[-1])*1.007
                                else:
                                    new_price = float(current_price)*1.005
                                if exchange_name == 'upbit':
                                    new_price = get_corrected_rounded_price(new_price)
                                else:
                                    new_price = round(new_price, price_precision)
                                if exchange_name == 'bitget':
                                    tp_order = await exchange_instance.create_order(
                                        symbol=symbol_name,
                                        type='limit',
                                        side=take_profit_side, #<-- side는, 이전 주문의 반대로 해야함. 일단은 sell 설정.
                                        amount=info["quantity"],
                                        price=new_price,
                                        params={
                                        'contract_type': 'swap',
                                        'position_mode': 'single',
                                        'marginCoin': 'USDT',
                                        'reduce_only': True
                                        }
                                    )
                                elif exchange_name == 'binance':
                                    try:
                                        tp_order = await exchange_instance.create_order(
                                            symbol=symbol_name,
                                            type='limit',
                                            side=take_profit_side, 
                                            amount=info["quantity"],
                                            price=new_price,
                                            params={'reduceOnly': True}
                                        )
                                    except Exception as e:
                                        print(f"An error occurred on tp order : {e}")
                                elif exchange_name == 'binance_spot':
                                    try:
                                        tp_order = await exchange_instance.create_order(
                                            symbol=symbol_name,
                                            type='limit',
                                            side='sell', #<-- 현물이므로, sell 설정.
                                            amount=info["quantity"],
                                            price=new_price
                                        )
                                    except Exception as e:
                                        print(f"An error occurred20: {e}")
                                elif exchange_name == 'okx':
                                    try:
                                        tp_order = await exchange_instance.create_order(
                                            symbol=symbol_name,
                                            type='limit',
                                            side=take_profit_side, #<-- side는, 이전 주문의 반대로 해야함. 일단은 sell 설정.
                                            amount=info["quantity"],
                                            price=new_price
                                        )
                                    except Exception as e:
                                        if 'margin' in str(e) or 'insufficient' in str(e):
                                            print(f"{user_id} : An error occurred on tp order : {e}")
                                            temporally_waiting_long_order = True
                                            temporally_waiting_short_order = True
                                        else:
                                            print(f"{user_id} : An error occurred on limitorder: {e}")
                                elif exchange_name == 'okx_spot':
                                    print('exchange okx_spot')
                                    try:
                                        tp_order = await exchange_instance.create_order(
                                            symbol=symbol_name,
                                            type='limit',
                                            side='sell', #<-- side는, 현물이므로 sell.
                                            amount=info["quantity"],
                                            price=new_price,
                                        )

                                    except Exception as e:
                                        print(f"An error occurred on limitorder: {e}")
                                elif exchange_name == 'bitget_spot':
                                    tp_order = await exchange_instance.create_order(
                                        symbol=symbol_name,
                                        type='limit',
                                        side='sell', #<-- side는, 이전 주문의 반대로 해야함. 일단은 sell 설정.
                                        amount=info["quantity"],
                                        price=new_price,
                                    )
                                elif exchange_name == 'upbit':
                                    try:
                                        tp_order = await retry_async(strategy.place_order, exchange = exchange_instance, symbol=symbol_name,order_type='limit',side='sell',amount=info["quantity"],price=new_price)
                                    except Exception as e: 
                                        print(f"An error occurred for tp : {e}")
                                        raise e
                                else:
                                    tp_order = await exchange_instance.create_order(
                                        symbol=symbol_name,
                                        type='limit',
                                        side=take_profit_side, #<-- 여기, side는 이전 주문의 반대로 설정해야함
                                        amount=info["quantity"],
                                        price=new_price
                                    )
                                for key in possible_order_id_keys:
                                    if 'info' in tp_order and key in tp_order['info']:
                                        order_id = tp_order['info'][key]
                                        break
                                #user_keys[user_id]["symbols"][symbol_name]["take_profit_orders_info"][level]['order_id'] = order_id
                                #user_keys[user_id]["symbols"][symbol_name]["take_profit_orders_info"][level]['target_price'] = new_price
                                #user_keys[user_id]["symbols"][symbol_name]["take_profit_orders_info"][level]['quantity'] = info["quantity"]
                                #user_keys[user_id]["symbols"][symbol_name]["take_profit_orders_info"][level]['active'] = True
                                await update_take_profit_orders_info(redis, exchange_name,user_id,symbol_name,level,order_id,new_price,info["quantity"], active = True, side = take_profit_side)
                                order_placed[level] = True
                                await add_placed_price(exchange_name, user_id, symbol_name, price=new_price)
                                await set_order_placed(exchange_name, user_id, symbol_name, new_price, level_index = level)
                                await asyncio.sleep(random.uniform(0.05, order_buffer+0.1))
                                asyncio.create_task(monitor_tp_orders_websocekts(exchange_name,symbol_name , user_id, level, take_profit_orders_info))
                                orders_count += 1  # 주문 생성 후 수를 증가
                            else:
                                pass
                                #print(f"level: {level}, current_price: {current_price}, new_price: {new_price}, take_profit_side: {take_profit_side}, symbol: {symbol_name}, orders_count: {orders_count}")
                        
                    except Exception as e:
                        print(f'{user_id} 1: An error occurred on tp order(long): {e}')
                        
                elif (new_position_size > 0.0 ) and not take_profit_orders_info[str(level)]["active"] and float(take_profit_orders_info[str(level)]["quantity"]) > 0.0:
                    await asyncio.sleep(random.uniform(0.05, order_buffer+0.1))
                    try:

                        if isinstance(upper_levels[0], tuple):
                            print(f"튜플로 나오는 것 확인. {upper_levels[0]}")
                            new_price = float(upper_levels[0][1])
                            print(f'적용 후 {new_price}')
                        else:
                            new_price = float(upper_levels[0])
                        #print("quantity 확인" ,take_profit_orders_info[level]["quantity"])
                        tp_order = await exchange_instance.create_order(
                            symbol=symbol_name,
                            type='limit',
                            side='sell',
                            #amount=take_profit_orders_info[level]["quantity"],
                            amount=float(info["quantity"]), #user_keys[user_id]["symbols"][symbol_name]["take_profit_orders_info"][str(level)]["quantity"],
                            price=max(new_price, current_price*1.005)
                        )
                        order_id = None
                        for key in possible_order_id_keys:
                            if 'info' in tp_order and key in tp_order['info']:
                                order_id = tp_order['info'][key]
                                print("order_id 연속성 확인", order_id)
                                break
                            print("order_id 연속성 확인", order_id)
                            #user_keys[user_id]["symbols"][symbol_name]["take_profit_orders_info"][level]["order_id"] = order_id
                            #user_keys[user_id]["symbols"][symbol_name]["take_profit_orders_info"][level]["target_price"] = max(new_price, current_price*1.005)
                            #user_keys[user_id]["symbols"][symbol_name]["take_profit_orders_info"][level]["active"] = True
                            target_price = max(new_price, current_price*1.005)
                            await update_take_profit_orders_info(redis, exchange_name,user_id,symbol_name,level,order_id,target_price,info["quantity"], True, side = 'sell')
                            await asyncio.sleep(random.uniform(0.05, order_buffer+0.1))
                            asyncio.create_task(monitor_tp_orders_websocekts(exchange_name, symbol_name, user_id, level, take_profit_orders_info))
                            order_placed[level] = True
                            await add_placed_price(exchange_name, user_id, symbol_name, price=new_price)
                            await set_order_placed(exchange_name, user_id, symbol_name, new_price, level_index = level)
                            orders_count += 1  # 주문 생성 후 수를 증가
                            break
                    #elif (new_position_size < 0.0 ) and not take_profit_orders_info[level]["active"] and float(take_profit_orders_info[level]["quantity"]) > 0.0 and direction == 'short':
                        
                    except Exception as e:
                        print(f"{user_id} 2: An error occurred on tp order(long): {e}")
                        tp_order = None
                #else:
                #    if position_size != 0 and info["active"] == False:
                #        print(f"{symbol}의 info : {info}")
                    
                    #if info["active"] == False:
                    #    await update_take_profit_orders_info(redis, exchange_name,user_id,symbol_name = symbol_name, level = level, order_id = None, new_price = 0.0, quantity= 0.0, active =  False, side= None)
                        #user_keys[user_id]["symbols"][symbol_name]["take_profit_orders_info"][level]["order_id"] = None
                        #user_keys[user_id]["symbols"][symbol_name]["take_profit_orders_info"][level]["target_price"] = 0.0
                        #user_keys[user_id]["symbols"][symbol_name]["take_profit_orders_info"][level]["quantity"] = 0.0
                        #user_keys[user_id]["symbols"][symbol_name]["take_profit_orders_info"][level]["side"] = None
                    #else:
                    #    print(f"익절 주문이 이미 활성화되어 있습니다. {symbol_name} {level}레벨의 주문 정보 : {take_profit_orders_info[level]}")
                    #    continue
            else:
                pass
                #print(f"{symbol} current_price : {current_price}, 근접 Upper: {upper_levels} Lower: {lower_levels}")
    except Exception as e:
        print(f"An {symbol} order error on take profit orders: {e}")
        traceback.print_exc()
    update_flag = False  # 실행 후 update_flag를 False로 설정
    last_execution_time = current_time  # 마지막 실행 시간 갱신
    end_timestamp = int(time.time())
    elapsed_time = end_timestamp - current_timestamp
    current_time_str = datetime.fromtimestamp(current_timestamp).strftime('%Y-%m-%d %H:%M:%S')
    print(f"{symbol}의 15분 주기 업데이트가 완료되었습니다. 소요시간 : {elapsed_time}초 현재시간 : {current_time_str}")
    
    
    
    try:
        if adx_4h == -2 and grid_levels['adx_state_4h'].iloc[-2] != -2 and grid_levels['adx_state_4h'].iloc[-3] != -2:
            print(f'{symbol}의 4시간봉 ADX 상태가 -2입니다. 롱포지션을 종료합니다.')
            message = f"{symbol}의 4시간봉 추세가 하락입니다. 숏 매매 위주로 진행합니다."
            position_size = await get_position_size(exchange_name, user_id, symbol)
            try:
                if position_size > 0:
                    #await manager.add_user_message(user_id, message)
                    await add_user_log(user_id, message)
                    await telegram_message.send_telegram_message(f"{symbol}의 4시간봉 추세가 하락입니다. 롱포지을 종료합니다.", exchange_name, debug = True)
                    await asyncio.sleep(random.uniform(0.02, order_buffer))
                    asyncio.create_task(strategy.close(exchange_instance, symbol, qty = max(new_position_size , position_size), message = f'4시간봉 추세가 하락으로 전환됩니다.\n{symbol}그리드 롱포지션을 종료합니다.', action = 'close_long'))
                    level_quantities = {n: 0 for n in range(0, grid_num + 1)}
                    for n in range(0, grid_num + 1):
                        await update_take_profit_orders_info(redis, exchange_name,user_id,symbol_name, n, None, 0.0, 0.0, False, None)
                        #user_keys[user_id]["symbols"][symbol_name]["take_profit_orders_info"][n]["active"] = False
                        #user_keys[user_id]["symbols"][symbol_name]["take_profit_orders_info"][n]["order_id"] = None
                        #user_keys[user_id]["symbols"][symbol_name]["take_profit_orders_info"][n]["target_price"] = 0.0
                        #user_keys[user_id]["symbols"][symbol_name]["take_profit_orders_info"][n]["quantity"] = 0.0
                        #user_keys[user_id]["symbols"][symbol_name]["take_profit_orders_info"][n]["side"] = None
            except Exception as e:
                logging.error(f"An error occurred on closing long ADX Logic: {e}")
            
        if adx_4h == 2 and grid_levels['adx_state_4h'].iloc[-2] != 2 and grid_levels['adx_state_4h'].iloc[-3] != 2:
            print('4시간봉 ADX 상태가 2입니다. 숏포지션을 종료합니다.')
            #global_messages.trading_message.put = f"{symbol}의 4시간봉 추세가 상승입니다. 롱 매매 위주로 진행합니다."
            message = f"{symbol}의 4시간봉 추세가 상승입니다. 롱 매매 위주로 진행합니다."
            #await manager.add_user_message(user_id, message)
            await add_user_log(user_id, message)
            try:
                if position_size < 0:
                    await asyncio.sleep(random.uniform(0.02, order_buffer))
                    asyncio.create_task(strategy.close(exchange_instance, symbol, qty = min(new_position_size, position_size), message = f'4시간봉 추세가 상승으로 전환됩니다.\n{symbol}그리드 숏포지션을 종료합니다.', action = 'close_short'))
                    level_quantities = {n: 0 for n in range(0, grid_num + 1)}
            except Exception as e:
                logging.error(f"An error occurred on closing short ADX Logic: {e}")
            
    except Exception as e:
        print(f"An error occurred on ADX logic: {e}")
        


async def long_logic(exchange_name, user_id, symbol_name, symbol, lower_levels, current_price, grid_levels, order_placed, grid_num,
                     price_precision, max_notional_value, initial_investment, order_quantities, quantity_list,
                     direction, take_profit_orders_info, level_quantities, min_notional, temporally_waiting_long_order,
                     adx_4h, overbought, oversold, order_buffer, exchange_instance, redis, possible_order_id_keys, order_ids, position_size, under_1_grid):
                long_logic_start_time = time.time()
                order_placed = await get_order_placed(exchange_name, user_id, symbol_name, grid_num)
                #print(f"order_placed 확인 : {order_placed}")
                for level in lower_levels:
                    grid_level = int(level[0])
                    price_level = level[1]
                    
                    if (grid_level >= 2) :
                        prev_level = grid_level - 1

                        if grid_level == 2:
                            if current_price > grid_levels[f'grid_level_{prev_level}'].iloc[-1]:
                                under_1_grid = False
                        
                        

                        initial_capital = initial_investment[prev_level]
                        order_quantity = order_quantities[prev_level]
                        #print(f"take_profit_orders_info55", take_profit_orders_info)
                        #print(f"prevlevel 확인 : {prev_level}")
                        #print('type 확인', type(prev_level))
                        #print(f"prevlevel 값 확인 : {prev_level in take_profit_orders_info}")
                        #print(f"take_profit_orders_info[prev_level]['active']", take_profit_orders_info[prev_level]["active"])
                        #print(f"prev_level: {prev_level}")
                        #print(f"take_profit_orders_info keys: {take_profit_orders_info.keys()}") #<<-- 0713에, 계속 key error 나온건, 다른 게 아니라, 이게 str로 되어있었다. 그래서 다시 int로 수정. 확인함. <-- 'dict key로 1,2,3,..로 int로저장됨 0715확인
                        
                            #print(f"An error occurred on checking minimum volatility: {e}")
                        #print(f"minimum_volatility{minimum_volatility} :last_placed_price 확인 : {last_placed_price[grid_level]},🔸 volatility = {abs(float(last_placed_price[grid_level]) - float(current_price)) / float(current_price)}")
                        ###롱 주문 생성 로직 

                        
                        if  int(prev_level) >= 1 and ((str(prev_level) in take_profit_orders_info and (not take_profit_orders_info[str(prev_level)]["active"]))) and (not order_placed[prev_level]) and (price_level < current_price) and (adx_4h != -2 or position_size < 0.0) and (not temporally_waiting_long_order) and not overbought  :
                            okay_to_order = await okay_to_place_order(exchange_name, user_id, symbol_name, price_level, max_notional_value, order_direction = 'long')
                            if (okay_to_order) and (not order_placed[prev_level] and (direction != 'short')) or (position_size < 0 and direction == 'short') and (not await is_price_placed(exchange_name, user_id, symbol_name, prev_level)):
                                #print(f'{symbol} 50')
                                long_level = grid_levels[f'grid_level_{prev_level}'].iloc[-1]
                                if long_level > 100000 or long_level < 0:
                                    print(f"{symbol} : long level : {long_level}, price_level : {price_level}")
                                    continue
                                if long_level < current_price * 0.9:
                                    long_level = (current_price + long_level) * 0.5
                                if exchange_name == 'upbit':
                                    long_level = get_corrected_rounded_price(long_level)
                                else:
                                    long_level = adjust_price_precision(long_level, price_precision)

                                if exchange_name == 'upbit':
                                    order_price_unit = get_order_price_unit_upbit(current_price)
                                    quantity_former = initial_capital / current_price
                                    processing_qty = round_to_upbit_tick_size(quantity_former)
                                    adjusted_quantity = processing_qty
                                elif exchange_name =='okx' :
                                    adjusted_quantity = order_quantities[grid_level-1]
                                    if symbol.startswith("ETH"):
                                        min_quantity = 0.1
                                    elif symbol.startswith("SOL"):
                                        min_quantity = 0.01
                                    elif symbol.startswith("BTC"):
                                        min_quantity = 0.01
                                    else:
                                        min_quantity = 0.1  # 그 외 종목의 최소 수량
                                elif min_notional is not None:
                                    min_quantity = min_notional / long_level
                                    
                                    if level_quantities[prev_level] > 0:
                                        adjusted_quantity = max(level_quantities[prev_level], min_quantity)
                                    else:
                                        adjusted_quantity = max(quantity_list[grid_level-1], min_quantity)
                                else:
                                    if level_quantities[prev_level] > 0:
                                        adjusted_quantity = level_quantities[prev_level]
                                    else:
                                        adjusted_quantity = quantity_list[grid_level-1]
                                try:
                                    print(f'{symbol} 롱 분기 확인! 0101 현재 level : {grid_level} 이전 level : {prev_level} 현재가 : {current_price} long_level : {long_level}, order_placed : {order_placed}')
                                    if not await is_price_placed( exchange_name, user_id, symbol_name, price = long_level, grid_level = prev_level):
                                        if exchange_name == 'bitget':
                                            long_order = await exchange_instance.create_order(
                                                symbol=symbol_name,
                                                type='limit',
                                                side='buy',
                                                amount=adjusted_quantity,
                                                price=long_level,
                                                params={
                                                'contract_type': 'swap',
                                                'position_mode': 'single',
                                                'marginCoin': 'USDT',
                                                }
                                            )
                                        #elif exchange_name == 'bitget_spot':
                                        #    long_order = await exchange_instance.create_order(
                                        #        symbol=symbol_name,
                                        #        type='limit',
                                        #        side='buy',
                                        #        amount=adjusted_quantity,
                                        #        price=long_level
                                        #    )
                                        elif exchange_name == 'okx' or exchange_name == 'okx_spot':
                                            try:
                                                if long_level < 1000000 and long_level > 0:
                                                    if position_size < 0 :
                                                        try:
                                                            long_order = await exchange_instance.create_order(
                                                                symbol=symbol_name,
                                                                type='limit',
                                                                side='buy',
                                                                amount=adjusted_quantity,
                                                                price=long_level,
                                                                params={'reduceOnly': True}
                                                            )
                                                            print(f'{symbol} okx-short direc의 숏 익절 롱주문 12✔︎')
                                                        except Exception as e:
                                                            print(f"Reduce Only error occurred on making long order on okx:(short익절) quantity : {adjusted_quantity} price : {long_level} {e}")
                                                            long_order = None
                                                    else:
                                                        long_order = await exchange_instance.create_order(
                                                            symbol=symbol_name,
                                                            type='limit',
                                                            side='buy',
                                                            amount=adjusted_quantity,
                                                            price=long_level
                                                        )
                                                        #print('okx의 롱주문 13✔︎')
                                                else:
                                                    print(f"long_level : {long_level} {symbol} {adjusted_quantity}")
                                                    continue
                                                    
                                                    #print('okx의 롱주문 14✔︎'
                                                await set_order_placed(exchange_name, user_id, symbol_name, long_level, level_index = prev_level)
                                                
                                            except Exception as e:
                                                if ('margin' in str(e)) or ('Insufficient' in str(e)):
                                                    print(f"{user_id} : Insufficient balance for {symbol_name} at {prev_level} level. Temporally waiting for next opportunity.")
                                                    temporally_waiting_long_order = True
                                                    temporally_waiting_short_order = True
                                                    await asyncio.sleep(2)
                                                    continue
                                                elif "You don't have any positions'" in str(e):
                                                    print(f"{user_id} : You don't have any positions for {symbol_name} at {prev_level} level. Temporally waiting for next opportunity.")
                                                    temporally_waiting_long_order = True
                                                    temporally_waiting_short_order = True
                                                    await asyncio.sleep(3)
                                                    #continue
                                                else:
                                                    if ('margin' in str(e)) or ('Insufficient' in str(e)):
                                                        print(f"{user_id} : Insufficient balance for {symbol_name} at {prev_level} level. Temporally waiting for next opportunity.")
                                                        temporally_waiting_long_order = True
                                                        temporally_waiting_short_order = True
                                                        await asyncio.sleep(3)
                                                        continue
                                                    else:
                                                        if ('margin' in str(e)) or ('Insufficient' in str(e)):
                                                            print(f"{user_id} : Insufficient balance for {symbol_name} at {prev_level} level. Temporally waiting for next opportunity.")
                                                            temporally_waiting_long_order = True
                                                            temporally_waiting_short_order = True
                                                            await asyncio.sleep(3)
                                                            continue
                                                        else:
                                                            print(f"{user_id} :{symbol} level ; {grid_level} An error occurred on making long order on okx:(short익절) quantity : {adjusted_quantity} price : {long_level} {e}") 
                                                            long_order = None
                                                            continue


                                        elif exchange_name == 'upbit':
                                            long_order = await retry_async(strategy.place_order, exchange = exchange_instance, symbol=symbol_name,order_type='limit',side='buy',amount=adjusted_quantity,price=long_level)
                                        else:
                                            long_order = await exchange_instance.create_order(
                                                symbol=symbol_name,
                                                type='limit',
                                                side='buy',
                                                amount=adjusted_quantity,
                                                price=long_level
                                            )
                                            #print('long_order1🔥5')
                                        if long_order is not None:
                                            print(f"{symbol}52")
                                            #print(long_order)
                                            temporally_waiting_long_order = False
                                            for key in possible_order_id_keys:
                                                if 'info' in long_order and key in long_order['info']:
                                                    order_id = long_order['info'][key]
                                                    if exchange_name == 'okx' or exchange_name == 'okx_spot':
                                                        if isinstance(order_id, int) or (isinstance(order_id, str) and order_id.isdigit() and 1 <= len(order_id) <= 20):
                                                            
                                                            break
                                                        else:
                                                            print(f"잘못된 order_id: {order_id}")
                                                    else:
                                                        if isinstance(order_id, int) or (isinstance(order_id, str) and 1 <= len(order_id) <= 60):
                                                            break
                                                        else:
                                                            print(f"잘못된 order_id: {order_id} type: {type(order_id)}")
                                            print(f"{user_id} : Long order placed at {long_level} : {symbol_name} {prev_level}레벨")
                                            order_ids[str(prev_level)] = order_id  # 주문 ID 저장
                                            #print(f"last_placed_price 확인 : {last_placed_price}")
                                            #print(f'grid level이랑 preve레벨 헷갈려서, grid level : {grid_level}, prev_level : {prev_level}')
                                            await add_placed_price(exchange_name, user_id, symbol_name, price=long_level)
                                            await set_order_placed(exchange_name, user_id, symbol_name, long_level, level_index = prev_level)
                                            await asyncio.sleep(random.uniform(0.05, order_buffer+0.5))
                                            asyncio.create_task(check_order_status(exchange_instance, exchange_name, order_ids[str(prev_level)], symbol_name, grid_levels, adjusted_quantity, price_precision, False, order_placed, prev_level, level_quantities, take_profit_orders_info, grid_num, direction, max_notional_value, user_id))
                                except Exception as e:
                                    error_message = str(e)
                                    if "insufficient funds" in error_message.lower() or "금액(KRW)이 부족합니다" in error_message or "Insufficient balance" in error_message or "Insufficient margin" in error_message:
                                        temporally_waiting_long_order = True
                                        print(f"Long order failed at {long_level} : Insufficient funds for {symbol_name} at {prev_level} level. Temporally waiting for next opportunity.")
                                    else:
                                        # 다른 예외 처리
                                        print(f"Failed to place order due to error: {error_message}")
                                        print(traceback.format_exc())
                                        
                                        temporally_waiting_long_order = True
                                        await asyncio.sleep(3)  # 실패 후 잠시 대기
                        level_end_time = time.time()
                        level_elapsed_time = level_end_time - long_logic_start_time
                        if level_elapsed_time > 1:
                            print(f"{symbol}의 {prev_level}레벨 롱주문 로직 완료{long_level}. 소요시간 : {round(level_elapsed_time,2)}초")
                        else:
                            current_time = int(time.time())
                            current_minute = current_time // 60 % 60  # 현재 분 계산
                            current_second = current_time % 60  # 현재 초 계산
                            if  current_minute % 7 == 0 and current_second < 2:
                                if order_placed[prev_level] :
                                    print(f"{user_id} : {symbol}의 {prev_level}레벨 롱 주문이 이미 있습니다 time : {current_minute}.")
                                elif adx_4h == -2 :
                                    print(f"{symbol}의 ADX == -2여서 롱 주문 불가능 상황")
                                else:
                                    print(f"롱 주문 불가능한 이유 확인. {symbol} order_placed : {order_placed[prev_level]}, price_level : {price_level}, current_price : {current_price}, adx_4h : {adx_4h}, overbought : {overbought}")
                    elif grid_level == 1 or grid_level == 0:
   
                        if under_1_grid == False:
                            under_1_grid = True
                            message = f"☑️{symbol}의 그리드 최하단에 도달했습니다."
                            position_size = await get_position_size(exchange_name, user_id, symbol)

                            if position_size < 0 and (exchange_name == 'binance' or exchange_name == 'okx' or exchange_name == 'bitget'):
                                #await manager.add_user_message(user_id, message)
                                await add_user_log(user_id, message)
                                print(message)
                                try:
                                    await strategy.close(exchange_instance, symbol_name, qty = max(abs(position_size), position_size), message = message, action = 'close_short')
                                    level_quantities = {n: 0 for n in range(0, grid_num + 1)}
                                    print(f"최하단 숏 종료. {symbol_name} {grid_level}레벨")
                                    #asyncio.create_task(telegram_message.send_telegram_message(message, exchange_instance))
                                except Exception as e:
                                    print(f"최하단 숏 종료 로직 재확인 필요: {e}")
                        else:
                            if position_size < 0 and (exchange_name == 'binance' or exchange_name == 'okx' or exchange_name == 'bitget' or exchange_name == 'bybit'):

                                try:
                                    okay_to_order = await okay_to_place_order(exchange_name, user_id, symbol_name, price_level, max_notional_value, order_direction='long')
                                    prev_level = grid_level - 1
                                    #print('grid level 0가 있는지 확인. ', grid_levels[f'grid_level_{prev_level}'].iloc[-1])
                                    order_quantity = order_quantities[grid_level-1]
                                    if (okay_to_order) and (not take_profit_orders_info[str(prev_level)]["active"]) and (not order_placed[int(grid_level)] and price_level < current_price) and adx_4h != 2 and (not temporally_waiting_long_order) and not overbought and  (not await is_order_placed(exchange_name, user_id, symbol, level)):
                                        if (not order_placed[int(prev_level)]) and (direction == 'short'):
                                            long_level = float(grid_levels[f'grid_level_0'].iloc[-1])
                                            if long_level < current_price * 0.9:
                                                long_level = (current_price + long_level) * 0.5
                                            long_level = adjust_price_precision(long_level, price_precision)
                                            print(f'{symbol} 분기 확인! 0102 ')
                                            if not await is_price_placed( exchange_name, user_id, symbol_name, price = long_level, grid_level = prev_level):
                                                if exchange_name =='okx' :
                                                    adjusted_quantity = order_quantities[grid_level-1]
                                                    if symbol.startswith("ETH"):
                                                        min_quantity = 0.1
                                                        adjusted_quantity = max(adjusted_quantity, min_quantity)
                                                    elif symbol.startswith("SOL"):
                                                        min_quantity = 0.01
                                                        adjusted_quantity = max(adjusted_quantity, min_quantity)
                                                    elif symbol.startswith("BTC"):
                                                        min_quantity = 0.01
                                                        adjusted_quantity = max(adjusted_quantity, min_quantity)
                                                    else:
                                                        min_quantity = 0.1  # 그 외 종목의 최소 수량
                                                elif min_notional is not None:
                                                    min_quantity = min_notional / long_level
                                                    if level_quantities[prev_level] > 0:
                                                        adjusted_quantity = max(level_quantities[prev_level], min_quantity)
                                                    else:
                                                        adjusted_quantity = max(quantity_list[grid_level-1], min_quantity)
                                                else:
                                                    if level_quantities[prev_level] > 0:
                                                        adjusted_quantity = level_quantities[prev_level]
                                                    else:
                                                        adjusted_quantity = quantity_list[grid_level-1]
                                                try:
                                                    if exchange_name == 'bitget':
                                                        long_order = await exchange_instance.create_order(
                                                            symbol=symbol_name,
                                                            type='limit',
                                                            side='buy',
                                                            amount=adjusted_quantity,
                                                            price=long_level,
                                                            params={
                                                            'contract_type': 'swap',
                                                            'position_mode': 'single',
                                                            'marginCoin': 'USDT',
                                                            }
                                                        )
                                                    elif exchange_name == 'okx' :

                                                        if direction == 'short' and position_size < 0:
                                                            try:
                                                                long_order = await exchange_instance.create_order(
                                                                    symbol=symbol_name,
                                                                    type='limit',
                                                                    side='buy',
                                                                    amount=adjusted_quantity,
                                                                    price=long_level,
                                                                    params={'reduceOnly': True}
                                                                )
                                                                print(f'{symbol} Long Order(short close01✔︎)')
                                                            except Exception as e:
                                                                
                                                                print(f"{user_id} : An error occurred on making long order on okx for reduce only: {e}")
                                                                long_order = None
                                                                continue
                                                                #raise e
                                                        else:
                                                            long_order = await exchange_instance.create_order(
                                                                symbol=symbol_name,
                                                                type='limit',
                                                                side='buy',
                                                                amount=adjusted_quantity,
                                                                price=long_level
                                                            )
                                                            print(f'{symbol} long_order16')

                                                    else:
                                                        long_order = await exchange_instance.create_order(
                                                            symbol=symbol_name,
                                                            type='limit',
                                                            side='buy',
                                                            amount=adjusted_quantity,
                                                            price=long_level
                                                        )
                                                        print(f'{symbol} long_order02')
                                                    if long_order is not None:
                                                        temporally_waiting_long_order = False
                                                        for key in possible_order_id_keys:
                                                            if 'info' in long_order and key in long_order['info']:
                                                                order_id = long_order['info'][key]
                                                                if exchange_name == 'okx' or exchange_name == 'okx_spot':
                                                                    if isinstance(order_id, int) or (isinstance(order_id, str) and order_id.isdigit() and 1 <= len(order_id) <= 25):
                                                                        break
                                                                    else:
                                                                        print(f"잘못된 order_id: {order_id}")
                                                                else:
                                                                    if isinstance(order_id, int) or (isinstance(order_id, str) and 1 <= len(order_id) <= 60):
                                                                        break
                                                                    else:
                                                                        print(f"잘못된 order_id: {order_id} type: {type(order_id)}")
                                                        #print(f"Long order placed at {long_level} : {order_id}, {symbol_name} {prev_level}레벨")
                                                        order_ids[str(grid_level)] = order_id  # 주문 ID 저장
                                                        order_placed[int(grid_level)] = True
                                                        print(f"타입 체킹. grid_level type : {type(grid_level)}")
                                                        await set_order_placed(exchange_name, user_id, symbol_name, long_level, level_index = prev_level)
                                                        asyncio.create_task(check_order_status(exchange_instance, exchange_name, order_ids[str(grid_level)], symbol_name, grid_levels, adjusted_quantity, price_precision, False, order_placed, prev_level, level_quantities, take_profit_orders_info, grid_num, direction,max_notional_value, user_id))
                                                except Exception as e:
                                                    error_message = str(e)
                                                    if "insufficient funds" in error_message.lower() or "금액(KRW)이 부족합니다" in error_message or "Insufficient balance" in error_message or "Insufficient margin" in error_message:
                                                        temporally_waiting_long_order = True
                                                        print(f"Long order failed at {long_level} : Insufficient funds for {symbol_name} at {prev_level} level. Temporally waiting for next opportunity.")
                                                    else:
                                                        # 다른 예외 처리
                                                        print(f"Failed to place order due to error: {error_message}")

                                                        temporally_waiting_long_order = True
                                                        await asyncio.sleep(3)  # 실패 후 잠시 대기
                                            else:
                                                print(f"{symbol} : {long_level}이 이미 주문되어 있습니다(01).")

                                except Exception as e:
                                    print(f"{user_id} : {symbol} An error occurred on making short tp order: {e}") #<-- 여기서 계속, -1이라는 오류 발생.
                                    print(traceback.format_exc()) 

                    else:
                        print(f'{user_id} {symbol} 정의해두지 않은 상황. 디버깅.')
                        #await telegram_message.send_telegram_message('정의해두지 않은 상황. 디버깅.', exchange_instance, debug = True)
                return order_placed, temporally_waiting_long_order, under_1_grid



async def short_logic(exchange_name, user_id, symbol_name, symbol, upper_levels, current_price, grid_levels, order_placed, grid_num,
                     price_precision, max_notional_value, initial_investment, order_quantities, quantity_list, new_position_size,
                     direction, take_profit_orders_info, level_quantities, min_notional, temporally_waiting_short_order,
                     adx_4h, overbought, oversold, order_buffer, exchange_instance, redis, possible_order_id_keys, order_ids, position_size, over_20_grid):
    order_placed = await get_order_placed(exchange_name, user_id, symbol_name, grid_num)
    if (direction == 'long' and position_size > 0) or (direction != 'long') :
        for level in upper_levels:
            try:
                grid_level = level[0]
                price_level = level[1]
                position_size = await get_position_size(exchange_name, user_id, symbol)
                #print(order_placed)
                #print(grid_level)
                #print(f"{symbol}의 숏 주문로직 시작. {level}")
                current_time = int(time.time())
                current_minute = current_time // 60 % 60  # 현재 분 계산
                current_second = current_time % 60  # 현재 초 계산
                if price_level < 1000000 and (not order_placed.get(int(grid_level), False) and price_level > current_price)  and (adx_4h != 2 or position_size > 0.0):
                    await asyncio.sleep(random.uniform(0.05, order_buffer+0.1))
                    okay_to_order = await okay_to_place_order(exchange_name, user_id, symbol, price_level, max_notional_value, order_direction = 'short')
                    if (okay_to_order) and (grid_level <= grid_num and direction != 'long') or (grid_level <= grid_num and direction == 'long' and position_size > 0) and temporally_waiting_short_order == False and (not await is_order_placed(exchange_name, user_id, symbol, grid_level)):
                        try:
                            if (int(grid_level) < int(grid_num)) :
                                over_20_grid = False
                                next_level = grid_level + 1
                                if next_level > grid_num:
                                    next_level = grid_num
                                if ((not order_placed.get(next_level, False) and ((direction != 'long')) or (position_size > 0 and direction == 'long'))) and (not await is_order_placed(exchange_name, user_id, symbol, next_level)) :
                                    short_level = grid_levels[f'grid_level_{next_level}'].iloc[-1]
                                    if short_level > 100000:
                                        print(f"{symbol} : short level : {short_level}, price_level : {price_level}")
                                        continue
                                
                                    if exchange_name == 'upbit':
                                        short_level = get_corrected_rounded_price(short_level)
                                    else:
                                        short_level = adjust_price_precision(short_level, price_precision)
                                        #print(f"{symbol} short_level : {short_level}")
                                    if short_level > current_price * 1.1:
                                        short_level = (current_price + short_level) * 0.5
                                    #print(f'{symbol} 숏 분기 확인! 0104. 현재 level : {grid_level} 주문 걸 next_level : {next_level}')
                                    if (not await is_price_placed( exchange_name, user_id, symbol_name, price = short_level, grid_level = next_level )):
                                        if exchange_name == 'okx' :
                                            adjusted_quantity = order_quantities[grid_level-1]
                                                # 종목별 최소 수량 설정
                                            if symbol.startswith("ETH"):
                                                min_quantity = 0.1
                                            elif symbol.startswith("SOL"):
                                                min_quantity = 0.01
                                            elif symbol.startswith("BTC"):
                                                min_quantity = 0.01
                                            else:
                                                min_quantity = 0.1  # 그 외 종목의 최소 수량
                                        elif min_notional is not None:
                                            min_quantity = min_notional / short_level
                                            if symbol.startswith("ETH"):
                                                min_quantity = 0.1
                                            elif symbol.startswith("SOL"):
                                                min_quantity = 0.01
                                            elif symbol.startswith("BTC"):
                                                min_quantity = 0.01
                                            else:
                                                min_quantity = 0.1  # 그 외 종목의 최소 수량
                                            if level_quantities[next_level] > 0:
                                                adjusted_quantity = max(level_quantities[next_level], min_quantity)
                                            else:
                                                adjusted_quantity = max(quantity_list[grid_level-1], min_quantity)
                                        else:
                                            if level_quantities[next_level] > 0:
                                                adjusted_quantity = level_quantities[next_level]
                                            else:
                                                adjusted_quantity = quantity_list[grid_level-1]
                                        if exchange_name == 'binance' :
                                            short_order = await exchange_instance.create_order(
                                                symbol=symbol,
                                                type='limit',
                                                side='sell',
                                                amount=adjusted_quantity,
                                                price=short_level
                                            )
                                        elif exchange_name == 'binance_spot' and new_position_size > 0:
                                            short_order = await exchange_instance.create_order(
                                                symbol=symbol,
                                                type='limit',
                                                side='sell',
                                                amount=adjusted_quantity,
                                                price=short_level
                                            )
                                        elif exchange_name == 'okx_spot' and new_position_size > 0:
                                            short_order = await exchange_instance.create_order(
                                                symbol=symbol,
                                                type='limit',
                                                side='sell',
                                                amount=adjusted_quantity,
                                                price=short_level
                                            )
                                        elif exchange_name == 'okx' :
                                            if symbol.startswith("ETH"):
                                                min_quantity = 0.1
                                            elif symbol.startswith("SOL"):
                                                min_quantity = 0.01
                                            elif symbol.startswith("BTC"):
                                                min_quantity = 0.01
                                            try:
                                                if temporally_waiting_short_order == False:
                                                    if position_size > 0.0:
                                                        short_order = await retry_async(create_short_orders, exchange_instance, symbol, short_level, adjusted_quantity, min_quantity, user_id ,reduce_only = True)
                                                        order_placed[next_level] = True
                                                        await set_order_placed(exchange_name, user_id, symbol_name, short_level, level_index = next_level)
                                                    else:
                                                        try:
                                                            short_order =await retry_async(create_short_orders, exchange_instance, symbol, short_level, adjusted_quantity, min_quantity, user_id)
                                                            order_placed[next_level] = True
                                                            await set_order_placed(exchange_name, user_id, symbol_name, short_level, level_index = next_level)
                                                        except Exception as e:
                                                            print(f"{user_id} : An error occurred on making short order202:2 {e}")
                                                            if ('margin' in str(e)) or ('insufficient' in str(e)):
                                                                short_order = None
                                                                temporally_waiting_short_order = True
                                                                temporally_waiting_long_order = True
                                                                
                                                            else:
                                                                print(f"{user_id} : An error occurred on making short order: {e}")       
                                                                short_order = None 
                                            except Exception as e:
                                                if ('margin' in str(e)) or ('insufficient' in str(e)):
                                                    print(f"{user_id} : An error occurred on making short order: {e}")
                                                    short_order = None
                                                    temporally_waiting_short_order = True
                                                    temporally_waiting_long_order = True
                                                else:
            
                                                    print(f"{user_id} : An error occurred on making short order: {e}")       
                                                    short_order = None 
                                            
                                        elif exchange_name == 'bitget':
                                            try:
                                                short_order = await exchange_instance.create_order(
                                                    symbol=symbol_name,
                                                    type='limit',
                                                    side='sell',
                                                    amount=adjusted_quantity,
                                                    price=short_level,
                                                    params={
                                                    'contract_type': 'swap',
                                                    'position_mode': 'single',
                                                    'marginCoin': 'USDT',
                                                }
                                                )
                                            except Exception as e:
                                                print(f"An error occurred7: {e}")
                                        elif exchange_name == 'bitget_spot' and new_position_size > 0:
                                            short_order = await exchange_instance.create_order(
                                                symbol=symbol_name,
                                                type='limit',
                                                side='sell',
                                                amount=adjusted_quantity,
                                                price=short_level
                                            )
                                            
                                        if short_order is not None:
                                            for key in possible_order_id_keys:
                                                if 'info' in short_order and key in short_order['info']:
                                                    order_id = short_order['info'][key]
                                                    break
                                            temporally_waiting_short_order = False
                                            order_ids[str(grid_level)] = order_id  # 주문 ID 저장
                                            print(f"{user_id} : Short order placed at {short_level} : , {symbol_name} {grid_level}레벨")
                                            try:
                                                await asyncio.sleep(random.uniform(0.05, order_buffer+0.1))
                                                asyncio.create_task(check_order_status(exchange_instance, exchange_name, order_ids[str(grid_level)], symbol_name, grid_levels, adjusted_quantity, price_precision, True, order_placed, next_level, level_quantities, take_profit_orders_info, grid_num, direction,max_notional_value, user_id))
                                                order_placed[grid_level] = True
                                                #last_placed_price[grid_level] = short_level
                                                await add_placed_price(exchange_name, user_id, symbol_name, price=short_level)
                                                await set_order_placed(exchange_name, user_id, symbol_name, short_level, level_index = grid_level)
                                            except Exception as e:
                                                print(f"An error occurred128: {e}")
                                #else:
                                #    print(f"{symbol} : {grid_level}레벨의 주문이 이미 있습니다(short logic).")
                        except Exception as e:
                            print(f"{user_id} : An error occurred on making short order: {e}")
                            print(traceback.format_exc())
                    else:
                        try:

                            if over_20_grid == False and grid_level >= grid_num:
                                print(f"grid_level : {grid_level}")
                                message = f"☑️{symbol}의 그리드 최상단에 도달했습니다."
                                if current_minute % 60 == 0:
                                    #global_messages.trading_message.put(message)
                                    #await manager.add_user_message(user_id, message)
                                    await add_user_log(user_id, message)
                                over_20_grid = True
                                position_size = await get_position_size(exchange_name, user_id, symbol)
                                print(f"{user_id} : {symbol} postiion_size: {get_position_size}")
                                if position_size > 0:
                                    print(message)
                                    try:
                                        await strategy.close(exchange_instance, symbol_name, qty = max(new_position_size ,position_size), message = message, action = 'close_long')
                                        level_quantities = {n: 0 for n in range(0, grid_num + 1)}
                                        for n in range(0, grid_num + 1):
                                            take_profit_orders_info[str(level)].update({
                                                        'order_id': None,
                                                        'target_price': 0.0,
                                                        'quantity': 0.0,
                                                        'active': False
                                                    })
                                            await update_take_profit_orders_info(redis, exchange_name,user_id,symbol_name = symbol_name, level = n, order_id = None, new_price = 0.0, quantity=0.0, active =  False, side = None)
                                            #user_keys[user_id]["symbols"][symbol_name]["take_profit_orders_info"][n]["order_id"] = None
                                            #user_keys[user_id]["symbols"][symbol_name]["take_profit_orders_info"][n]["active"] = False
                                            #user_keys[user_id]["symbols"][symbol_name]["take_profit_orders_info"][n]["target_price"] = 0.0
                                            #user_keys[user_id]["symbols"][symbol_name]["take_profit_orders_info"][n]["quantity"] = 0.0
                                            #user_keys[user_id]["symbols"][symbol_name]["take_profit_orders_info"][n]["side"] = None
                                            
                                        #asyncio.create_task(telegram_message.send_telegram_message(message, exchange_instance))
                                    except Exception as e:
                                        print(f"An error occurred on Closing whole long: {e}")
                                else: 
                                    temporally_waiting_short_order = True
                        except Exception as e:
                            print(f"{user_id} : An error occurred on making short order2: {e}")
                else:
                    if current_minute % 7 == 0 and current_second < 2:
                        
                        if order_placed.get(int(grid_level), True):
                            print(f"{symbol}의 {grid_level}레벨 주문이 이미 있습니다. {datetime.fromtimestamp(current_time).strftime('%Y-%m-%d %H:%M:')} ")
                        elif adx_4h == 2 :
                            print(f"{level} : {symbol}의 ADX == 2여서 숏 주문 불가능 상황 time : {datetime.fromtimestamp(current_time).strftime('%Y-%m-%d %H:%M:')} ")
                        else:
                            print(f'{level} : {symbol} 숏 주문 불가능 상황 .이유 확인. order_placed : {order_placed[int(grid_level)]}, price_level : {price_level}, current_price : {current_price}, adx_4h : {adx_4h}, oversold : {oversold}')
            except Exception as e:
                print(f"{user_id} :{symbol} An error occurred on making totally short {e}")
                print(traceback.format_exc())
    return order_placed, temporally_waiting_short_order, over_20_grid

#================================================================================================
#                              Grid Trading Strategy
#================================================================================================
#async def update_is_running(redis, user_key):
#    try:
#        is_running = await redis.hget(user_key, 'is_running')
#        is_running = is_running.decode('utf-8') if isinstance(is_running, bytes) else is_running
#        return bool(int(is_running or '0'))
#    except Exception as e:
#        print(f"Error updating is_running status: {e}")
#        return False

            


async def check_order_status(exchange_instance,exchange_name, order_id, symbol, grid_levels, adjusted_quantity, price_precision, is_short_order, order_placed, level_index, level_quantities, take_profit_orders_info, grid_num, direction, max_notional_value, user_id):
    global user_keys
    try:
        redis = await get_redis_connection()
        user_key = f'{exchange_name}:user:{user_id}'
        possible_order_id_keys = ['order_id', 'uuid', 'orderId', 'ordId', 'id']
        is_running = await redis.hget(user_key, 'is_running')
        is_running = is_running.decode('utf-8') if isinstance(is_running, bytes) else is_running
        is_running = bool(int(is_running or '0'))
        if not is_running:
            return
    except Exception as e:
        print(f"An error occurred:507 {e}")
        print(traceback.format_exc())
        return
    try:
        while is_running:
            current_time = datetime.now()
            minutes = current_time.minute
            seconds = current_time.second
            # 15분 단위 시간 확인 (14분 55초, 29분 55초, 44분 55초, 59분 55초에 종료)
            if (minutes in [14, 29, 44, 59] and seconds >= 55) or (minutes == 59 and seconds >= 55):
                #print(f"{symbol} 시간 기준 도달 - 함수 종료")
                break
            try:
                retry_count = 0
                await asyncio.sleep(random.uniform(0.5, 2.5))
                fetched_order = await fetch_order_with_retry(exchange_instance, order_id, symbol)
            except Exception as e:
                if 'Order does not exists' in str(e):
                    print(f"Order does not exist: {order_id}")
                    break
                print(f"{user_id} An error occurred4: {e}")
                await log_exception(e)
                break
            if fetched_order['status'] == 'closed':
                filled_quantity = fetched_order.get('filled', adjusted_quantity)  # 'filled' 키가 없는 경우 기본값 0
                level_quantities[level_index] = round(adjusted_quantity,4 )
                print(f"f 체결. {level_quantities[level_index]}")
                trading_direction = '🔴 숏' if is_short_order else '🟢 롱'
                message = f"<{symbol} :{level_index}의 {trading_direction} 주문 체결되었습니다.>\n 수량 : {level_quantities[level_index]} | 가격 : {fetched_order['price']} | 시간 : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                asyncio.create_task(telegram_message.send_telegram_message(message, exchange_name, user_id))
                #await manager.add_user_message(user_id, message)
                await add_user_log(user_id, message)
                print(f"{user_id} : <{symbol} :{level_index}의  {trading_direction} 주문 체결되었습니다.>\n 수량 : {level_quantities[level_index]} | 가격 : {fetched_order['price']} | 시간 : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                current_price = fetched_order['price']
                # 마지막 진입 시간 기록
                await redis_database.set_trading_volume(exchange_name, user_id, symbol, filled_quantity)
                symbol_key = f'{user_key}:symbol:{symbol}'
                user_keys[user_id]["symbols"][symbol]["last_entry_time"] = datetime.now()
                user_keys[user_id]["symbols"][symbol]["last_entry_size"] = filled_quantity
                # 데이터 읽기
                user_data = await redis.hgetall(user_key)
                symbol_data = await redis.hgetall(symbol_key)
                symbol_data['last_entry_time'] = datetime.now()
                symbol_data['last_entry_size'] = filled_quantity
                grid_count = -1 if is_short_order else 1
                await update_active_grid(redis, exchange_name, user_id, symbol, level_index, fetched_order['price'], level_quantities[level_index], execution_time = datetime.now(),grid_count = grid_count, pnl = None)
                await update_take_profit_orders_info(redis, exchange_name, user_id, symbol, level = level_index, order_id=  order_id, new_price = fetched_order['price'], quantity = level_quantities[level_index], active = True, side = 'short' if is_short_order else 'long')
                if is_short_order:
                    take_profit_level = max(min(current_price * 0.993, grid_levels[f'grid_level_{level_index - 1}'].iloc[-1]), current_price * 0.93) #<-- 숏 주문이 익절될 곳. 현재의 level_index보다 한 칸 낮은 곳. 그러나 최소 0.7%는 떨어져야함.
                    #print(f"Take profit level: {take_profit_level}")
                    tp_side = 'buy'
                    print(f'{user_id} : Short 체결. {take_profit_level}에 새로운 tpside:{tp_side} 주문 생성')
                    if level_index < grid_num:
                        new_order_level = max(grid_levels[f'grid_level_{level_index + 1}'].iloc[-1],current_price*1.005) #<-- 새로운 주문이 걸릴 곳. 현재의 level_index보다 한 칸 높은 곳.그러나 최소 0.5%는 올라가야함.
                        print(f"New order level: {new_order_level}")
                        new_order_side = 'sell' #<-- 새로운 주문이 걸릴 side(숏 주문이 추가로 걸릴 side)
                        if direction == 'long':
                            new_order_side = None
                        new_order_quantity = level_quantities[level_index] 
                        #print(f"새로 진입할 물량 :{level_quantities[level_index]}")
                    else:
                        new_order_level = None
                        new_order_side = None
                        new_order_quantity = 0.0
                        print('최상단 도달. 따라서 새로운 주문은 들어가지 않음')
                else:
                    #print('Long 익절 + 새로운 order')
                    take_profit_level = min(max(current_price*1.004, grid_levels[f'grid_level_{level_index + 1}'].iloc[-1]), current_price*1.08) #<-- 롱 주문이 익절될 곳. 현재의 level_index보다 한 칸 높은 곳. 그러나 최대 8%가 한계. 그리고 최소 0.5%는 떨어져야.
                    #print(f"Take profit level: {take_profit_level}")
                    tp_side = 'sell'
                    print(f"{user_id} : Long 체결. {take_profit_level}에 새로운 tpside:{tp_side} 주문 생성")
                    if level_index > 1:
                        new_order_level = min(grid_levels[f'grid_level_{level_index - 1}'].iloc[-1], current_price*0.995) #새로 롱주문이 들어갈 곳. 현재의 level_index보다 한 칸 낮은 곳. 그러나,최소 0.5%는 떨어져야함.
                        #print(f"New order level: {new_order_level}")
                        new_order_side = 'buy' #새로운 주문이 들어갈 side(롱 주문이 추가로 들어갈 side)
                        if direction == 'short':
                            new_order_side = None
                        new_order_quantity = level_quantities[level_index] #새로운 주문이 들어갈 물량
                        #print(f"체결물량 (익절 대상 물량):{level_quantities[level_index]}")
                    else:
                        new_order_level = None
                        new_order_side = None
                        new_order_quantity = 0.0
                        print('최하단 도달. 따라서 새로운 주문은 들어가지 않음')

                if exchange_instance.id.lower() == 'upbit':
                    take_profit_level = get_corrected_rounded_price(take_profit_level)
                else:
                    take_profit_level = adjust_price_precision(take_profit_level, price_precision)
                #print(f"Take profit level: {take_profit_level}")

                ##익절주문##
                await asyncio.sleep(0.5)
                if level_index > 1 and level_index < grid_num:
                    #⭐️여기서 중복주문이 많이 발생한다. 해결방법은, 현재 오픈오더를 확인하고 거는 방법이지만, API제한때문에 그렇게 할 수는 없다. 만약 중복주문이 발생한다면 이 곳을 확인하기. 0721 1525
                    is_okay_to_place = await okay_to_place_order(exchange_name, user_id, symbol, take_profit_level, max_notional_value, order_direction = tp_side)
                    if is_okay_to_place :  #<-- 여기, #direction != 'long-short': <-- 원래, 여기 익절주문 거는 것에 있어서, direction이 long-short은 걸지 않도록 했었는데, 그랬더니 익절주문이 안나가고 active가 False가 되고 있었다. 0721 1525
                        if exchange_instance.id.lower() == 'upbit':
                            tp_order = await retry_async(strategy.place_order, exchange_instance, symbol, order_type='limit',side='sell', amount = level_quantities[level_index], price = take_profit_level)
                            adjusted_quantity = level_quantities[level_index]
                        elif exchange_instance.id.lower() == 'bitget' and exchange_name == 'bitget':
                            tp_order = await exchange_instance.create_order(
                                symbol=symbol,
                                type='limit',
                                side=tp_side,
                                amount=adjusted_quantity,
                                price=take_profit_level,
                                params={
                                    'contract_type': 'swap',
                                    'position_mode': 'single',
                                    'marginCoin': 'USDT'
                                }
                                )
                        #elif exchange_instance.id.lower() == 'bitget' and exchange_name == 'bitget_spot':
                        #    tp_order = await exchange_instance.create_order(
                        #        symbol=symbol,
                        #        type='limit',
                        #        side='sell',
                        #        amount=min(new_order_quantity, adjusted_quantity),
                        #        price=take_profit_level,
                        #        )
                        elif exchange_instance.id.lower() == 'okx' and exchange_name == 'okx':
                            tp_order = await exchange_instance.create_order(
                                symbol=symbol,
                                type='limit',
                                side=tp_side, #<-- 원래, tp_side였는데, reduce 방향을 바꾸라고 오류가 나와서, new_order_side로 변경함.(06.01) <-- 06.19 TP side가 맞다.
                                amount=level_quantities[level_index],
                                price=take_profit_level,
                                params={'reduceOnly': True} #<-- reduce only를 지우는 이유는, 예를들어, 롱을 갖고 있고 숏이 잡혔는데(즉 롱 익절), reduce only로 하면, 또 롱이 잡힌다. 그래서 reduce only를 빼는게 맞다.
                                                            )                                #<--하지만, 추가주문이 아니라 익절주문이잖아? 그러니까True가 맞지.
                            #print('tp_order03')
                        elif exchange_instance.id.lower() == 'okx' and exchange_name == 'okx_spot':
                            tp_order = await exchange_instance.create_order(
                                symbol=symbol,
                                type='limit',
                                side='sell',
                                amount=level_quantities[level_index],
                                price=take_profit_level,
                                params={'reduceOnly': True}
                                )
                        elif exchange_name == 'binance_spot':
                            tp_order = await exchange_instance.create_order(
                                symbol=symbol,
                                type='limit',
                                side='sell',
                                amount=min(adjusted_quantity, new_order_quantity),
                                price=take_profit_level,
                                )
                        else:
                            tp_order = await exchange_instance.create_order(
                                symbol=symbol,
                                type='limit',
                                side=tp_side, #<-- 원래, tp_side였는데, reduce 방향을 바꾸라고 오류가 나와서, new_order_side로 변경함.(06.01) #<-- 0619 tp side가 맞으므로 다시 수정
                                amount=level_quantities[level_index],
                                price=take_profit_level,
                                params={'reduceOnly': True}  #if is_short_order else {} < -- ??? 이건 왜 롱오더에 대해선 적용을 안한거지
                            )
                            #print('tp_order04')
                            #print(f"Take profit order placed at {take_profit_level}")
                        # 익절 주문 정보 업데이트
                        for key in possible_order_id_keys:
                            if 'info' in tp_order and key in tp_order['info']:
                                order_id = tp_order['info'][key]
                                if exchange_name == 'okx' or exchange_name == 'okx_spot':
                                    if isinstance(order_id, int) or (isinstance(order_id, str) and order_id.isdigit() and 1 <= len(order_id) <= 20):
                                        break
                                    else:
                                        print(f"{user_id} : 잘못된 order_id: {order_id}")
                                else:
                                    if isinstance(order_id, int) or (isinstance(order_id, str)  and 1 <= len(order_id) <= 60):
                                        break
                                    else:
                                        print(f"{user_id} : 잘못된 order_id: {order_id}. type : {type(order_id)}")
                        if tp_order is not None:
                            level_index = level_index + 1 if not is_short_order else level_index - 1
                            take_profit_orders_info[str(level_index)] = {
                                "order_id": order_id, 
                                "quantity": adjusted_quantity, 
                                "target_price": take_profit_level, 
                                "active": True,
                                "side": tp_side
                            }
                            print(f"{user_id} : 익절 주문 추가. {take_profit_level}(level : {level_index}에 새로운 주문 생성. order_quantity : {adjusted_quantity})")
                        try:
                            await add_placed_price(exchange_name, user_id, symbol, take_profit_level)
                            await set_order_placed(exchange_name, user_id, symbol, take_profit_level, level_index=level_index)
                            grid_count = -1 if is_short_order else 1
                            

                        except Exception as e:
                            print(f" {user_id} : An error occurred10: {e}")
                    else: #<-- 주문을 걸어야하지만, 주문을 걸 수 없는 경우(거기에 이미 주문이 있는 경우)
                        try:
                            print(f"이미 그 자리에 주문이 걸려있기에, 따로 익절주문을 걸지는 않음.")
                        except Exception as e:
                            print(f" {user_id} : An error occurred11: {e}")
                else: #<-- level index가 1이거나 grid num인 경우
                    position_size = await get_position_size(exchange_name, user_id, symbol)
                    if level_index == 1 or level_index == grid_num:
                        if level_index == grid_num:
                            tp_price = grid_levels[f'grid_level_{level_index}'].iloc[-1]*1.005
                        else:
                            tp_price = grid_levels[f'grid_level_{level_index}'].iloc[-1]*0.995 
                        if exchange_instance.id.lower() == 'upbit':
                            tp_order = await retry_async(strategy.place_order, exchange_instance, symbol, order_type='limit',side='sell', amount = level_quantities, price = tp_price)
                            adjusted_quantity = level_quantities
                        elif exchange_instance.id.lower() == 'okx' and exchange_name == 'okx':
                            tp_order = await exchange_instance.create_order(
                                symbol=symbol,
                                type='limit',
                                side=tp_side, #<-- 원래, tp_side였는데, reduce 방향을 바꾸라고 오류가 나와서, new_order_side로 변경함.(06.01) <-- 06.19 TP side가 맞다.
                                amount=min(position_size, new_order_quantity),
                                price=tp_price,
                                params={'reduceOnly': True}
                                )
                            #print('tp_order05')
                        elif exchange_instance.id.lower() == 'okx' and exchange_name == 'okx_spot':
                            tp_order = await exchange_instance.create_order(
                                symbol=symbol,
                                type='limit',
                                side='sell',
                                amount=level_quantities[level_index],
                                price=take_profit_level,
                                )
                        elif exchange_name == 'binance_spot':
                            tp_order = await exchange_instance.create_order(
                                symbol=symbol,
                                type='limit',
                                side='sell',
                                amount=min(adjusted_quantity, new_order_quantity),
                                price=tp_price,
                                )
                        else:
                            tp_order = await exchange_instance.create_order(
                                symbol=symbol,
                                type='limit',
                                side=tp_side, #<-- 원래, tp_side였는데, reduce 방향을 바꾸라고 오류가 나와서, new_order_side로 변경함.(06.01) #<-- 0619 tp side가 맞으므로 다시 수정
                                amount=level_quantities[level_index],
                                price=tp_price,
                                params={'reduceOnly': True}  #if is_short_order else {} < -- ??? 이건 왜 롱오더에 대해선 적용을 안한거지
                            )
                            #print('tp_order06')
                            #print(f"Take profit order placed at {take_profit_level}")
                        # 익절 주문 정보 업데이트
                        for key in possible_order_id_keys:
                            if 'info' in tp_order and key in tp_order['info']:
                                order_id = tp_order['info'][key]
                                if exchange_name == 'okx' or exchange_name == 'okx_spot':
                                    if (isinstance(order_id, int) or (isinstance(order_id, str)) and order_id.isdigit() and 1 <= len(order_id) <= 20):
                                        break
                                    else:
                                        print(f"잘못된 order_id: {order_id}")
                                else:
                                    if (isinstance(order_id, int) or (isinstance(order_id, str))) and (1 <= len(order_id) <= 60):
                                        break
                                    else:
                                        print(f"잘못된 order_id: {order_id}. type : {type(order_id)}")
                        if tp_order is not None:
                            level_index = level_index + 1 if not is_short_order else level_index - 1
                            take_profit_orders_info[str(level_index)] = {
                                "order_id": order_id, 
                                "quantity": adjusted_quantity, 
                                "target_price": take_profit_level, 
                                "active": True,
                                "side": tp_side
                            }
                        try:
                            await asyncio.sleep(random.random())
                            await update_take_profit_orders_info(redis, exchange_name, user_id, symbol, level = level_index, order_id = order_id, new_price =  take_profit_level, quantity = adjusted_quantity,active = True, side =tp_side)
                            await add_placed_price(exchange_name, user_id, symbol, take_profit_level)
                            await set_order_placed(exchange_name, user_id, symbol, take_profit_level, level_index = level_index)
                            asyncio.create_task(monitor_tp_orders_websocekts(exchange_name,symbol, user_id, level_index, take_profit_orders_info))
                        except Exception as e:
                            print(f" {user_id} : An error occurred10: {e}")
                ###익절 후, 새로운 주문을 아래에 거는 것###
                if new_order_level is not None:
                    if new_order_side is not None:
                        if exchange_instance.id.lower() == 'upbit':
                            new_order_level = get_corrected_rounded_price(new_order_level)
                        else:
                            new_order_level = adjust_price_precision(new_order_level, price_precision)
                        if not await is_price_placed(exchange_name, user_id, symbol, price = new_order_level, grid_level = level_index):
                            try:
                                if exchange_name == 'bitget':
                                    new_order = await exchange_instance.create_order(
                                        symbol=symbol,
                                        type='limit',
                                        side=new_order_side,
                                        amount=adjusted_quantity,
                                        price=new_order_level,
                                        params={
                                            'contract_type': 'swap',
                                            'position_mode': 'single',
                                            'marginCoin': 'USDT',
                                        })
                                elif exchange_name == 'binance':
                                    new_order = await exchange_instance.create_order(
                                        symbol=symbol,
                                        type='limit',
                                        side=new_order_side,
                                        amount=adjusted_quantity,
                                        price=new_order_level
                                    )
                                elif exchange_name == 'binance_spot':
                                    new_order = await exchange_instance.create_order(
                                        symbol=symbol,
                                        type='limit',
                                        side='sell',
                                        amount=min(adjusted_quantity, new_order_quantity),
                                        price=new_order_level
                                    )
                                elif exchange_instance.id.lower() == 'upbit':
                                    new_order = await retry_async(strategy.place_order, exchange_instance, symbol, order_type='limit',side='buy', amount = adjusted_quantity, price = new_order_level)
                                elif exchange_name == 'okx':
                                    #print('okx_order9')
                                    new_order = await exchange_instance.create_order(
                                        symbol=symbol,
                                        type='limit',
                                        side=new_order_side,
                                        amount=adjusted_quantity,
                                        price=new_order_level
                                    )
                                elif exchange_name == 'okx_spot':
                                    new_order = await exchange_instance.create_order(
                                        symbol=symbol,
                                        type='limit',
                                        side='sell',
                                        amount=adjusted_quantity,
                                        price=new_order_level
                                    )
                            except Exception as e:
                                print(f" {user_id} :An error occurred5: {e}")    
                            print(f"New order placed at {new_order_level}")
                            order_placed[int(level_index)] = True # 주문이 성공적으로 생성되었음을 표시
                            await add_placed_price(exchange_name, user_id, symbol, new_order_level)
                            await set_order_placed(exchange_name, user_id, symbol, new_order_level, level_index = level_index)
                        else:
                            print(f"{symbol}의 {level_index}레벨 주문이 이미 있습니다.(check_order_status)")
                        
                        
                break
            elif fetched_order['status'] == 'canceled':
                order_placed[level_index] = False
                break
            await asyncio.sleep(3)

    finally:
        order_placed[int(level_index)] = False
        await redis.close()
        return order_placed



MAX_RETRIES = 3
RETRY_DELAY = 4  # 재시도 사이의 대기 시간(초)

# retry_async is now imported from shared.utils







