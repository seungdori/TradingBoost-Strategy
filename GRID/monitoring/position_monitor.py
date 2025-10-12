"""GRID Trading Bot - Position Monitoring Module

포지션 및 주문 모니터링 기능:
- monitor_tp_orders_websocekts: TP 주문 WebSocket 모니터링
- monitor_positions: 포지션 모니터링
- monitor_custom_stop: 커스텀 스탑 모니터링
- check_entry_order: 진입 주문 확인
- check_and_close_positions: 포지션 청산 확인
- manually_close_positions: 수동 청산
- manually_close_symbol: 심볼별 수동 청산

Note: monitor_and_handle_tasks moved to task_manager to break circular dependency
"""

# ==================== 표준 라이브러리 ====================
import asyncio
import json
import logging
import random
import traceback
from datetime import datetime
from typing import Any, Dict, List, Optional

# ==================== 외부 라이브러리 ====================
import ccxt
from ccxt.async_support import ExchangeError, NetworkError

from GRID import telegram_message

# ==================== Core 모듈 ====================
from GRID.core.redis import get_redis_connection

# ==================== 프로젝트 모듈 ====================
from GRID.database import redis_database
from GRID.database.redis_database import update_active_grid, update_take_profit_orders_info

# Removed circular import: create_recovery_tasks, handle_task_completion moved to task_manager
from GRID.routes.logs_route import add_log_endpoint as add_user_log

# ==================== Services ====================
from GRID.services.balance_service import get_all_positions, get_position_size
from GRID.services.order_service import get_take_profit_orders_info
from GRID.services.user_management_service import get_user_data
from GRID.strategies import strategy
from GRID.trading.instance_manager import get_exchange_instance
from GRID.trading.shared_state import cancel_state, user_keys

# ==================== Utils ====================
from shared.utils import parse_bool, retry_async

logger = logging.getLogger(__name__)


# ==============================================================================
#                          Monitoring Functions
# ==============================================================================

async def monitor_tp_orders_websocekts(exchange_name, symbol_name, user_id, level_index, take_profit_orders_info):
    global cancel_state, user_keys
    #print(f"take_profit_orders_info: {take_profit_orders_info}")
    redis = await get_redis_connection()
    user_key = f"exchange:{exchange_name}:user:{user_id}"
    first_time_check = True
    is_running = await redis.hget(user_key, 'is_running')
    try:
        if is_running is not None:
            is_running = is_running.decode('utf-8') if isinstance(is_running, bytes) else str(is_running)
            is_running = bool(int(is_running or '0'))
        else:
            is_running = False
    except Exception as e:
        print(f"An error occurred on getting is_running! : {str(e)}")
    #print(f"{symbol_name}으로 익절 주문 감시 시작")
    
    async def handle_order_update(order, level, symbol_name):
        if level is not None:
            if order['status'] == 'closed':
                print(f"레벨 {level} 익절 주문 체결")
                #global_messages.trading_message.put(f"{symbol_name}의 {level}번째 그리드 익절 주문이 체결되었습니다.\n[수량 : {info['quantity']}, 가격 : {info['target_price']} 시간 : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]")
                message = f"{symbol_name}의 {level}번째 그리드 익절 주문이 체결되었습니다.\n[수량 : {info['quantity']}, 가격 : {info['target_price']} 시간 : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]"
                await add_user_log(user_id, message)
                grid_count = 1 if order['side'] == 'buy' else -1
                await update_active_grid(redis, exchange_name, user_id, symbol_name, level, entry_price = 0.0, position_size = 0.0, execution_time = datetime.now(), grid_count = grid_count ,pnl = None)
                await update_take_profit_orders_info(redis, exchange_name, user_id, symbol_name, level, order_id = None, new_price = 0.0, quantity = 0.0, active = False, side = None)
                asyncio.create_task(telegram_message.send_telegram_message(message, exchange_name, user_id))
                if info['quantity'] == 0:
                    print("❗️DEBUG: 익절 주문 수량이 0입니다. 확인이 필요합니다")
                    print(f"❗️DEBUG: 익절 주문 정보: {info}")
                    #print(f"take_profit_orders_info: {take_profit_orders_info}")
                    #asyncio.create_task(telegram_message.send_telegram_message(f"❗️DEBUG: {symbol_name}의 익절 주문 수량이 0입니다. 확인이 필요합니다", exchange_name, user_id))
                take_profit_orders_info[str(level)] = {"order_id": None, "quantity": 0, "target_price": 0, "active": False, "side": None}
                await update_take_profit_orders_info(redis, exchange_name, user_id, symbol_name, level_index, order_id = None, new_price = 0.0, quantity = 0.0, active = False, side = None)
                print(f"{user_id} : {symbol_name}의 {level}번째 그리드 익절 주문이 체결되었습니다.")
            elif order['status'] == 'canceled':
                current_time = datetime.now()
                minutes = current_time.minute
                seconds = current_time.second
                if ((minutes in [14, 29, 44, 59] and seconds >= 58)) : #TODO : cancel_state == 1일때 구현 필요. :
                    take_profit_orders_info[level] = {"order_id": None, "quantity": info['quantity'], "target_price": 0, "active": True, "side": None}
                    await update_take_profit_orders_info(redis, exchange_name, user_id, symbol_name, level, order_id = None, new_price = 0.0, quantity = info['quantity'], active = True,  side = None)
                else:
                    take_profit_orders_info[level] = {"order_id": None, "quantity": info['quantity'], "target_price": 0, "active": True, "side": None} #<-- 이게 active가 True인건지, 확인이 필요함. <--0705. False가 맞다. cancel은 기본적으로 직접 한거니까. 그런데, 현재 중앙통제 구조에서는 True도맞다
                    await update_take_profit_orders_info(redis, exchange_name, user_id, symbol_name, level, order_id = None, new_price = 0.0, quantity = info['quantity'], active = False,  side = None)
                print(f"{user_id} : {symbol_name}의 {level}번째 그리드 익절 주문이 취소되었습니다. 익절 테스크를 종료합니다")
                return
            #else:
            #    print(f"레벨 {level} 주문 상태 업데이트: {order['status']}")
    try:
        exchange_instance = await get_exchange_instance(exchange_name, user_id)
    except Exception as e:
        print(f"{user_id} : An error occurred21: {e}")
        return
    try:
        while True:
            await asyncio.sleep(random.uniform(0.5, 2))
            current_time = datetime.now()
            minutes = current_time.minute
            seconds = current_time.second
            # 15분 단위 시간 확인 (14분 55초, 29분 55초, 44분 55초, 59분 55초에 종료)
            #take_profit_orders_info = user_keys[user_id]["symbols"][symbol_name]["take_profit_orders_info"]
            take_profit_orders_info = await get_take_profit_orders_info(redis, exchange_name, user_id, symbol_name, level_index,  force_restart=False)
            #print("15분확인", take_profit_orders_info)
            if ((minutes in [15, 30, 45, 0] and seconds >= 55)) and not first_time_check:
                #print("15분봉 마감 도달 - 익절 관리 종료")
                try:
                    orders_to_cancel = []
                    for level, info in take_profit_orders_info.items():
                        if info["order_id"] is not None:
                            try:
                                orders_to_cancel.append(info["order_id"])
                                #await exchange_instance.cancel_order(info["order_id"], symbol_name) #<-- batch 주문으로 중앙화 
                            except Exception as e:
                                print(f"익절 주문 취소 실패. {symbol_name} {level}레벨, {info['order_id']}")
                                await telegram_message.send_telegram_message(f"익절 주문 취소 실패: {e}", exchange_name, user_id)
                    return
                except Exception as e:
                    print(f"익절 관리 종료 혹은 주문 취소할 것 없음 Monitor_tp_orders: {e}")
                    return
            else:
                for level, info in take_profit_orders_info.items():
                    if info["active"] and info["order_id"] is not None:
                        try:
                            #print(f" {symbol_name} 레벨 {level} 익절 주문 감시 시작")
                            order = await exchange_instance.fetch_order(info["order_id"], symbol_name) # type: ignore[union-attr]
                            await handle_order_update(order, level, symbol_name)
                        except Exception as e:
                            if 'Order does not exist' in str(e):
                                print(f"{user_id} : 익절 주문이 존재하지 않음. {symbol_name} {level}레벨, {info['order_id']}")
                                await update_take_profit_orders_info(redis, exchange_name, user_id, symbol_name, level, order_id = None, new_price = 0.0, quantity = 0.0, active = False, side = None)
                                continue
                first_time_check = False
                await asyncio.sleep(4.36)  # 4초마다 체크

    except Exception as e:
        print(f"{user_id} : 기타 예외 처리1: {e}")
        traceback.print_exc()
        await asyncio.sleep(5)
    #####TODO : 인스턴스 재활용버젼에서는 필요없어서 우선 확인
    finally:
        return
    #    if exchange_instance is not None:
    #        await exchange_instance.close()
        
    
#================================================================================================
# Monitor SL Orders
#================================================================================================





async def monitor_positions(exchange_name, user_id):
    redis = await get_redis_connection()
    retry_count = 0
    max_retry_count = 3
    user_data = await redis.hgetall(f'{exchange_name}:user:{user_id}')
    running_symbols: set[str] = set(json.loads(user_data.get('running_symbols', '[]')))
    await asyncio.sleep(4.5)
    exchange = None
    is_running = parse_bool(user_data.get('is_running', '0'))
    if is_running:
        try:
            exchange = await get_exchange_instance(exchange_name, user_id)
            await asyncio.sleep(0.8)
            while True:
                is_running = parse_bool(user_data.get('is_running', '0'))
                try:
                    if (not is_running):
                        return
                    await check_and_close_positions(exchange, user_id)
                    if not running_symbols and not is_running:  # running_symbols가 비었는지 확인
                        print("모든 포지션을 청산했습니다. 모니터링을 종료합니다.") # type: ignore[unreachable]
                        break
                    await asyncio.sleep(15)  # 15초 대기
                except Exception as e:
                    print(f"{user_id} : An error occurred on monitor_positions1: {e}")
                    print(traceback.format_exc())
                    retry_count =+ 1
                    if max_retry_count == retry_count:
                        print(f"모니터링 SL테스크 생성 중 오류가 발생하여 종료합니다.")
                        break
                    await asyncio.sleep(4)
                    continue
        except Exception as e:
            if 'API' in str(e):
                print(f"{user_id} API 키 오류로 인한 모니터링 종료")
                await redis.hset(f'{exchange_name}:user:{user_id}', 'is_running', 0)
                return
                
            print(f"{user_id} : An error occurred on monitor_positions0: {e}")
            print(traceback.format_exc())
        finally:
            return
            #if exchange:
            #    await exchange.close()
    else:
        print(f"User {user_id} is not running. Stopping monitor_positions.")
        return
            
            


async def monitor_custom_stop(exchange_name, user_id, custom_stop):
    redis = await get_redis_connection()
    try:
        print(f"Starting monitor_custom_stop for user {user_id} on {exchange_name}")
        while True:
            user_key = f'{exchange_name}:user:{user_id}'
            is_running = await redis.hget(user_key, 'is_running')
            if is_running is not None:
                try:
                    is_running = is_running.decode('utf-8') if isinstance(is_running, bytes) else str(is_running)
                    is_running = bool(int(is_running or '0'))
                except Exception as e:
                    print(f"{user_id} : An error occurred on getting is_running! : {str(e)}")
                    is_running = True
            else:
                is_running = False
            #print(f"Debug: User {user_id} is_running status: {is_running}")  # 디버그 로그 추가

            if not is_running:
                logger.info(f"User {user_id} is not running. Stopping monitor_custom_stop.")
                break

            try:
                await check_entry_order(exchange_name, user_id, custom_stop)
            except Exception as e:
                print(f"{user_id} : An error occurred on check_entry_order: {e}")
                print(traceback.format_exc())

            await asyncio.sleep(15)  # 15초 대기
        if not is_running:
            print(f"User {user_id} is not running. Stopping monitor")
        
    except Exception as e:
        print(f"{user_id} : An error occurred on monitor_custom_stop: {e}")
        print(traceback.format_exc())
        return

    finally:
        await redis.close()
        print(f"monitor_custom_stop for user {user_id} on {exchange_name} has stopped.")
        return



async def check_entry_order(exchange_name, user_id, custom_stop):
    redis = await get_redis_connection()
    exchange = None
    try:
        user_data = await redis.hgetall(f'{exchange_name}:user:{user_id}')
        if not user_data:
            print(f"No data found for user {user_id}")
            return

        running_symbols = set(json.loads(user_data.get('running_symbols', '[]')))
        symbols_data = json.loads(user_data.get('symbols', '{}'))

        for symbol in running_symbols:
            if symbol not in symbols_data:
                continue

            last_entry_time = symbols_data[symbol].get("last_entry_time")
            if custom_stop > 0 and last_entry_time is not None:
                last_entry_time = datetime.fromisoformat(last_entry_time)
                if (datetime.now() - last_entry_time).total_seconds() >= custom_stop * 60:
                    exchange = await get_exchange_instance(exchange_name, user_id)
                    trades = await exchange.fetch_my_trades(symbol, limit=1) # type: ignore[union-attr]
                    if trades:
                        actual_last_entry_time = datetime.strptime(trades[0]['datetime'], "%Y-%m-%dT%H:%M:%S.%fZ")
                        if (datetime.now() - actual_last_entry_time).total_seconds() >= custom_stop * 60:
                            print(f"{user_id} : 마지막 진입 시간이 지정된 시간 {custom_stop}분을 초과하여 {symbol} 포지션을 청산합니다.\n마지막 진입 : {actual_last_entry_time}")
                            await manually_close_symbol(exchange_name, user_id, symbol)
                        else:
                            # 실제 마지막 진입 시간으로 Redis 업데이트
                            symbols_data[symbol]["last_entry_time"] = actual_last_entry_time.isoformat()
                            await redis.hset(f'{exchange_name}:user:{user_id}', 'symbols', json.dumps(symbols_data))
                            print(f"{symbol}의 last_entry_time을 {actual_last_entry_time}으로 업데이트했습니다.")

    except Exception as e:
        print(f"{user_id} : An error occurred on check_entry_order: {e}")
        print(traceback.format_exc())
    ####TODO : 인스턴스 재활용버젼에서는 필요없어서 우선 확인
    #finally:
    #    if exchange is not None:
    #        await exchange.close()



async def check_and_close_positions(exchange, user_id):
    redis = await get_redis_connection()
    try:
        exchange_name = str(exchange.id).lower()
        user_key = f'{exchange_name}:user:{user_id}'
        user_data = await redis.hgetall(user_key)
        
        running_symbols = set(json.loads(user_data.get('running_symbols', '[]')))
        is_running = parse_bool(user_data.get('is_running', '0'))
        stop_loss = float(user_data.get('stop_loss', 0))
        if not is_running:
            return
        if exchange_name == 'okx' or exchange_name == 'okx_spot':
            # 캐시 키 생성
            cache_key = f'{exchange_name}:positions:{user_id}'

            # 캐시에서 포지션 데이터 가져오기 시도
            cached_positions = await redis.get(cache_key)
            if cached_positions:
                try:
                    positions_data = json.loads(cached_positions)
                    #logger.info(f"Cached positions data for user {user_id}: {positions_data}")
                    if isinstance(positions_data, list):
                        for position in positions_data:
                            
                            if isinstance(position, dict):
                                # Process each position
                                symbol = position.get('instId')
                                if symbol in running_symbols:
                                    # Your position processing logic here
                                    pass
                            else:
                                logger.warning(f"Unexpected position data format for user {user_id}: {position}")
                    elif isinstance(positions_data, dict):
                        # If positions_data is a dict, it might be a single position
                        symbol = positions_data.get('instId')
                        if symbol in running_symbols:
                            # Your position processing logic here
                            pass
                    else:
                        logger.warning(f"Unexpected positions data format for user {user_id}: {positions_data}")

                except json.JSONDecodeError as e:
                    logger.error(f"Error decoding cached positions for user {user_id}: {e}")
                if positions_data is not None:
                    try:
                        if isinstance(positions_data, list):
                            for position in positions_data:
                                if isinstance(position, dict) and 'instId' in position:
                                    symbol = position['instId']
                                    if symbol in running_symbols:

                                        quantity = float(position['pos']) if position['pos'] else 0.0
                                        avg_entry_price = float(position['avgPx']) if position['avgPx'] else 0.0
                                        current_price = float(position['last']) if position['last'] else 0.0
                                        side = 'long' if quantity > 0 else 'short'
                                        #print('여기까지 확인(ws)! ', symbol, quantity, avg_entry_price, current_price, side)
                                        if side == 'long':
                                            pnl_percent = ((current_price - avg_entry_price) / avg_entry_price) * 100
                                        else:  # short position
                                            pnl_percent = ((avg_entry_price - current_price) / avg_entry_price) * 100

                                        if stop_loss > 0 and pnl_percent < -stop_loss:
                                            print(f"{user_id} : Warning: {symbol} has exceeded the stop loss threshold with a PnL% of {pnl_percent}")
                                            await strategy.close_position(exchange, symbol, side, abs(quantity), user_id)

                                            message = f"⚠️{user_id} {symbol}의 손실률이 -{stop_loss}%를 초과하여 포지션을 청산합니다.\n평균단가 : {avg_entry_price}\n방향 : {side} \nPNL퍼센트 : {round(pnl_percent,2)}"
                                            await telegram_message.send_telegram_message(message, exchange_name, user_id)
                                            await add_user_log(user_id, message)

                                            completed_symbols = set(json.loads(user_data.get('completed_trading_symbols', '[]')))
                                            completed_symbols.add(symbol)
                                            running_symbols.remove(symbol)

                                            await redis.hset(user_key, 'completed_trading_symbols', json.dumps(list(completed_symbols)))
                                            await redis.hset(user_key, 'running_symbols', json.dumps(list(running_symbols)))
                                            print(f"{user_id} :  changed running symbol : {running_symbols}")

                                            print(f"❗️{symbol} removed from running_symbols for user {user_id}.")

                                            await asyncio.sleep(6)
                    except Exception as e:
                        print(f"{user_id} : An error occurred on check_and_close_positions: {e}. type : {type(positions_data)}")
                        print(traceback.format_exc())
            else:
                try:
                    await asyncio.sleep(random.uniform(0.1, 1) + 0.9)
                    #position_data = json.loads(cached_positions)
                    positions_data = await exchange.private_get_account_positions()
                    await redis.set(cache_key, json.dumps(positions_data), ex=20)
                except Exception as e:
                    raise e
                
                for position in positions_data['data']:
                    symbol = position['instId']
                    if symbol in running_symbols:
                        quantity = float(position['pos']) if position['pos'] else 0.0
                        avg_entry_price = float(position['avgPx']) if position['avgPx'] else 0.0
                        current_price = float(position['last']) if position['last'] else 0.0
                        side = 'long' if quantity > 0 else 'short'

                        print(f"Checking position for {symbol} , {quantity}, {avg_entry_price}, {current_price}, {side}")
                        if side == 'long':
                            pnl_percent = ((current_price - avg_entry_price) / avg_entry_price) * 100
                        else:  # short position
                            pnl_percent = ((avg_entry_price - current_price) / avg_entry_price) * 100

                        if stop_loss > 0 and pnl_percent < -stop_loss:
                            print(f"Warning: {symbol} has exceeded the stop loss threshold with a PnL% of {pnl_percent}")
                            await strategy.close_position(exchange, symbol, side, abs(quantity), user_id)

                            message = f"⚠️{user_id} {symbol}의 손실률이 -{stop_loss}%를 초과하여 포지션을 청산합니다.\n평균단가 : {avg_entry_price}\n방향 : {side} \nPNL퍼센트 : {round(pnl_percent,2)}"
                            await telegram_message.send_telegram_message(message, exchange_name, user_id)
                            await add_user_log(user_id, message)

                            completed_symbols = set(json.loads(user_data.get('completed_trading_symbols', '[]')))
                            completed_symbols.add(symbol)
                            running_symbols.remove(symbol)

                            await redis.hset(user_key, 'completed_trading_symbols', json.dumps(list(completed_symbols)))
                            await redis.hset(user_key, 'running_symbols', json.dumps(list(running_symbols)))
                            print(f" changed running symbol : {running_symbols}")

                            print(f"❗️{symbol} removed from running_symbols for user {user_id}.")

                            await asyncio.sleep(6)
        try:
            if exchange_name == 'upbit':
                await asyncio.sleep(random.uniform(0.6, 2.2))
                balance = await exchange.fetch_balance()
                if symbol is not None:
                    base_currency = symbol.split('-')[1]  # 'KRW-ETC'에서 'ETC'를 추출
                else:
                    base_currency = 'UNKNOWN'
                print("fetched positions for upbit")
                for position in positions_data:
                    symbol = position['symbol']
                    if symbol in running_symbols:
                        print(position)
                        quantity = float(position['amount']) if position['amount'] else 0.0  # 'pos' 값을 float로 변환합니다.
                        avg_entry_price = float(position['avgPx']) if position['avgPx'] else 0.0  # 'avgPx' 값을 float로 변환합니다.
                        current_price = float(position['last']) if position['last'] else 0.0  # 'last' 값을 float로 변환합니다.
                        side = 'long' if quantity > 0 else 'short'  # 'posSide' 값 확인 (long/short)

                        if side == 'long':
                            pnl_percent = ((current_price - avg_entry_price) / avg_entry_price) * 100
                        else:  # short position
                            pnl_percent = ((avg_entry_price - current_price) / avg_entry_price) * 100

                        #print(f"[{user_id}] Symbol: {symbol}, Quantity: {quantity}, PnL%: {pnl_percent}")

                        if (stop_loss is not None) and (stop_loss > 0) and pnl_percent < -stop_loss:
                            print(f"Warning: {symbol} has exceeded the stop loss threshold with a PnL% of {pnl_percent}")
                            await strategy.close_position(exchange, symbol, side, quantity, user_id)

                            await telegram_message.send_telegram_message(f"⚠️ {symbol}의 손실률이 -{stop_loss}%를 초과하여 포지션을 청산합니다.\n평균단가 : {avg_entry_price}\n방향 : {side} \nPNL퍼센트 : {round(pnl_percent,2)}", exchange, user_id)
                            message = f"⚠️ {symbol}의 손실률이 -{stop_loss}%를 초과하여 포지션을 청산합니다.\n평균단가 : {avg_entry_price}\n방향 : {side} \nPNL퍼센트 : {round(pnl_percent,2)}"
                            #await manager.add_user_message(user_id, message)
                            await add_user_log(user_id, message)
                            #global_messages.trading_message.put(f"⚠️ {symbol}의 손실률이 -{stop_loss}%를 초과하여 포지션을 청산합니다.\n평균단가 : {avg_entry_price}\n방향 : {side} \nPNL퍼센트 : {round(pnl_percent,2)}")

                            print(f"❗️{symbol} removed from running_symbols.")

                            #포지션 청산 후, 새로운 포지션 진입 로직 
                            await asyncio.sleep(5)
                        
                        
        except Exception as e:
            print(f"{user_id} : An error occurred3153: {e}")
            raise e
    except Exception as e:
        if 'API' in str(e):
            print(f"{user_id} : API 키 오류로 인한 모니터링 종료")
            await redis.hset(f'{exchange_name}:user:{user_id}', 'is_running', 0)
            raise e
        if 'Invalid' in str(e):
            print(f"{user_id} : API 키 오류로 인한 모니터링 종료")
            await redis.hset(f'{exchange_name}:user:{user_id}', 'is_running', 0)
            raise e
        if 'AuthenticationError' in str(e):
            print(f"{user_id} : API 키 오류로 인한 모니터링 종료")
            await redis.hset(f'{exchange_name}:user:{user_id}', 'is_running', 0)
            raise e
        print(f"{user_id}: An error occurred30131: {e}")
        raise e
    finally:
        if redis is not None:
            await redis.close()



async def manually_close_positions(exchange_name, user_id):
    redis = await get_redis_connection()
    exchange = None
    try:
        user_key = f'{exchange_name}:user:{user_id}'
        user_data = await redis.hgetall(user_key)
        running_symbols = set(json.loads(user_data.get('running_symbols', '[]')))
        
        exchange = await get_exchange_instance(exchange_name, user_id)
        
        if exchange_name == 'okx' or exchange_name == 'okx_spot':
            positions_data = await exchange.private_get_account_positions() # type: ignore[union-attr]
            for position in positions_data['data']:
                symbol = position['instId']
                if symbol in running_symbols:
                    quantity = float(position['pos'])
                    side = 'long' if quantity > 0 else 'short'
                    await strategy.close_position(exchange, symbol, side, abs(quantity), user_id)
        elif exchange_name == 'upbit':
            position_data = await exchange.fetch_balance() # type: ignore[union-attr]
            for symbol in running_symbols:
                base_currency = symbol.split('-')[1]
                quantity = float(position_data['total'].get(base_currency, 0))
                if quantity > 0:
                    await strategy.close_position(exchange, symbol, 'long', quantity, user_id)
        else:
            positions_data = await exchange.fetch_positions() # type: ignore[union-attr]
            for position in positions_data:
                symbol = position['symbol']
                if symbol in running_symbols:
                    quantity = float(position['amount'])
                    side = 'long' if quantity > 0 else 'short'
                    await strategy.close_position(exchange, symbol, side, abs(quantity), user_id)
        
        log_message = "{user_id}  : 전체 포지션을 종료하고 새로운 종목으로 탐색합니다"
        message = "{user_id}  : 전체 포지션을 종료하고 새로운 종목으로 탐색합니다"
        await telegram_message.send_telegram_message(message, exchange_name, user_id)
        await add_user_log(user_id, log_message)
        
        completed_symbols = set(json.loads(user_data.get('completed_trading_symbols', '[]')))
        completed_symbols.update(running_symbols)
        running_symbols.clear()
        
        await redis.hset(user_key, 'completed_trading_symbols', json.dumps(list(completed_symbols)))
        await redis.hset(user_key, 'running_symbols', json.dumps(list(running_symbols)))
        
        print(f"❗️All symbols removed from running_symbols for user {user_id}.")
        
        await asyncio.sleep(3)
        
    except Exception as e:
        print(f"{user_id} : An error occurred in manually_close_positions: {e}")
        print(traceback.format_exc())
    finally:
        #if exchange is not None:
        #    await exchange.close()
        if redis is not None:
            await redis.close()
    


async def manually_close_symbol(exchange_name, user_id, symbol):
    redis = await get_redis_connection()
    exchange = None
    try:
        user_key = f'{exchange_name}:user:{user_id}'
        user_data = await redis.hgetall(user_key)
        running_symbols = set(json.loads(user_data.get('running_symbols', '[]')))
        
        if symbol not in running_symbols:
            print(f"Symbol {symbol} is not in running symbols for user {user_id}")
            return
        
        exchange = await get_exchange_instance(exchange_name, user_id)
        
        if exchange_name == 'okx' or exchange_name == 'okx_spot':
            positions_data = await exchange.private_get_account_positions() # type: ignore[union-attr]
            for position in positions_data['data']:
                if position['instId'] == symbol:
                    quantity = float(position['pos'])
                    side = 'long' if quantity > 0 else 'short'
                    await strategy.close_position(exchange, symbol, side, abs(quantity), user_id)
                    break
        elif exchange_name == 'upbit':
            position_data = await exchange.fetch_balance() # type: ignore[union-attr]
            base_currency = symbol.split('-')[1]
            quantity = float(position_data['total'].get(base_currency, 0))
            if quantity > 0:
                await strategy.close_position(exchange, symbol, 'long', quantity, user_id)
        else:
            positions_data = await exchange.fetch_positions() # type: ignore[union-attr]
            for position in positions_data:
                if position['symbol'] == symbol:
                    quantity = float(position['amount'])
                    side = 'long' if quantity > 0 else 'short'
                    await strategy.close_position(exchange, symbol, side, abs(quantity), user_id)
                    break
        
        message = f"{user_id}  : {symbol}에 대해 설정한 기간동안 포지션 진입이 없습니다.\n{symbol}을 종료하고 새로운 종목으로 탐색합니다"
        await telegram_message.send_telegram_message(message, exchange_name, user_id)
        await add_user_log(user_id, message)
        
        completed_symbols = set(json.loads(user_data.get('completed_trading_symbols', '[]')))
        completed_symbols.add(symbol)
        running_symbols.remove(symbol)
        
        await redis.hset(user_key, 'completed_trading_symbols', json.dumps(list(completed_symbols)))
        await redis.hset(user_key, 'running_symbols', json.dumps(list(running_symbols)))
        
        print(f"❗️{symbol} removed from running_symbols for user {user_id}.")
        
        await asyncio.sleep(3)
        
    except Exception as e:
        print(f"{user_id} : An error occurred in manually_close_symbol: {e}")
        print(traceback.format_exc())
    finally:
        if exchange is not None:
            await exchange.close()
        await redis.close()
    



# =======[TOOLS_SECTION_START]=======
# Tools 
# ==================================
# 타임프레임을 float형태로
# 다음 타임프레임까지의 시간 계산
# 타임존 계산
# ===================================




# monitor_and_handle_tasks moved to GRID.jobs.task_manager to break circular dependency



