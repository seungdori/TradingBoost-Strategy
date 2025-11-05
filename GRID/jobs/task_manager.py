"""GRID Trading Bot - Task Management Module

태스크 생성, 관리 및 오케스트레이션 기능:
- run_task: 트레이딩 태스크 실행
- create_tasks: 메인 태스크 생성
- cancel_tasks: 태스크 취소
- task_completed: 태스크 완료 처리
- handle_task_completion: 태스크 완료 핸들러
- monitor_and_handle_tasks: 태스크 모니터링 및 처리 (from position_monitor)
- create_symbol_task: 심볼 태스크 생성
- create_new_task: 새 태스크 생성
- create_monitoring_tasks: 모니터링 태스크
- create_recovery_tasks: 복구 태스크
- create_individual_task: 개별 태스크
- create_stop_loss_task: 스탑로스 태스크
- create_custom_stop_task: 커스텀 스탑 태스크
- initialize_and_load_user_data: 사용자 데이터 로드
- handle_skipped_symbols: 스킵된 심볼 처리
- process_new_symbols: 새 심볼 처리
- summarize_trading_results: 트레이딩 결과 요약
"""

# ==================== 표준 라이브러리 ====================
from shared.database.redis_patterns import redis_context, RedisTTL
import asyncio
import glob
import json
import logging
import os
import random
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# ==================== 외부 라이브러리 ====================
import pandas as pd
import redis.asyncio as aioredis

from GRID import telegram_message
from GRID.core.exceptions import QuitException

# ==================== Core 모듈 ====================
from GRID.core.websocket import ws_client

# ==================== 프로젝트 모듈 ====================
from GRID.database import redis_database
from GRID.main import periodic_analysis

# Monitoring - 포지션 및 커스텀 스탑 모니터링
from GRID.monitoring.position_monitor import monitor_custom_stop, monitor_positions
from GRID.routes.logs_route import add_log_endpoint as add_user_log

# ==================== Services ====================
from GRID.services.symbol_service import get_top_symbols
from GRID.services.user_management_service import (
    get_user_data,
    get_user_data_from_redis,
    initialize_user_data,
    update_user_data,
)
from GRID.strategies import strategy

# ==================== 모듈 내부 import (순환 참조 방지) ====================
# Grid Core - 그리드 레벨 계산 및 주문 배치
from GRID.trading.grid_core import calculate_grid_levels, place_grid_orders
from GRID.trading.instance_manager import get_exchange_instance
from GRID.trading.shared_state import user_keys

# ==================== Utils ====================
from shared.utils import parse_bool, path_helper, retry_async

logger = logging.getLogger(__name__)


# ==============================================================================
#                          Task Management Functions
# ==============================================================================

async def run_task(symbol, queue, initial_investment, direction, grid_levels, grid_num, exchange_name, leverage, timeframe, stop_loss, numbers_to_entry, user_id, exchange_instance, force_restart = False):
    async with redis_context() as redis:
        print(f"Running task for {symbol}")
        try:
            user_key = f'{exchange_name}:user:{user_id}'
            if not await redis.exists(user_key):
                await redis.hset(user_key, mapping = {
                    'is_running': '1',
                    'tasks': '[]',
                    'running_symbols': '[]',
                    'completed_trading_symbols': '[]'
                })

            # Get user data from Redis
            user_data = await redis.hgetall(user_key)
            user_data = {k.decode() if isinstance(k, bytes) else k: v.decode() if isinstance(v, bytes) else v for k, v in user_data.items()}
            running_symbols = set(json.loads(user_data.get('running_symbols', '[]')))
            tasks = json.loads(user_data.get('tasks', '[]'))
            is_running = user_data.get('is_running') == '1'
        
        
        
            if is_running and len(running_symbols) <= numbers_to_entry:
                if exchange_name in ['binance', 'bitget', 'okx'] and int(leverage) > 1:
                    try:
                        await asyncio.sleep(random.uniform(0.8, 2.0))
                        await retry_async(strategy.change_leverage, exchange_name, symbol, leverage, user_id)
                    except Exception as e:
                        print(f"Error changing leverage for {symbol}: {e}")
                        print(traceback.format_exc())
                        return symbol
                try:
                    user_key = f'{exchange_name}:user:{user_id}'
                
                    await asyncio.sleep(random.uniform(1, 1.7))
                
                    #기존 로직 0726 0208
                    ws_task = asyncio.create_task(ws_client(exchange_name, symbol, queue, user_id))
                    order_task = asyncio.create_task(place_grid_orders(symbol, initial_investment, direction, grid_levels, queue, grid_num, leverage, exchange_name, user_id, force_restart))
                    print('💫Task created for ', symbol)
                    tasks = json.loads(await redis.hget(user_key, 'tasks') or '[]')
                    tasks.extend([str(ws_task.get_name()), str(order_task.get_name())])
                    await redis.hset(user_key, 'tasks', json.dumps(tasks))
                    results = await asyncio.gather(ws_task, order_task, return_exceptions=True)
                
                    #ws_task = asyncio.create_task(ws_client(exchange_name, symbol, queue, user_id))
                    #order_task = asyncio.create_task(place_grid_orders(symbol, initial_investment, direction, grid_levels, queue, grid_num, leverage, exchange_name, user_id, force_restart))
                    #tasks = json.loads(await redis.hget(user_key, 'tasks') or '[]')
                    #tasks.extend(str(order_task.get_name()))
                    #await redis.hset(user_key, 'tasks', json.dumps(tasks))
                    #results = await asyncio.gather(order_task, return_exceptions=True)    
            
                except Exception as e:
                    print(f"Error running tasks for symbol {symbol}: {e}")
                    if 'remove' in str(e):
                        print(f"Removing {symbol} from running symbols")
                        return str(e)
                    print(traceback.format_exc())
                # Check if user is still running
                is_running = await redis.hget(user_key, 'is_running')
                if is_running is True:
                    for result in results:
                        if isinstance(result, QuitException):
                            print("종료? ")
                            await cancel_tasks(user_id, exchange_name)
                            print(f"Task for {symbol} completed. Finding new task...")
                            return symbol
                        else: 
                            print(f"Task for {symbol} failed. Finding new task...")
                            new_task = await task_completed(task=order_task, new_symbol=symbol, symbol_queue=queue, exchange_name=exchange_name, user_id=user_id) # type: ignore[call-arg]
                            return new_task
                    #await task_completed(task=order_task, new_symbol=symbol, symbol_queue=queue, exchange_name=exchange_name, user_id=user_id)
                    if any(isinstance(result, Exception) for result in results):
                        print(f"Task for {symbol} failed. Finding new task...")
                        return None
                    else:
                        print(f"Task for {symbol} completed. Finding new task...")
                        return symbol
                else:
                    return None
            return
    
        except Exception as e:
            print(f"{user_id} : Error running tasks for symbol {symbol}: {e}")
        
            print(traceback.format_exc())
            return None


async def task_completed(task: Any, new_symbol: str, exchange_name: str, user_id: str) -> Any:
    print(f'매개변수 확인. task: {task}, new_symbol: {new_symbol}, exchange_name: {exchange_name}, user_id: {user_id}')
    async with redis_context() as redis:
        try:
            user_key = f'{exchange_name}:user:{user_id}'
            user_data = await redis.hgetall(user_key)

            grid_num = int(user_data.get("grid_num", 20))
            leverage = float(user_data.get("leverage", 1))
            direction = user_data.get("direction", "long")
            initial_capital_json = user_data.get("initial_capital", "[]")
            initial_capital_list = json.loads(initial_capital_json) if isinstance(initial_capital_json, str) else initial_capital_json
            stop_loss = float(user_data.get("stop_loss", 0))
            numbers_to_entry = int(user_data.get("numbers_to_entry", 10))
            running_symbols = set(json.loads(user_data.get('running_symbols', '[]')))
            completed_symbols = set(json.loads(user_data.get('completed_trading_symbols', '[]')))
            tasks = json.loads(user_data.get('tasks', '[]'))

            running_symbols.discard(new_symbol)
            completed_symbols.add(new_symbol)
            if task in tasks:
                tasks.remove(task)
            await redis.hset(user_key, 'running_symbols', json.dumps(list(running_symbols)))
            await redis.hset(user_key, 'completed_trading_symbols', json.dumps(list(completed_symbols)))
            await redis.hset(user_key, 'tasks', json.dumps(tasks))

            print(f"user_id = {user_id}, exchange_name = {exchange_name}, direction = {direction}")

            new_entry_symbols = await get_new_symbols(user_id=user_id, exchange_name=exchange_name, direction=direction, limit=20)
            if new_entry_symbols is None:
                print('종료')
                return

            limit = int(user_data.get("numbers_to_entry", 1))
        
            filtered_symbols = [symbol for symbol in new_entry_symbols if symbol not in completed_symbols]

            print(f"new_entry_symbols 타입: {type(new_entry_symbols)}")
            print(f"new_entry_symbols 내용: {new_entry_symbols}")
            print(f"filtered_symbols 타입: {type(filtered_symbols)}")
            print(filtered_symbols)
            print('새로운 심볼 탐색 ! 확인! ')
            print(f"limit : {limit}")

            is_running = parse_bool(user_data.get('is_running', '0'))
        
            if is_running:
                print(f"running_symbols : {running_symbols}, len : {len(running_symbols)}")
                if len(running_symbols) <= numbers_to_entry:
                    for symbol in filtered_symbols[:limit]:
                        print(f"filtered_symbols[:limit] : {filtered_symbols[:limit]}")
                        print(f"symbol {symbol}")
                        symbol_queues = {symbol: asyncio.Queue(maxsize=1)} # type: ignore[var-annotated]
                        message = f"🚀 {user_id} 새로운 심볼{new_entry_symbols}에 대한 매매를 시작합니다."
                        await (create_new_task(new_symbol=symbol, symbol_queues=symbol_queues, 
                                                                  initial_investment=initial_capital_list, direction=direction, 
                                                                  timeframe='15m', grid_num=grid_num, exchange_name=exchange_name,
                                                                  leverage=leverage, user_id=user_id, stop_loss=stop_loss, numbers_to_entry = numbers_to_entry, force_restart=False))
                    await telegram_message.send_telegram_message(message, exchange_name, user_id)
                    await add_user_log(user_id, message)
                else:
                    message = f"{numbers_to_entry}보다 많은 포지션을 보유 중입니다. 새로운 포지션 진입을 종료합니다."
                    await telegram_message.send_telegram_message(message, exchange_name, user_id)                
            else:
                print("{user_id} : 테스크가 종료 되었습니다.")
                message = f"🚀 {user_id} 매매가 종료되었습니다.\n모든 트레이딩이 종료되었습니다."
                await telegram_message.send_telegram_message(message, exchange_name, user_id)
                await add_user_log(user_id, message)
                return
        except Exception as e:
            print(f"An error occurred on task_completed: {e}")
            print(traceback.format_exc())
async def cancel_tasks(user_id, exchange_name, close_positions = False):
    print('========================[GRID MAIN CANCEL REQUEST]========================')
    async with redis_context() as redis:
        try:
            user_key = f'{exchange_name}:user:{user_id}'
        
            # Get user data from Redis
            user_data = await redis.hgetall(user_key)
            if not user_data:
                print(f"User ID {user_id} not found in Redis")
                return
            user_running_state = parse_bool(user_data.get('is_running', '0'))
            print(f"User {user_id} is running: {user_running_state}")

            if not user_running_state:
                print("프로세스가 이미 종료되었습니다.")
                await redis.hset(user_key, 'is_running', '0')
                print(f"Set is_running to 0. New state: {await redis.hget(user_key, 'is_running')}")
                return

            running_symbols = json.loads(user_data.get('running_symbols', '[]'))
            symbols_to_remove = set()

            for symbol_name in running_symbols:
                await strategy.cancel_all_limit_orders(exchange_name, symbol_name, user_id)
                symbols_to_remove.add(symbol_name)

            updated_running_symbols = list(set(running_symbols) - symbols_to_remove)
            await redis.hset(user_key, 'running_symbols', json.dumps(updated_running_symbols))
            await redis.hset(user_key, 'is_running', '0')
            await redis.hset(user_key, 'is_stopped', '1')

            # Cancel all tasks
            tasks = json.loads(user_data.get('tasks', '[]'))
            for task_name in tasks:
                for task in asyncio.all_tasks():
                    if task.get_name() == task_name and not task.done():
                        task.cancel()
        
            print("모든 트레이딩 태스크가 취소되었습니다.")

            # Wait for all cancelled tasks to finish
            cancelled_tasks = [task for task in asyncio.all_tasks() if task.cancelled()]
            await asyncio.gather(*cancelled_tasks, return_exceptions=True)
            print("모든 태스크가 취소되었습니다.")

            # Clear the tasks list in Redis
            await redis.hset(user_key, 'tasks', '[]')
            await redis.hset(user_key, 'completed_trading_symbols', '[]')

            # Update user info in Redis

            #print(f"Updated user data: {await redis.hgetall(user_key)}")

        except Exception as e:
            print(f"{user_id} : An error occurred in cancel_tasks: {e}")
            print(traceback.format_exc())
            raise e
        finally:
            await redis.hset(user_key, 'is_running', '0')
            #await redis.aclose()



    # =======[GET SYMBOL 심볼 분석 끝]=======







def summarize_trading_results(exchange_name, direction):
    
    # 경로 패턴을 사용하여 해당 거래소 폴더 내의 모든 CSV 파일을 찾습니다.
    exchange_name = str(exchange_name)
    print(f"{exchange_name}의 거래 전략 요약을 시작합니다.")
    pattern = str(path_helper.grid_dir / exchange_name / direction / "trading_strategy_results_*.csv")
    print(f"패턴: {pattern}")
    files = glob.glob(pattern)
    
    results = []
    for file_path in files: 
        df = pd.read_csv(file_path)
        if not df.empty and 'total_profit' in df.columns:
            last_total_profit = df['total_profit'].iloc[-1]
            # total_profit이 2,000 이상인 경우에만 100으로 나누어 저장합니다.
            if last_total_profit >= 2000:
                last_total_profit /= 100
            elif last_total_profit <= -2000:
                last_total_profit /= 100
            elif last_total_profit >= 900:
                last_total_profit /= 10
            elif last_total_profit <= -100:
                last_total_profit /= 100
            
            # 파일명에서 심볼 이름을 추출합니다.
            symbol = os.path.basename(file_path).replace('trading_strategy_results_', '').replace('.csv', '')
            results.append({'symbol': symbol, 'total_profit': last_total_profit})


    # 결과를 하나의 데이터프레임으로 합치고 CSV 파일로 저장합니다.
    try:
        print(f"path_helper.grid_dir : {path_helper.grid_dir}")
        summary_df = pd.DataFrame(results).infer_objects()  # infer_objects() 메서드 추가
        summary_file_path = path_helper.grid_dir / exchange_name / direction / f"{exchange_name}_summary_trading_results.csv"
        summary_df.to_csv(summary_file_path, index=False)
        print(f"{exchange_name}의 거래 전략 요약이 완료되었습니다. 파일 경로: {summary_file_path}")
    except Exception as e:
        print(f"An error occurred24: {e}")
        print(traceback.format_exc())




# ==============================================================================
# Main 메인
# ==============================================================================
#
#async def trading_loop(exchange_name, user_id, initial_investment, direction, timeframe, grid_num, leverage, stop_loss, custom_stop, numbers_to_entry):
#    trading_semaphore = asyncio.Semaphore(numbers_to_entry)  # Limit concurrent operations
#    symbol_queues = {}
#    tasks = []
#    completed_symbols = set()
#    running_symbols = set()
#
#    while True:
#        is_running = await get_user_data(exchange_name, user_id, "is_running")
#        if not is_running:
#            break
#
#        async with trading_semaphore:
#            try:
#                # Get new symbols
#                potential_symbols = await get_top_symbols(user_id, exchange_name, direction, limit=10)
#                new_symbols = [s for s in potential_symbols if s not in completed_symbols and s not in running_symbols]
#
#                if new_symbols:
#                    created_tasks = await create_tasks(new_symbols, symbol_queues, initial_investment, direction, timeframe, grid_num, exchange_name, leverage, user_id, stop_loss, numbers_to_entry, custom_stop)
#                    if created_tasks:
#                        tasks.extend(created_tasks)
#                        running_symbols.update(new_symbols)
#                        print(f"Created and managed {len(created_tasks)} new tasks.")
#                    else:
#                        print("No new tasks were created.")
#                else:
#                    print("No suitable new symbols found.")
#
#            except Exception as e:
#                print(f"An error occurred during task creation: {e}")
#                print(traceback.format_exc())
#
#            # Process completed tasks
#            done_tasks = [task for task in tasks if task.done()]
#            for task in done_tasks:
#                try:
#                    result = await task
#                    if result:
#                        completed_symbols.add(result)
#                        running_symbols.remove(result)
#                        print(f"Completed symbol: {result}")
#                except Exception as task_e:
#                    print(f"Error processing completed task: {task_e}")
#                tasks.remove(task)
#
#            # Replace completed or failed tasks
#            if len(running_symbols) < 5:  # Maintain at least 5 running tasks
#                replacement_needed = 5 - len(running_symbols)
#                potential_replacement_symbols = await get_top_symbols(user_id, exchange_name, direction, limit=replacement_needed + 5)
#                replacement_symbols = [s for s in potential_replacement_symbols if s not in completed_symbols and s not in running_symbols][:replacement_needed]
#                
#                if replacement_symbols:
#                    print(f"Attempting to add replacement symbols: {replacement_symbols}")
#                    replacement_tasks = await create_tasks(replacement_symbols, symbol_queues, initial_investment, direction, timeframe, grid_num, exchange_name, leverage, user_id, stop_loss,numbers_to_entry, custom_stop)
#                    if replacement_tasks:
#                        tasks.extend(replacement_tasks)
#                        running_symbols.update(replacement_symbols)
#                        print(f"Successfully added {len(replacement_tasks)} replacement tasks.")
#                    else:
#                        print("No replacement tasks were created.")
#                else:
#                    print("No suitable replacement symbols found.")
#
#        await asyncio.sleep(60)  # Wait for 1 minute before the next iteration
#
#    # Clean up when the loop ends
#    for task in tasks:
#        task.cancel()
#    await asyncio.gather(*tasks, return_exceptions=True)


#================================================================================================
# TASKS
#================================================================================================


async def create_symbol_task(new_symbol, symbol_queues, initial_investment, direction, grid_num, exchange_name, leverage, timeframe, stop_loss, numbers_to_entry, user_id, exchange_instance, force_restart):
    grid_levels = await periodic_analysis.calculate_grid_logic(direction = direction,grid_num = grid_num, exchange_name=exchange_name, symbol=new_symbol, user_id=user_id, exchange_instance=exchange_instance)
    try:
        if grid_levels is None:
            return None

        queue = symbol_queues.get(new_symbol) or asyncio.Queue(maxsize=1)
        symbol_queues[new_symbol] = queue
        print(f"🤖Creating task for symbol {new_symbol}")
        task = asyncio.create_task(run_task(new_symbol, queue, initial_investment, direction, grid_levels, grid_num, exchange_name, leverage, timeframe, stop_loss, numbers_to_entry, user_id, exchange_instance, force_restart))
        #원본이, 의의 asyncio.create_task.그런데 이렇게하면 끝날 때까지 기다리지 않기 때문에, await로 아래처럼 수정해봄. 0928
        #task = await (run_task(new_symbol, queue, initial_investment, direction, grid_levels, grid_num, exchange_name, leverage, timeframe, stop_loss, numbers_to_entry, user_id, exchange_instance, force_restart))
        task_name = f"task_{new_symbol}_{user_id}"
        task.set_name(task_name)
    except Exception as e:
        print(f"An error occurred in create_symbol_task: {e}")
        print(traceback.format_exc())
        return None, new_symbol
    
    return task, task_name



async def create_monitoring_tasks(exchange_name, user_id, stop_loss, custom_stop):
    tasks = []
    if stop_loss is not None and stop_loss > 0 and exchange_name != 'upbit':
        monitor_sl_task = asyncio.create_task(monitor_positions(exchange_name, user_id))
        monitor_sl_task_name = f"monitor_sl_{user_id}"
        monitor_sl_task.set_name(monitor_sl_task_name)
        tasks.append((monitor_sl_task, monitor_sl_task_name))

    if custom_stop is not None:
        monitor_custom_stop_task = asyncio.create_task(monitor_custom_stop(exchange_name, user_id, custom_stop))
        monitor_custom_stop_task_name = f"monitor_custom_stop_{user_id}"
        monitor_custom_stop_task.set_name(monitor_custom_stop_task_name)
        tasks.append((monitor_custom_stop_task, monitor_custom_stop_task_name))

    return tasks



async def create_recovery_tasks(user_id, exchange_name, direction, symbol_queues, initial_investment, timeframe, grid_num, leverage, stop_loss, numbers_to_entry, custom_stop):
    try:
        is_running = await get_user_data(exchange_name, user_id, "is_running")
        if not is_running:
            print(f"Trading process is not running for user {user_id}. Skipping recovery.")
            return []

        potential_recovery_symbols = await get_top_symbols(user_id, exchange_name, direction, limit=40)
        running_symbols = set(await get_user_data(exchange_name, user_id, 'running_symbols'))
        completed_symbols = set(await get_user_data(exchange_name, user_id, 'completed_trading_symbols'))
        
        exchange_instance = await get_exchange_instance(exchange_name, user_id)
        
        new_symbols = [s for s in potential_recovery_symbols if s not in completed_symbols and s not in running_symbols]
        
        if not new_symbols:
            print(f"No new symbols available for recovery for user {user_id}.")
            return []

        print(f"Attempting recovery with symbols: {new_symbols[:1]}")
        
        try:
            recovery_tasks = await create_tasks(
                new_symbols[:1], symbol_queues, initial_investment, direction, timeframe, 
                grid_num, exchange_name, leverage, user_id, stop_loss, numbers_to_entry, 
                custom_stop=custom_stop, exchange_instance=exchange_instance
            )
            
            if recovery_tasks:
                print(f"Successfully created {len(recovery_tasks)} recovery tasks for user {user_id}.")
                await telegram_message.send_telegram_message(
                    f"{user_id}: 새로운 심볼 {new_symbols[:1]}로 재진입", 
                    exchange_name, user_id
                )
                return recovery_tasks
            else:
                print(f"No recovery tasks were created for user {user_id}.")
                return []
        
        except Exception as e:
            print(f"Error creating recovery tasks for user {user_id}: {e}")
            print(traceback.format_exc())
            return []

    except Exception as e:
        print(f"An error occurred in create_recovery_tasks for user {user_id}: {e}")
        print(traceback.format_exc())
        return []



async def initialize_and_load_user_data(redis, user_key):
    await initialize_user_data(redis, user_key)
    user_data = await get_user_data_from_redis(redis, user_key)
    
    running_symbols = set(json.loads(user_data.get('running_symbols', '[]')))
    completed_symbols = set(json.loads(user_data.get('completed_trading_symbols', '[]')))
    existing_tasks = json.loads(user_data.get('tasks', '[]'))
    
    return running_symbols, completed_symbols, existing_tasks




async def create_individual_task(
    new_symbol, symbol_queues, initial_investment, direction, grid_num, 
    exchange_name, leverage, timeframe, stop_loss, numbers_to_entry, 
    user_id, exchange_instance, force_restart, redis, user_key
):
    #print(f'{user_id} : ❗️❗️create_individual_task, new_symbol: {new_symbol}')
    try:
        await asyncio.sleep(random.random())
        # Check if symbol is already completed or running
        user_data = await get_user_data_from_redis(redis, user_key)
        completed_symbols = set(json.loads(user_data.get('completed_trading_symbols', '[]')))
        running_symbols = set(json.loads(user_data.get('running_symbols', '[]')))
        if new_symbol in completed_symbols or new_symbol in running_symbols:
            print(f"Symbol {new_symbol} is already completed or running. Skipping.")
            
            return None, new_symbol
        
        
        # Add to running symbols
        running_symbols.add(new_symbol)
        await redis.hset(user_key, 'running_symbols', json.dumps(list(running_symbols)))
        
        # Create the trading task
        ####1008 : 여기를, await가 아니라, asyncio.create_task로 변경해봄.
        task = asyncio.create_task(create_symbol_task(
            new_symbol, symbol_queues, initial_investment, direction, grid_num, 
            exchange_name, leverage, timeframe, stop_loss, numbers_to_entry, 
            user_id, exchange_instance, force_restart
        ))
        if task:
            print(f"Starting trading for {new_symbol}")
            return task
        else:
            # If task creation failed, update symbols accordingly
            running_symbols.remove(new_symbol)
            completed_symbols.add(new_symbol)
            await redis.hset(user_key, 'running_symbols', json.dumps(list(running_symbols)))
            await redis.hset(user_key, 'completed_trading_symbols', json.dumps(list(completed_symbols)))
            return None, new_symbol
    except Exception as e:
        print(f"{user_id} : Error creating task for {new_symbol}: {e}")
        print(traceback.format_exc())
        return None
    
    


async def handle_skipped_symbols(
    skipped_symbols, new_symbols, symbol_queues, initial_investment, direction, timeframe, 
    grid_num, exchange_name, leverage, user_id, stop_loss, numbers_to_entry, 
    exchange_instance, custom_stop, recursion_depth, force_restart, 
    created_tasks
):
    print(f'{user_id} : ❗️❗️handle_skipped_symbols')
    if skipped_symbols and recursion_depth < 3:
        additional_symbols_needed = len(new_symbols) + len(skipped_symbols) + 5
        potential_symbols = await get_top_symbols(
            user_id=user_id, 
            exchange_name=exchange_name, 
            direction=direction, 
            limit=additional_symbols_needed
        )
        existing_symbols = set(new_symbols) | set(skipped_symbols)
        new_additional_symbols = [symbol for symbol in potential_symbols if symbol not in existing_symbols]
        print(f"🚨🚨skipped_symbols: {skipped_symbols}에 대해 새로운 시도. 추가 심볼: {new_additional_symbols}")
        if new_additional_symbols:
            print(f"Adding {len(new_additional_symbols)} new symbols to replace skipped ones.")
            additional_tasks = await create_tasks(
                new_symbols=new_additional_symbols,
                symbol_queues=symbol_queues,
                initial_investment=initial_investment,
                direction=direction,
                timeframe=timeframe,
                grid_num=grid_num,
                exchange_name=exchange_name,
                leverage=leverage,
                user_id=user_id,
                stop_loss=stop_loss,
                numbers_to_entry=numbers_to_entry,
                exchange_instance=exchange_instance,
                custom_stop=custom_stop,
                recursion_depth=recursion_depth + 1,
                force_restart=force_restart
            )
            created_tasks.extend(additional_tasks)
            return additional_tasks
            
            


async def process_new_symbols(
    new_symbols, symbol_queues, initial_investment, direction, timeframe, 
    grid_num, exchange_name, leverage, user_id, stop_loss, numbers_to_entry, 
    exchange_instance, custom_stop, recursion_depth, force_restart, 
    redis, user_key
):
    created_tasks = []
    tasks = []
    testing_tasks = []
    skipped_symbols = []
    try:
        for new_symbol in new_symbols:
            task = asyncio.create_task(create_individual_task(
                new_symbol, symbol_queues, initial_investment, direction, grid_num, 
                exchange_name, leverage, timeframe, stop_loss, numbers_to_entry, 
                user_id, exchange_instance, force_restart, redis, user_key
            ), name=f"task_{new_symbol}_{user_id}")
            task_name = new_symbol
            if task :
                created_tasks.append(task)
                tasks.append(task_name)
                print(f"새로 task {task_name} 추가 for symbol {new_symbol}")
                testing_tasks.append(task)
                
        
        await redis.hset(user_key, 'tasks', json.dumps(tasks))
        await redis.hset(user_key, 'tasks_symbol', json.dumps(tasks)) #<--- symbol name이 저장되지 않고 테스크 객체가 저장되어서. 
        #print("Tasks to store:", testing_tasks)
        task_names = [task.get_name() for task in testing_tasks]
        await redis.hset(user_key, 'tasks_testing', json.dumps(task_names))
    except Exception as e:
        print(f"{user_id} : Error creating tasks: {e}")
        print(traceback.format_exc())
        
    # Handle skipped symbols and potentially create additional tasks
    # Note: The original code added skipped symbols to a list but didn't use them directly.
    # This part can be adjusted based on specific requirements.
    # For now, we'll assume skipped_symbols are the ones that failed during task creation
    try:
        skipped_symbols = [symbol for symbol in new_symbols if symbol not in tasks]
        await handle_skipped_symbols(
            skipped_symbols, new_symbols, symbol_queues, initial_investment, direction, timeframe, 
            grid_num, exchange_name, leverage, user_id, stop_loss, numbers_to_entry, 
            exchange_instance, custom_stop, recursion_depth, force_restart, 
            created_tasks
        )
    except Exception as e:
        print(f"{user_id} : Error handling skipped symbols: {e}")
        traceback.print_exc()
        
    
    return created_tasks




async def create_tasks(
    new_symbols, symbol_queues, initial_investment, direction, timeframe, grid_num, 
    exchange_name, leverage, user_id, stop_loss, numbers_to_entry, 
    exchange_instance, custom_stop=False, recursion_depth=0, force_restart=False
):
    async with redis_context() as redis:
        user_key = f'{exchange_name}:user:{user_id}'
    
        try:
            # 사용자 데이터 초기화 및 로드
            running_symbols, completed_symbols, existing_tasks = await initialize_and_load_user_data(redis, user_key)
        
            if len(running_symbols) > numbers_to_entry:
                print(f"Running symbols count {len(running_symbols)} is greater than or equal to numbers_to_entry {numbers_to_entry}. Skipping.")
                return []
        
            # 새 심볼에 대한 태스크 생성
            created_tasks = await process_new_symbols(
                new_symbols, symbol_queues, initial_investment, direction, timeframe, 
                grid_num, exchange_name, leverage, user_id, stop_loss, numbers_to_entry, 
                exchange_instance, custom_stop, recursion_depth, force_restart, 
                redis, user_key
            )
            #print(f"created tasks: {created_tasks}, sy")
            # 모니터링 태스크 생성
            monitoring_tasks = await create_monitoring_tasks(exchange_name, user_id, stop_loss, custom_stop)
            for task, task_name in monitoring_tasks:
                created_tasks.append(task)
        
            await redis.hset(user_key, 'tasks', json.dumps([task.get_name() for task in created_tasks]))
        
            # 태스크 완료 처리
            await monitor_and_handle_tasks( # type: ignore[name-defined]
                created_tasks, exchange_name, user_id, symbol_queues, initial_investment, 
                direction, timeframe, grid_num, leverage, stop_loss, numbers_to_entry, 
                exchange_instance, custom_stop, user_key, redis
            )
        
            return created_tasks
        except Exception as e:
            print(f"{user_id} : An error occurred in create_tasks: {e}")
            print(traceback.format_exc())
            return []





async def handle_task_completion(task: asyncio.Task, new_symbol: str, exchange_name: str, user_id: str, redis: aioredis.Redis) -> None:
    user_key = f'{exchange_name}:user:{user_id}'
    try:
        async with redis.pipeline(transaction=True) as pipe:
            # Fetch and update running symbols
            pipe.hget(user_key, 'running_symbols')
            pipe.hget(user_key, 'completed_trading_symbols')
            results = await pipe.execute()

            running_symbols = json.loads(results[0]) if results[0] else []
            completed_symbols = json.loads(results[1]) if results[1] else []

            if new_symbol in running_symbols:
                running_symbols.remove(new_symbol)

            completed_symbols.append(new_symbol)

            # Update both lists in Redis
            pipe.hset(user_key, 'running_symbols', json.dumps(running_symbols))
            pipe.hset(user_key, 'completed_trading_symbols', json.dumps(completed_symbols))
            await pipe.execute()

        logging.info(f"Task for {new_symbol} completed. Running symbols: {running_symbols}")
    except json.JSONDecodeError as e:
        logging.error(f"JSON decoding error: {e}")
    except aioredis.RedisError as e:
        logging.error(f"Redis error: {e}")
    except Exception as e:
        logging.exception(f"Unexpected error handling task completion: {e}")



async def monitor_and_handle_tasks(
    created_tasks, exchange_name, user_id, symbol_queues, initial_investment,
    direction, timeframe, grid_num, leverage, stop_loss, numbers_to_entry,
    exchange_instance, custom_stop, user_key, redis
):
    """
    Task monitoring and completion handling.
    Moved from position_monitor to break circular dependency.
    """
    while created_tasks:
        done, pending = await asyncio.wait(created_tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task_name = task.get_name()
            if task_name in created_tasks:
                is_running = await get_user_data(exchange_name, user_id, "is_running")
                if not is_running:
                    print('프로세스가 종료되었습니다.')
                    return created_tasks

                # Remove completed task
                created_tasks.remove(task)
                await redis.hset(user_key, 'tasks', json.dumps([t.get_name() for t in created_tasks]))

                # Handle task completion
                await handle_task_completion(task, task_name, exchange_name, user_id, redis)

                # Check if still running
                is_running = await get_user_data(exchange_name, user_id, "is_running")
                if not is_running:
                    print('프로세스가 종료되었습니다.')
                    return created_tasks

                # Potentially create recovery tasks if necessary
                if len(created_tasks) <= numbers_to_entry and is_running:
                    try:
                        recovery_tasks = await create_recovery_tasks(
                            user_id, exchange_name, direction, symbol_queues, initial_investment,
                            timeframe, grid_num, leverage, stop_loss, numbers_to_entry, custom_stop
                        )
                        if recovery_tasks:
                            created_tasks.extend(recovery_tasks)
                            await redis.hset(user_key, 'tasks', json.dumps([t.get_name() for t in created_tasks]))
                    except Exception as e:
                        print(f"{user_id} : Error during recovery: {e}")
                        print(traceback.format_exc())
    return created_tasks




async def create_new_task(new_symbol, symbol_queues, initial_investment, direction, timeframe, grid_num, exchange_name, leverage, user_id, stop_loss, numbers_to_entry, custom_stop=False, force_restart=False):
    user_key = f'{exchange_name}:user:{user_id}'
    try:
        # 사용자 데이터 가져오기
        user_data = await get_user_data(exchange_name, user_id)
        tasks = user_data.get('tasks', [])
        running_symbols = set(user_data.get('running_symbols', []))
        is_running = parse_bool(user_data.get('is_running', '0'))

        if not is_running:
            print(f"Trading process is not running for user {user_id}. Skipping new task creation.")
            return

        if len(running_symbols) > numbers_to_entry:
            print(f"Maximum number of running symbols reached for user {user_id}. Skipping new task creation.")
            return

        # Exchange 인스턴스 가져오기
        exchange_instance = await get_exchange_instance(exchange_name, user_id)

        # 새 심볼 추가 및 그리드 레벨 계산
        running_symbols.add(new_symbol)
        await redis_database.add_running_symbol(user_id, new_symbol, exchange_name)
        print(f"Adding new task for symbol: {new_symbol}")

        grid_levels = await calculate_grid_levels(direction, grid_num, new_symbol, exchange_name, user_id, exchange_instance)

        # 메인 태스크 생성
        queue = symbol_queues[new_symbol]
        main_task = asyncio.create_task(run_task(new_symbol, queue, initial_investment, direction, grid_levels, grid_num, exchange_name, leverage, timeframe, stop_loss, numbers_to_entry, user_id, exchange_instance=exchange_instance, force_restart=force_restart))
        tasks.append(main_task)
        await redis_database.add_tasks(user_id, main_task, exchange_name) # type: ignore[arg-type]

        # Custom Stop 모니터링 태스크 생성 (필요한 경우)
        if custom_stop:
            await create_custom_stop_task(exchange_name, user_id, custom_stop, tasks)

        # Stop Loss 모니터링 태스크 생성 (필요한 경우)
        if stop_loss is not None and stop_loss > 0:
            await create_stop_loss_task(exchange_name, user_id, tasks)

        print(f"Successfully started trading for {new_symbol}")
        return main_task

    except Exception as e:
        print(f"An error occurred in create_new_task for user {user_id}, symbol {new_symbol}: {e}")
        print(traceback.format_exc())
        if new_symbol in running_symbols:
            running_symbols.remove(new_symbol)
            await redis_database.remove_running_symbol(user_id, new_symbol, exchange_name)
        return None




async def create_stop_loss_task(exchange_name, user_id, tasks):
    try:
        monitor_sl_task = asyncio.create_task(monitor_positions(exchange_name, user_id))
        tasks.append(monitor_sl_task)
        await redis_database.add_tasks(user_id, monitor_sl_task, exchange_name) # type: ignore[arg-type]
        print(f"Created stop loss monitoring task for user {user_id}")
    except Exception as e:
        print(f"Error creating stop loss task for user {user_id}: {e}")
        print(traceback.format_exc())




async def create_custom_stop_task(exchange_name, user_id, custom_stop, tasks):
    try:
        monitor_custom_stop_task = asyncio.create_task(monitor_custom_stop(exchange_name, user_id, custom_stop))
        tasks.append(monitor_custom_stop_task)
        await redis_database.add_tasks(user_id, monitor_custom_stop_task, exchange_name) # type: ignore[arg-type]
        print(f"Created custom stop monitoring task for user {user_id}")
    except Exception as e:
        print(f"Error creating custom stop task for user {user_id}: {e}")
        print(traceback.format_exc())




async def get_new_symbols(user_id, exchange_name, direction, limit):
    async with redis_context() as redis:
        try:
            user_key = f'{exchange_name}:user:{user_id}'
            user_data = await redis.hgetall(user_key)

            is_running = parse_bool(user_data.get('is_running', '0'))
            if not is_running:
                print('프로세스가 종료되었습니다.')
                return None

            new_trading_symbols = await get_top_symbols(user_id, exchange_name=exchange_name, direction=direction, limit=limit)

            running_symbols = set(json.loads(user_data.get('running_symbols', '[]')))
            completed_trading_symbols = set(json.loads(user_data.get('completed_trading_symbols', '[]')))

            new_entry_symbols = [symbol for symbol in new_trading_symbols
                                 if symbol not in running_symbols and symbol not in completed_trading_symbols]

            return new_entry_symbols

        except Exception as e:
            print(f"An error occurred on get_new_symbols: {e}")
            print(traceback.format_exc())
            return None
