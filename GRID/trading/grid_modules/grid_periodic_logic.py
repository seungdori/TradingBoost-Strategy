"""GRID Trading Periodic Logic Module

주기적 로직 관련 함수들:
- periodic_15m_logic: 15분 주기 로직
"""

import asyncio
import json
import logging
import random
import time
import traceback
from datetime import datetime
from typing import Dict, Any, Optional

import pandas as pd

from GRID.database import redis_database
from GRID.database.redis_database import update_take_profit_orders_info
from GRID.main import periodic_analysis
from GRID.main.main_loop import add_user_log
from GRID.monitoring.monitor_tp_orders import monitor_tp_orders_websocekts
from GRID.services.balance_service import get_balance_of_symbol, get_position_size
from GRID.services.order_service import (
    get_take_profit_orders_info, add_placed_price, set_order_placed,
    is_price_placed, is_order_placed, okay_to_place_order
)
from GRID.strategies import strategy
from GRID.trading.shared_state import user_keys
from GRID.utils.price import get_corrected_rounded_price
from GRID.utils.redis_helpers import reset_order_placed, get_order_placed
from HYPERRSI import telegram_message
from shared.utils import retry_async

logger = logging.getLogger(__name__)

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
                                elif level_index == 1 and tp_order_side == 'buy':
                                    new_price = float(grid_levels[f'grid_level_{1}'].iloc[-1])*0.99
                                elif level_index == grid_num and tp_order_side == 'sell':
                                    new_price = float(grid_levels[f'grid_level_{grid_num}'].iloc[-1])*1.01
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
                                                await telegram_message.send_telegram_message(f'🚨{symbol}의 {level} 익절물량이 0보다 작으므로 확인해봐야한다. 함수 시작saved : {saved_quantity}', exchange_name = 'upbit', user_id = user_id, debug = True)  # type: ignore[call-arg]

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
                                        asyncio.create_task(monitor_tp_orders_websocekts(user_id, exchange_name, symbol_name, take_profit_orders_info))
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
                                asyncio.create_task(monitor_tp_orders_websocekts(user_id, exchange_name, symbol_name, take_profit_orders_info))
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
                                asyncio.create_task(monitor_tp_orders_websocekts(user_id, exchange_name, symbol_name, take_profit_orders_info))
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
                            new_price = float(upper_levels[0])  # type: ignore[unreachable]
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
                            asyncio.create_task(monitor_tp_orders_websocekts(user_id, exchange_name, symbol_name, take_profit_orders_info))
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
        


