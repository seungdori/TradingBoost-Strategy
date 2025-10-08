"""GRID Trading Monitoring Module

주문 모니터링 관련 함수들:
- check_order_status: 주문 상태 확인 및 처리
"""

import asyncio
import json
import logging
import random
import time
import traceback
from datetime import datetime
from typing import Dict, Any, Optional

from ccxt.async_support import NetworkError, ExchangeError

from GRID.core.redis import get_redis_connection
from GRID.core.websocket import log_exception
from GRID.database import redis_database
from GRID.database.redis_database import update_take_profit_orders_info, update_active_grid
from GRID.main.main_loop import add_user_log
from GRID.monitoring.position_monitor import monitor_tp_orders_websocekts
from GRID.services.balance_service import get_position_size
from GRID.services.order_service import (
    fetch_order_with_retry, add_placed_price, set_order_placed, okay_to_place_order, is_price_placed
)
from GRID.strategies import strategy
from GRID.trading.shared_state import user_keys
from GRID.utils.price import get_corrected_rounded_price
from GRID import telegram_message
from shared.utils import retry_async
from shared.utils.exchange_precision import adjust_price_precision

logger = logging.getLogger(__name__)

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
                        new_order_side: str | None = 'sell' #<-- 새로운 주문이 걸릴 side(숏 주문이 추가로 걸릴 side)
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
                        if tp_order is not None:
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
                        if tp_order is not None:
                            for key in possible_order_id_keys:
                                if 'info' in tp_order and key in tp_order['info']:
                                    order_id = tp_order['info'][key]
                                if exchange_name == 'okx' or exchange_name == 'okx_spot':
                                    if (isinstance(order_id, int) or (isinstance(order_id, str)) and order_id.isdigit() and 1 <= len(order_id) <= 20):
                                        break
                                    else:
                                        print(f"잘못된 order_id: {order_id}")
                                else:
                                    if isinstance(order_id, int) or (isinstance(order_id, str) and (1 <= len(order_id) <= 60)):
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







