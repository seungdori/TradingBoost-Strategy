
# 이 함수를 15분마다 호출하도록 설정
import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import random
import time
import traceback
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pdb import run
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple, Union, cast

import websockets
from redis import Redis

from GRID import telegram_message
from GRID.core.redis import get_redis_connection
from GRID.database import redis_database
from GRID.strategies import strategy
from GRID.trading import instance
from GRID.trading.redis_connection_manager import RedisConnectionManager
from GRID.trading.shared_state import cancel_state, user_keys
from shared.config import settings
from shared.utils import parse_bool, retry_async

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

REDIS_PASSWORD = settings.REDIS_PASSWORD

redis_manager = RedisConnectionManager()

#================================================================================================
# TOOLS
#================================================================================================

# parse_bool is now imported from shared.utils

# Exchange instance management with activity tracking

redis_connection: Optional[Any] = None
exchange_instances: Dict[str, Dict[str, Any]] = {}
INSTANCE_TIMEOUT = 3600  # 1 hour
MAX_RETRIES = 3
RETRY_DELAY = 3  # 재시도 사이의 대기 시간(초)

# retry_async is now imported from shared.utils


async def get_redis():
    """Get Redis connection using shared connection pool"""
    global redis_connection
    if redis_connection is None:
        redis_connection = await get_redis_connection()

    try:
        # Ping the Redis server to check if the connection is still alive
        await redis_connection.ping()
    except Exception:
        # If ping fails, create a new connection
        redis_connection = await get_redis_connection()

    return redis_connection

async def close_redis() -> None:
    global redis_connection
    if redis_connection:
        await redis_connection.close()
        redis_connection = None

position_data_logger = logging.getLogger('position_data')

@asynccontextmanager
async def manage_redis_connection():
    redis = await get_redis()
    try:
        yield redis
    finally:
        # We don't close the connection here, it will be reused
        pass
    





async def get_user_data(exchange_name: str, user_id: int, field: Optional[str] = None) -> Union[Dict[str, Any], Any]:
    redis = await get_redis_connection()
    user_key = f"{exchange_name}:user:{user_id}"
    
    json_fields = ["tasks", "running_symbols", "completed_trading_symbols", "enter_symbol_amount_list"]
    boolean_fields = ["is_running"]
    numeric_fields = ["leverage", "initial_capital"]
    
    def parse_boolean(value: str) -> bool:
        return value.lower() in ('true', '1', 'yes', 'on')
    
    if field:
        value = await redis.hget(user_key, field)
        if value is None:
            return None
        if field in json_fields:
            return json.loads(value)
        elif field in boolean_fields:
            return parse_boolean(value)
        elif field in numeric_fields:
            return float(value)
        else:
            return value
    else:
        data = await redis.hgetall(user_key)
        for key in data:
            if key in json_fields:
                data[key] = json.loads(data[key])
            elif key in boolean_fields:
                data[key] = parse_boolean(data[key])
            elif key in numeric_fields:
                data[key] = float(data[key])
        return data

async def set_user_data(exchange_name: str, user_id: int, data: Dict[str, Any], field: Optional[str] = None) -> None:
    redis = await get_redis_connection()
    user_key = f"{exchange_name}:user:{user_id}"
    
    json_fields = ["tasks", "running_symbols", "completed_trading_symbols", "enter_symbol_amount_list"]
    boolean_fields = ["is_running", "stop_task_only"]
    numeric_fields = ["leverage", "initial_capital"]
    
    def serialize_value(key: str, value: Any) -> str:
        if key in json_fields:
            return json.dumps(value)
        elif key in boolean_fields:
            return '1' if parse_bool(value) else '0'
        elif key in numeric_fields:
            return str(float(value))
        else:
            return str(value)
    
    if field:
        value = serialize_value(field, data)
        await redis.hset(user_key, field, value)
    else:
        serialized_data = {key: serialize_value(key, value) for key, value in data.items()}
        await redis.hmset(user_key, serialized_data)


async def should_log(redis: Any, log_interval: int = 30) -> bool:
    log_key = "last_log_time"
    if await redis.set(log_key, "1", nx=True, ex=log_interval):
        return True
    return False


#================================================================================================


async def get_exchange_instance(exchange_name: str, user_id: str) -> Any:
    key = f"{exchange_name}:{user_id}"
    current_time = time.time()
    
    if key in exchange_instances:
        instance_data = exchange_instances[key]
        if current_time - instance_data['last_used'] > INSTANCE_TIMEOUT:
            await instance_data['instance'].close()
            del exchange_instances[key]
        else:
            instance_data['last_used'] = current_time
            return instance_data['instance']
    
    new_instance = await create_exchange_instance(exchange_name, user_id)
    exchange_instances[key] = {
        'instance': new_instance,
        'last_used': current_time
    }
    return new_instance

async def create_exchange_instance(exchange_name, user_id):
    exchange_name = str(exchange_name).lower()
    try:
        if exchange_name == 'binance':
            exchange_instance = await instance.get_binance_instance(user_id)
        elif exchange_name == 'binance_spot':
            exchange_instance = await instance.get_binance_spot_instance(user_id)
            direction = 'long'
        elif exchange_name == 'upbit':
            exchange_instance = await instance.get_upbit_instance(user_id)
            direction = 'long'
        elif exchange_name == 'bitget':
            exchange_instance = await instance.get_bitget_instance(user_id)
        elif exchange_name == 'bitget_spot':
            exchange_instance = await instance.get_bitget_spot_instance(user_id)
            direction = 'long'
        elif exchange_name == 'okx':
            exchange_instance = await instance.get_okx_instance(user_id)
        elif exchange_name == 'okx_spot':
            exchange_instance = await instance.get_okx_spot_instance(user_id)
        return exchange_instance
    except Exception as e:
        error_message = str(e)
        if "API" in error_message:
            print("API key issue detected. Terminating process.")
            from GRID.strategies.grid_process import stop_grid_main_process
            await stop_grid_main_process(exchange_name, user_id)
            return
        print(f"Error getting exchange instance for{user_id}13,  {exchange_name}: {error_message}")
        return None

    


@asynccontextmanager
async def manage_exchange_instance(exchange_name: str, user_id: str) -> AsyncIterator[Any]:
    instance = await get_exchange_instance(exchange_name, user_id)
    try:
        yield instance
    finally:
        # Update last used time
        exchange_instances[f"{exchange_name}:{user_id}"]['last_used'] = time.time()

# Cleanup function
async def cleanup_connections() -> None:
    global redis_connection, exchange_instances
    try:
        if redis_connection:
            await redis_connection.close()
            redis_connection = None
        for instance in exchange_instances.values():
            if 'instance' in instance and hasattr(instance['instance'], 'close'):
                await instance['instance'].close()
    except Exception as e:
        logger.error(f"Error during connection cleanup: {e}", exc_info=True)
        
async def cleanup_inactive_instances():
    global exchange_instances
    current_time = time.time()
    keys_to_remove = []
    for key, instance_data in exchange_instances.items():
        try:
            if current_time - instance_data['last_used'] > INSTANCE_TIMEOUT:
                if 'instance' in instance_data and hasattr(instance_data['instance'], 'close'):
                    await instance_data['instance'].close()
                keys_to_remove.append(key)
        except Exception as e:
            logger.error(f"Error closing instance {key}: {e}", exc_info=True)
            keys_to_remove.append(key)  # Remove the instance even if closing fails
    
    for key in keys_to_remove:
        del exchange_instances[key]


#================================================================================================
# CENTRALIZE ORDER CANCELLATION
#================================================================================================
        
async def centralized_order_cancellation(exchange_name):
    global cancel_state, user_keys
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    logger = logging.getLogger('order_cancellation')


    async with manage_redis_connection() as redis:
        try:
            await redis.set('cancel_state', '1')
            cancel_state = True
            fetched_user_keys = await redis_database.get_user_keys(exchange_name)
            running_users = {
                user_id: user_data 
                for user_id, user_data in fetched_user_keys.items() 
                if parse_bool(user_data.get("is_running"))
            }
            logger.info('User keys obtained.')

            async def process_user(user_id, user_data):
                user_key = f'{exchange_name}:user:{user_id}'
                async with manage_exchange_instance(exchange_name, user_id) as exchange_instance:
                    try:
                        all_orders = await exchange_instance.fetch_open_orders()
                        print(f"Total open orders: {len(all_orders)}")
                        orders_by_symbol: dict[str, list[Any]] = {}
                        for order in all_orders:
                            if 'info' not in order or 'instId' not in order['info']:
                                print(f"Warning: Order without 'instId' key: {order}")
                                continue
                            
                            symbol = order['info']['instId']
                            if symbol not in orders_by_symbol:
                                orders_by_symbol[symbol] = []
                            orders_by_symbol[symbol].append(order)
                        
                        #print(f"Symbols with open orders: {list(orders_by_symbol.keys())}")
                        
                        running_symbols = json.loads(await redis.hget(user_key, 'running_symbols') or '[]')
                        logger.info(f"Starting order cancellation for user {user_id}. Running symbols: {running_symbols}")

                        tasks: list[Any] = []
                        for symbol_name in running_symbols:
                            print(f"{symbol_name}에 대한 주문 취소 시작")
                            if symbol_name in orders_by_symbol:
                                symbol_orders = orders_by_symbol[symbol_name]
                                #print(f"{symbol_orders}에 대한 주문 취소 시작")
                                if exchange_name == 'upbit':
                                    task = strategy.cancel_all_limit_orders(exchange_instance, symbol_name, user_id)
                                else:
                                    task = cancel_all_limit_orders_batch(exchange_instance, symbol_name, user_id, symbol_orders)
                                tasks.append(task)
                                tasks.append(asyncio.sleep(0.32))  # 0.1초 지연 추가
                            else:
                                logger.info(f"No orders found for symbol {symbol_name}")
                        
                        # 태스크 실행
                        results = await asyncio.gather(*tasks)
                        total_cancelled_orders = 0
                        result_index = 0
                        for i in range(0, len(results), 2):  # 2씩 증가: 결과와 sleep 건너뛰기
                            result = results[i]
                            if isinstance(result, Exception):
                                logger.error(f"Error cancelling orders for user {user_id}, symbol {running_symbols[result_index]}: {result}")
                            else:
                                cancelled_orders, failed_orders = result
                                total_cancelled_orders += len(cancelled_orders)
                                await update_take_profit_orders(redis, user_key, running_symbols[result_index], cancelled_orders, user_id)
                            result_index += 1
                    except Exception as e:
                        logger.error(f"Error processing user {user_id}: {e}")


            # Use a semaphore to limit concurrent user processing
            semaphore = asyncio.Semaphore(7)  # Adjust this value based on your system's capacity

            async def process_user_with_semaphore(user_id, user_data):
                async with semaphore:
                    await retry_async(process_user, user_id, user_data)

            await asyncio.gather(*[process_user_with_semaphore(user_id, user_data) for user_id, user_data in running_users.items()])

        except Exception as e:
            error_message = str(e)
            logger.exception(f"An error occurred during centralized order cancellation: {error_message}")
        finally:
            await asyncio.sleep(1)
            cancel_state = False
            await redis.set('cancel_state', '0')





async def cancel_all_limit_orders_batch(exchange_instance, symbol, user_id, orders):
    retry_delay = 2
    max_retries = 4
    retry_attempts = 0
    cancelled_orders = []
    failed_orders = []
    
    while retry_attempts < max_retries:
        try:
            limit_order_ids = [order['id'] for order in orders if order['type'] == 'limit']
            if not limit_order_ids:
                return [], []  # 취소할 지정가 주문이 없음
            
            # 배치로 주문 취소
            try:
                print(f"{symbol}에 대한 limit order 갯수 : {len(limit_order_ids)}")
                results = await exchange_instance.cancel_orders(limit_order_ids, symbol)
                for order_id, result in zip(limit_order_ids, results):
                    if isinstance(result, dict) and result.get('status') == 'canceled':
                        cancelled_orders.append(order_id)
                    else:
                        failed_orders.append((order_id, str(result)))
            except Exception as e:
                error_message = str(e)
                # 배치 취소가 지원되지 않는 경우, 개별 취소로 전환
                if "batch" in str(e).lower():
                    print(f"Batch cancellation not supported for {exchange_instance.id}, switching to individual cancellation.")
                    for order_id in limit_order_ids:
                        try:
                            await exchange_instance.cancel_order(order_id, symbol)
                            cancelled_orders.append(order_id)
                        except Exception as e:
                            failed_orders.append((order_id, str(e)))
                        await asyncio.sleep(0.35)  # 개별 취소 사이에 짧은 지연 추가
            
            return cancelled_orders, failed_orders
        except Exception as e:
            error_message = str(e)
            print(f"An error occurred while cancelling orders: {error_message}. Retrying...")
            retry_attempts += 1
            await asyncio.sleep(retry_delay)
    
    return [], []  # 모든 시도가 실패한 경우



async def cancel_orders_batch(exchange_instance, orders_to_cancel, symbol_name):
    try:
        # 대부분의 거래소는 batch_cancel_orders 메서드를 제공합니다.
        await exchange_instance.cancel_orders(orders_to_cancel, symbol_name)
    except AttributeError:
        # batch_cancel_orders가 없는 경우, 개별 취소를 사용하되 동시에 실행
        cancel_tasks = [exchange_instance.cancel_order(order_id, symbol_name) for order_id in orders_to_cancel]
        await asyncio.gather(*cancel_tasks)
        


#================================================================================================
# CHECK ENTRY
#================================================================================================


#================================================================================================
# SET USER STATUS
#================================================================================================

async def check_status_loop(exchange_name : str) -> None:
    redis = await get_redis_connection()
    zero_count = {}  # 각 사용자의 연속된 0 카운트를 저장하는 딕셔너리
    first_zero_time = {}  # 각 사용자의 첫 번째 0이 발생한 시간을 저장하는 딕셔너리
    while True:
        try:
            fetched_user_keys = await redis_database.get_user_keys(exchange_name)
            running_users = {
                user_id: user_data 
                for user_id, user_data in fetched_user_keys.items() 
                if parse_bool(user_data.get("is_running"))
                }
            for user_id, user_data in running_users.items():
                user_key = f'{exchange_name}:user:{user_id}'
                user_status = parse_bool(await redis.hget(user_key, 'is_running'))
                if user_status == True:
                    is_stopped = await redis.hget(user_key, 'is_stopped')
                    is_task_stopped = await redis.hget(user_key, 'stop_task_only')
                    if parse_bool(is_stopped) or parse_bool(is_task_stopped):
                        await redis.hset(user_key, 'is_running', '0')
                        await redis.hset(user_key, 'is_stopped', '0')
                        await redis.hset(user_key, 'stop_task_only', '0')
                    else:
                        all_order_length = await fetch_open_orders_length(redis, int(user_id))
                        #print(f"{user_id}의 모든 주문 길이: {all_order_length}")
                        if all_order_length == 0: 
                            
                            current_time = time.time()
                            current_minute = datetime.now().minute
                            if current_minute % 15 == 0:
                                pass
                            else:
                                if user_id not in zero_count:
                                    zero_count[user_id] = 1
                                    first_zero_time[user_id] = current_time
                                    #print(f"{user_id}의 첫 번째 order length 0 발생 시간: {first_zero_time[user_id]}")
                                    print(f"{user_id}의 첫 번째 order length 0 발생 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                                else:
                                    if current_time - first_zero_time[user_id] >= 360:  # 2분(120초 for tradingboost, 360 for futures) 경과 확인
                                        zero_count[user_id] += 1
                                        print(f"{user_id}의 연속된 0 카운트: {zero_count[user_id]}")
                                        if zero_count[user_id] >= 6:
                                            print(f"{user_id}의 연속된 0 카운트가 3 이상입니다. 주문 취소 및 재시작을 시작합니다.")
                                            # force_restart 로직 시작
                                            await restart_logic(redis, exchange_name, user_id)
                                            # 카운트 및 시간 초기화
                                            del zero_count[user_id]
                                            del first_zero_time[user_id]
                        else:
                            # all_order_length가 0이 아닌 경우, 카운트 및 시간 초기화
                            if user_id in zero_count:
                                del zero_count[user_id]
                            if user_id in first_zero_time:
                                del first_zero_time[user_id]
                                
        except Exception as e:
            print(f"Error in check_status_loop: {e}")
        
        await asyncio.sleep(60)  # 1분 대기
                        
async def get_request_body(redis: Any, exchange_id : str , user_id : int) -> str | None:
    """Redis에서 request_body를 가져옴"""
    redis_key = f"{exchange_id}:request_body:{user_id}"
    value = await redis.get(redis_key)
    if value is None:
        value = await redis.get(f"{exchange_id}:request_body:{user_id}:backup")
        if value is None:
            value = await redis.get(f"{exchange_id}:request_body:{user_id}:*")
    return cast(str | None, value)
                   
                

async def restart_logic(redis, exchange_name, user_id):
    request_body_str = await get_request_body(redis, exchange_id = exchange_name ,user_id = user_id)
    if request_body_str is None:
        return
    else:
        from GRID.routes.feature_route import restart_single_user
        await restart_single_user(exchange_name, user_id, request_body_str)
        
#================================================================================================
# UPDATE TAKE PROFIT ORDERS
#================================================================================================


async def update_take_profit_orders(redis, user_key, symbol_name, cancelled_orders, user_id):
    global user_keys
    symbol_key = f'{user_key}:symbol:{symbol_name}'
    take_profit_orders_info = json.loads(await redis.hget(symbol_key, 'take_profit_orders_info') or '{}')
    #print(f" **central** take_profit_orders_info : {take_profit_orders_info}. ")
    for order_id in cancelled_orders:
        for level, info in take_profit_orders_info.items():
            if info["order_id"] == order_id:
                take_profit_orders_info[level]["order_id"] = None
                take_profit_orders_info[level]["active"] = True
                user_keys[user_id]["symbols"][symbol_name]["take_profit_orders_info"][level]["order_id"] = None
                user_keys[user_id]["symbols"][symbol_name]["take_profit_orders_info"][level]["active"] = True
    
    await redis.hset(symbol_key, 'take_profit_orders_info', json.dumps(take_profit_orders_info))

async def schedule_order_cancellation(exchange_name):
    print(f"Starting centralized order cancellation for {exchange_name}")
    while True:
        current_time = datetime.now()
        try:
            # 다음 실행 시간 계산 (14, 29, 44, 59분의 55초)
            minutes_to_next = 14 - (current_time.minute % 15)
            if minutes_to_next == 0:
                minutes_to_next = 15
            next_run_time = current_time.replace(second=55, microsecond=0) + timedelta(minutes=minutes_to_next)
            print(f"Next run time: {next_run_time}")
            # 다음 실행 시간까지 대기
            wait_time = (next_run_time - current_time).total_seconds()
            if wait_time > 0:
                await asyncio.sleep(wait_time)

            print(f"현재 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - 중앙화 주문 취소 시작")
            try:
                await centralized_order_cancellation(exchange_name)
            except Exception as e:
                error_message = str(e)
                print(f"An error occurred during centralized order cancellation3: {error_message}")
                await telegram_message.send_telegram_message(f"중앙화 주문 취소 중 오류 발생: {error_message}", exchange_name, debug=True)
                print(traceback.format_exc())   

            # 짧은 대기 시간 추가 (다음 주기와 겹치지 않도록)
            await asyncio.sleep(1)
        except Exception as e:
            error_message = str(e)
            print(f"An error occurred during centralized order cancellation2: {error_message}")
            #await telegram_message.send_telegram_message(f"중앙화 주문 취소 중 오류 발생: {error_message}", exchange_name, debug=True)
            print(traceback.format_exc())
            await asyncio.sleep(1)

#================================================================================================
# RESET CACHE
#================================================================================================

async def reset_cache():
    current_time_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"Resetting cache at {current_time_str}")
    redis_client = await get_redis_connection()
    patterns = [
        "orders:*:*:*:symbol:*:orders",
        "orders:*:user:*:symbol:*:order_placed",
        "orders:*:user:*:symbol:*:order_placed_index",
        "okx:user:*:symbol:*:order_placed"# 새로 추가된 패턴
    ]
    
    for pattern in patterns:
        cursor = '0'
        while True:
            cursor, keys = await redis_client.scan(cursor=cursor, match=pattern, count=100)
            if keys:
                await redis_client.delete(*keys)
            if cursor == '0':
                break
    print("Cache reset completed")
    

async def schedule_cache_reset():
    while True:
        now = datetime.now()
        next_run = now.replace(minute=(now.minute // 15) * 15, second=59, microsecond=0) + timedelta(minutes=14)
        if next_run <= now:
            next_run += timedelta(minutes=15)
        wait_seconds = (next_run - now).total_seconds()
        print(f"Next cache reset scheduled at {next_run.strftime('%Y-%m-%d %H:%M:%S')}")
        await asyncio.sleep(wait_seconds)
        await reset_cache()


#================================================================================================
# MAIN
#================================================================================================
        
async def run_with_retry(coroutine, name):
    while True:
        try:
            await coroutine()
        except Exception as e:
            logger.error(f"Error in {name}: {e}")
            logger.error(traceback.format_exc())
            logger.info(f"Restarting {name} in 5 seconds...")
            await asyncio.sleep(5)
async def main():
    cleanup_task = asyncio.create_task(periodic_instance_cleanup())
    try:
        tasks = [
            run_with_retry(schedule_cache_reset, "cache reset"),
            run_with_retry(lambda: schedule_order_cancellation('okx'), "OKX order cancellation"),
            run_with_retry(lambda: check_and_update_positions('okx'), "OKX position check"),
            run_with_retry(lambda: order_fetching_loop('okx'), "OKX order fetching"),
            run_with_retry(lambda: check_status_loop('okx'), "OKX status check")
        ]
        await asyncio.gather(*tasks)
    finally:
        cleanup_task.cancel()
        await asyncio.gather(cleanup_task, return_exceptions=True)
        await cleanup_connections()
    
    # Wait for both tasks indefinitely
    #await asyncio.gather(okx_task, upbit_task)



#================================================================================================
# CENTRALIZE POSITIONS
#================================================================================================


def process_okx_position_data(positions_data, symbol):
    for position in positions_data['data']:
        if position['instId'] == symbol:
            quantity = float(position['pos'])
            print(f"{symbol}의 position : {quantity} Quantity type : {type(quantity)}")
            return quantity
    return 0.0

async def get_position_data_from_websocket(websocket, redis, cache_key, symbol, timeout=13.0):
    try:
        while True:
            try:
                response = await asyncio.wait_for(websocket.recv(), timeout=timeout)
                data = json.loads(response)
                
                if 'data' in data and isinstance(data['data'], list):
                    positions_data = data['data']
                    quantity = process_okx_position_data(positions_data, symbol)
                    
                    if quantity != 0.0:
                        # 포지션 데이터를 Redis에 캐시
                        await redis.set(cache_key, json.dumps(positions_data), ex=25)
                        return quantity
                    else:
                        position_data_logger.info(f"No active position for symbol {symbol}")
                else:
                    position_data_logger.warning(f"Unexpected data format received: {data}")
            
            except asyncio.TimeoutError:
                position_data_logger.warning(f"Timeout occurred while waiting for position data for symbol {symbol}")
                return None
            
            except json.JSONDecodeError as e:
                position_data_logger.error(f"JSON decoding error: {e}")
                continue
    
    except Exception as e:
        position_data_logger.error(f"Error in WebSocket connection: {e}")
        return None


async def check_and_update_positions(exchange_name):
    print(f"Starting centralized position update for {exchange_name}")
    try:
        exchange_name = 'okx'
        semaphore = asyncio.Semaphore(10)  # Adjust this value based on your system's capacity

        async def process_user_with_semaphore(user_id, user_data):
            async with semaphore:
                await update_user_positions(redis, user_id, user_data)

        while True:
            try:
                async with manage_redis_connection() as redis:
                    fetched_user_keys = await redis_database.get_user_keys(exchange_name)
                    running_users = {
                        user_id: user_data 
                        for user_id, user_data in fetched_user_keys.items() 
                        if parse_bool(user_data.get("is_running"))
                    }
                    #print(f'Total running users: {len(running_users)}')

                    await asyncio.gather(*[process_user_with_semaphore(user_id, user_data) for user_id, user_data in running_users.items()])

                # Wait for 5 seconds before the next update
                await asyncio.sleep(5)
            except Exception as e:
                print(f"Error in check_and_update_positions: {e}")
                await asyncio.sleep(5)  # Wait for 5 seconds before retrying
    except Exception as e:  
        print(f"Error in check_and_update_positions: {e}")
        print(traceback.format_exc())
        await asyncio.sleep(5)

async def get_and_cache_all_positions(uri: str, API_KEY: str, SECRET_KEY: str, PASSPHRASE: str, redis: Any, user_id: str) -> list[Any] | None:
    cache_key = f'okx:positions:{user_id}'
    async with websockets.connect(uri) as websocket:
        # Perform authentication
        timestamp = str(int(time.time()))
        message = timestamp + 'GET' + '/users/self/verify'
        signature = base64.b64encode(hmac.new(SECRET_KEY.encode('utf-8'), message.encode('utf-8'), hashlib.sha256).digest()).decode('utf-8')
        
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
        #print("Sent login data to WebSocket")
        try:
            login_response = await websocket.recv()
        except Exception as e:
            print(f"Error in WebSocket connection for user {user_id}: {e}")
            
            raise e
            #print(f"Login response: {login_response}")
        
        # Subscribe to position channel
        subscribe_data = {
            "op": "subscribe",
            "args": [{
                "channel": "positions",
                "instType": "SWAP"
            }]
        }
        await websocket.send(json.dumps(subscribe_data))
        #print("Sent subscription request")
        
        #subscription_response = await websocket.recv()
        #print(f"Subscription response: {subscription_response}")
    
        try:

            while True:
                position_data = await asyncio.wait_for(websocket.recv(), timeout=13.0)
                #print(f"Received data: {position_data}")
                
                data = json.loads(position_data)
                if 'data' in data:
                    positions_data = data['data']
                    #total_upl = Decimal('0')
                    ## Cache position data
                    #for position in positions_data:
                    #     upl = Decimal(position.get('upl', '0'))
                    #     total_upl += upl
                    #current_time = int(time.time())
                    await redis.set(cache_key, json.dumps(positions_data), ex=20)  # Cache for 10 seconds
                    #print(f"Updated position data for user {user_id}")
                    return cast(list[Any], positions_data)
        except asyncio.TimeoutError:
            print(f"Timeout occurred while waiting for position data for user {user_id}")
        except Exception as e:
            print(f"Error in WebSocket connection for user {user_id}: {e}")
        
        return None

async def update_user_positions(redis: Any, user_id: str, user_data: dict[str, Any]) -> None:
    uri = "wss://ws.okx.com:8443/ws/v5/private"
    
    # Get user data from Redis
    user_key = f'okx:user:{user_id}'
    API_KEY = cast(str, user_data.get('api_key'))
    SECRET_KEY = cast(str, user_data.get('api_secret'))
    PASSPHRASE = cast(str, user_data.get('password'))

    await get_and_cache_all_positions(uri, API_KEY, SECRET_KEY, PASSPHRASE, redis, user_id)

#================================================================================================
# CENTRALIZE ORDERS
#================================================================================================

async def check_and_cancel_duplicate_order(
    redis: Any,
    exchange_instance: Any,
    exchange_name: str,
    user_id: str,
    symbol: str,
    price: Decimal,
    side: Optional[str] = None,
    tolerance: Decimal = Decimal('0.0003')
) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """
    Check if there's an existing order at the given price and cancel one if found.
    
    :param redis: Redis connection
    :param exchange_instance: Exchange instance for cancelling orders
    :param exchange_name: Name of the exchange
    :param user_id: User ID
    :param symbol: Trading symbol (e.g., 'BTC/USDT')
    :param price: Price to check
    :param side: Optional. 'buy' or 'sell'. If not provided, checks both sides.
    :param tolerance: Price tolerance for matching (default is 0.01%)
    :return: Tuple (bool, dict): (Whether an order was cancelled, Cancelled order details if any)
    """
    redis_key = f"{exchange_name}:user:{user_id}:{symbol}"
    
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
                    # Found a matching order, attempt to cancel it
                    try:
                        cancelled_order = await exchange_instance.cancel_order(order_id, symbol)
                        
                        # Remove the cancelled order from Redis
                        await redis.hdel(redis_key, order_id)
                        
                        print(f"Cancelled {user_id}'s duplicate order: {cancelled_order}")
                        return True, cancelled_order
                    except Exception as cancel_error:
                        print(f"Error cancelling order {order_id}: {cancel_error}")
                        # If cancellation fails, we might want to continue and try the next matching order
                        continue

        # If we've gone through all orders and haven't cancelled any, return False
        return False, None

    except Exception as e:
        print(f"Error checking and cancelling duplicate orders: {e}")
        return False, None


async def fetch_open_orders_length(redis: Any, user_id : int) -> int:
    all_orders_key = f"orders:{user_id}"
    all_orders = await redis.hgetall(all_orders_key)
    return len(all_orders)

async def fetch_and_store_orders(exchange_name: str, user_id: str, exchange_instance: Any, okay_to_log : bool ,redis: Any) -> dict[str, list[dict[str, Any]]]:
    logger = logging.getLogger('order_fetching')
    user_key = f'{exchange_name}:user:{user_id}'


    try:
        all_orders = await exchange_instance.fetch_open_orders()
        if okay_to_log:
            logger.info(f"Total open orders for user {user_id}: {len(all_orders)}")

        # Group orders by symbol
        orders_by_symbol: Dict[str, List[Dict[str, Any]]] = {}
        for order in all_orders:
            if 'info' not in order or 'instId' not in order['info']:
                logger.warning(f"Warning: Order without 'instId' key: {order}")
                continue
            symbol = order['info']['instId']
            if symbol not in orders_by_symbol:
                orders_by_symbol[symbol] = []
            orders_by_symbol[symbol].append(order)

        # Store all orders for the user without symbol distinction
        all_orders_key = f"orders:{user_id}"
        await redis.delete(all_orders_key)  # Clear existing orders

        # Process orders for each symbol
        total_processed = 0
        for symbol, orders in orders_by_symbol.items():
            redis_key = f"{exchange_name}:user:{user_id}:{symbol}"
            await redis.delete(redis_key)  # Clear existing orders

            # Sort orders by price and then by timestamp (oldest first)
            sorted_orders = sorted(orders, key=lambda x: (Decimal(str(x['price'])), x['timestamp']))
            price_set = set()
            orders_to_cancel = []

            for order in sorted_orders:
                price = Decimal(str(order['price']))
                if price in price_set:
                    orders_to_cancel.append(order)
                else:
                    price_set.add(price)
                    await redis.hset(redis_key, order['id'], json.dumps(order))

                # Store order info in the all_orders_key
                order_info = {
                    'symbol': symbol,
                    'price': str(price),
                    'status': order['status'],
                    'side': order['side'],
                    'amount': str(order['amount']),
                    'timestamp': order['timestamp']
                }
                await redis.hset(all_orders_key, order['id'], json.dumps(order_info))

                total_processed += 1


            # Cancel duplicate orders
            for order in orders_to_cancel:
                try:
                    cancelled_order = await exchange_instance.cancel_order(order['id'], symbol)
                    logger.info(f"Cancelled duplicate order: {symbol}, price : {order['price']}")
                except Exception as cancel_error:
                    logger.error(f"Error cancelling order {order['id']}: {cancel_error}")


        #logger.info(f"Completed processing all {total_processed} orders for user {user_id}")
        return orders_by_symbol

    except Exception as e:
        logger.error(f"Error fetching and storing orders for user {user_id}: {e}")
        return {}

# Modified order fetching loop with controlled concurrency
async def order_fetching_loop(exchange_name: str, max_concurrent: int = 10) -> None:
    logger = logging.getLogger('order_fetching')
    semaphore = asyncio.Semaphore(max_concurrent)

    async def process_user(user_id: str, user_data: Dict[str, Any], okay_to_log: bool) -> None:
        async with semaphore:
            async with manage_redis_connection() as redis, manage_exchange_instance(exchange_name, user_id) as exchange_instance:
                await fetch_and_store_orders(exchange_name, user_id, exchange_instance, okay_to_log, redis=redis)

    while True:
        try:
            async with manage_redis_connection() as redis:
                fetched_user_keys = await redis_database.get_user_keys(exchange_name)
                running_users = {
                    user_id: user_data 
                    for user_id, user_data in fetched_user_keys.items() 
                    if parse_bool(user_data.get("is_running"))
                }
                okay_to_log = await should_log(redis)
                if okay_to_log:
                    logger.info(f'Total running users: {len(running_users)}')
                
                tasks = [process_user(user_id, user_data, okay_to_log) for user_id, user_data in running_users.items()]
                await asyncio.gather(*tasks)

            # Cleanup inactive instances
            await cleanup_inactive_instances()
        except Exception as e:
            logger.error(f"Error in order fetching loop: {e}")
        
        await asyncio.sleep(7)  # Wait for 7 seconds before the next fetch

# Add this to your main function or scheduler
async def periodic_instance_cleanup():
    while True:
        try:
            await cleanup_inactive_instances()
            await asyncio.sleep(3600)  # Run cleanup every hour
        except asyncio.CancelledError:
            logger.info("Periodic cleanup task was cancelled.")
            break
        except Exception as e:
            logger.error(f"Error in periodic cleanup: {e}", exc_info=True)
            await asyncio.sleep(60)  # Wait a bit before retrying

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logger.error(f"Error in main: {e}")
        logger.error(traceback.format_exc())
        logger.info("Restarting main in 5 seconds...")
        time.sleep(5)