"""GRID Trading Entry Logic Module

진입 로직 관련 함수들:
- long_logic: 롱 진입 로직
- short_logic: 숏 진입 로직
"""

import asyncio
import logging
import random
import time
import traceback
from datetime import datetime
from typing import Any, Dict, List, Tuple

import pandas as pd

from GRID.database.redis_database import update_take_profit_orders_info
from GRID.routes.logs_route import add_log_endpoint as add_user_log
from GRID.services.balance_service import get_position_size
from GRID.services.order_service import (
    create_short_orders,
    fetch_order_with_retry,
    okay_to_place_order,
)
from GRID.strategies import strategy
from GRID.trading.grid_modules.grid_monitoring import check_order_status
from GRID.utils.price import (
    get_corrected_rounded_price,
    get_order_price_unit_upbit,
    round_to_upbit_tick_size,
)
from GRID.utils.redis_helpers import (
    add_placed_price,
    get_order_placed,
    is_order_placed,
    is_price_placed,
    set_order_placed,
)
from shared.utils import retry_async
from shared.utils.exchange_precision import adjust_price_precision

logger = logging.getLogger(__name__)

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

            


