"""GRID Trading Bot - Main Entry Points Module

메인 진입점 및 시스템 제어 기능:
- main: 메인 트레이딩 프로세스
- sell_all_coins: 전체 포지션 매도
- cancel_all_tasks: 모든 태스크 취소
- start_feature: 디버그용 시작 함수
"""

# ==================== 표준 라이브러리 ====================
import asyncio
import json
import logging
import random
import traceback
from typing import List, Optional

# ==================== 외부 라이브러리 ====================
import requests

# ==================== 프로젝트 모듈 ====================
from GRID.database import redis_database
from GRID.routes.logs_route import add_log_endpoint as add_user_log
from HYPERRSI import telegram_message
from shared.utils import retry_async

# ==================== Core 모듈 ====================
from GRID.core.redis import get_redis_connection

# ==================== Services ====================
from GRID.services.symbol_service import get_top_symbols, format_symbols
from GRID.services.user_management_service import (
    check_permissions_and_initialize,
    get_user_data,
    update_user_data,
    get_and_format_symbols,
    prepare_initial_messages,
    handle_completed_tasks,
)

# ==================== Trading Modules ====================
from GRID.trading.instance_manager import get_exchange_instance
from GRID.monitoring.position_monitor import manually_close_positions

# ==================== Task Management ====================
from GRID.jobs.task_manager import create_tasks

# ==================== Config (for debug only) ====================
try:
    from config import OKX_API_KEY, OKX_SECRET_KEY, OKX_PASSPHRASE
except ImportError:
    OKX_API_KEY = None
    OKX_SECRET_KEY = None
    OKX_PASSPHRASE = None

logger = logging.getLogger(__name__)


# ==============================================================================
#                          Main Entry Functions
# ==============================================================================

async def main(exchange_name, direction, enter_symbol_count, enter_symbol_amount_list, grid_num, leverage, stop_loss, user_id, custom_stop=None, telegram_id=None, force_restart=False):
    try:
        # 초기 설정 및 권한 확인
        try:
            await check_permissions_and_initialize(exchange_name, user_id, enter_symbol_amount_list, grid_num, leverage, stop_loss)
        except Exception as e:
            print(f"Error on starting: {e}")
            raise e

        # Redis 및 사용자 데이터 초기화
        try:
            redis = await get_redis_connection()
            user_id = int(user_id)
            if telegram_id is not None:
                await redis_database.update_telegram_id(exchange_name, user_id, telegram_id)
            is_running = await get_user_data(exchange_name, user_id, "is_running")
            if is_running is None:
                await update_user_data(exchange_name, user_id, is_running=False, tasks=[], running_symbols=set())
            completed_symbols: set[str] = set()
            if force_restart:
                completed_trading_symbols = await get_user_data(exchange_name, user_id, "completed_trading_symbols")
            else:
                await redis.hset(f'{exchange_name}:user:{user_id}', 'completed_trading_symbols', json.dumps(list(completed_symbols)))
        except Exception as e:
            print(f"Error on initializing user data: {str(e)}")
            raise e

        # 초기 메시지 준비 및 전송
        total_enter_symbol_amount = sum(enter_symbol_amount_list)
        if (leverage is not None) and (exchange_name in ['bitget', 'binance', 'okx']):
            initial_investment = [amount * leverage for amount in enter_symbol_amount_list]
        else:
            initial_investment = enter_symbol_amount_list
            leverage = 1
        numbers_to_entry = enter_symbol_count
        initial_capital_list = enter_symbol_amount_list
        modified_symbols = []
        recovery_tasks: list[asyncio.Task] = []
        timeframe = '15m'
        limit = 1000
        initial_capital = initial_investment
        grid_num = int(grid_num)
        recovery_mode = False
        recovery_state = redis.get('recovery_state')

        try:
            n = int(numbers_to_entry)
        except ValueError as e:
            logging.error(f"숫자 변환 오류: {e}")
            n = 5  # 숫자가 아닌 경우 기본값으로 5을 설정

        if recovery_state:
            await asyncio.sleep(random.random())
        await asyncio.sleep(0.1)

        # 심볼 가져오기 및 포맷팅
        symbols, modified_symbols = await get_and_format_symbols(exchange_name, user_id, direction, n, force_restart)

        symbol_queues: dict[str, asyncio.Queue] = {symbol: asyncio.Queue(maxsize=1) for symbol in symbols}
        symbols_formatted = format_symbols(symbols)

        # 메시지 준비
        message = await prepare_initial_messages(
            exchange_name, user_id, symbols, enter_symbol_amount_list, leverage, total_enter_symbol_amount
        )

        await redis_database.update_user_running_status(exchange_name, user_id, is_running=True)
        try:
            await add_user_log(user_id, message)
            #asyncio.create_task(telegram_message.send_telegram_message(message, exchange_name, user_id))
            trading_semaphore = asyncio.Semaphore(numbers_to_entry)
            completed_symbols = set()
            running_symbols: set[str] = set()
            await update_user_data(exchange_name, user_id, running_symbols=set())
            tasks = []
        except Exception as e:
            print(f"{user_id} : An error occurred while sending initial logs: {e}")
            print(traceback.format_exc())
            print("Tasks have been cancelled.")
            raise e

        try:
            exchange_instance = await get_exchange_instance(exchange_name, user_id)
            user_key = f'{exchange_name}:user:{user_id}'
            while True:
                is_running = await get_user_data(exchange_name, user_id, "is_running")
                if not is_running:
                    break

                async with trading_semaphore:
                    if len(running_symbols) <= enter_symbol_count:
                        try:
                            new_symbols = [s for s in symbols if s not in completed_symbols and s not in running_symbols]
                            if new_symbols:
                                print(f"😈Attempting to create tasks for symbols: {new_symbols}")
                                created_tasks = await create_tasks(
                                    new_symbols, symbol_queues, initial_investment, direction,
                                    timeframe, grid_num, exchange_name, leverage, user_id,
                                    stop_loss, numbers_to_entry, exchange_instance, custom_stop, force_restart
                                )
                                if created_tasks:
                                    tasks.extend(created_tasks)
                                    print(f"Created and managed {len(created_tasks)} new tasks.")
                                else:
                                    print("No new tasks were created or all tasks completed.")
                            else:
                                print("No suitable new symbols found.")
                        except Exception as e:
                            print(f"An error occurred during task creation: {e}")
                            print(traceback.format_exc())
                    else:
                        print(f"Running symbols: {running_symbols}")
                        print(f"Completed symbols: {completed_symbols}")
                        print(f"Running tasks: {len(tasks)}")
                        print(f"Completed tasks: {len([task for task in tasks if task.done()])}")

                    try:
                        is_running = await get_user_data(exchange_name, user_id, "is_running")
                        if not is_running:
                            break
                        if len(running_symbols) <= enter_symbol_count:
                            potential_recovery_symbols = await get_top_symbols(user_id, exchange_name, direction, limit=32)
                            new_symbols = [s for s in potential_recovery_symbols if s not in completed_symbols and s not in running_symbols]
                            if new_symbols:
                                print(f"Attempting recovery with symbols: {new_symbols[:1]}")
                                tasks.extend(recovery_tasks)
                                running_symbols.update(new_symbols[:1])
                                print(f"Successfully created {len(recovery_tasks)} recovery tasks.")

                                await telegram_message.send_telegram_message(
                                    f"새로운 심볼 {new_symbols[:1]}로 재진입", exchange_name, user_id
                                )
                                await redis.hset(user_key, 'running_symbols', json.dumps(list(running_symbols)))
                                recovery_tasks = await create_tasks(
                                    new_symbols[:1], symbol_queues, initial_investment, direction, timeframe, grid_num, exchange_name, leverage, user_id,
                                    stop_loss=stop_loss, numbers_to_entry=numbers_to_entry,
                                    exchange_instance=exchange_instance, custom_stop=custom_stop
                                )
                                if recovery_tasks:
                                    all_task_names = [task.get_name() for task in tasks]
                                    await redis.hset(user_key, 'tasks', json.dumps(all_task_names))
                                else:
                                    print(f" {user_id} : Recovery tasks were created but returned empty. This is unexpected.")
                            else:
                                print(f" {user_id} : No suitable recovery symbols found after exception.")
                                await asyncio.sleep(10)
                    except Exception as recovery_e:
                        print(f"Error during recovery: {recovery_e}")
                        print(traceback.format_exc())

                # 완료된 태스크 처리
                await handle_completed_tasks(tasks, exchange_name, user_id, completed_symbols, running_symbols, user_key, redis)

                await asyncio.sleep(3)  # 루프 사이에 짧은 대기 시간 추가
        except Exception as e:
            print(f"{user_id} : An error occurred during main loop: {e}")
            raise e

        # 모든 실행 중인 태스크 완료 대기
        try:
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            trading_success = True
            final_message = f"매매가 종료되었습니다"
        except Exception as e:
            print('exception! ')
            print(f"Unexpected error in run_task for {user_id}: {e}")
            print(traceback.format_exc())
            raise e
    except KeyboardInterrupt:
        print("Caught KeyboardInterrupt. Cleaning up...")
        print("is_running set to False")
        raise
    except Exception as e:
        print('[START FEATURE EXCEPTION]', e)
        print(traceback.format_exc())
        raise e
    finally:
        from grid_process import stop_grid_main_process
        message = f"{user_id} : 매매가 종료되었습니다.\n모든 트레이딩이 종료되었습니다"
        await stop_grid_main_process(exchange_name, user_id)
        await telegram_message.send_telegram_message(f"{user_id} : 매매가 종료되었습니다", exchange_name, user_id)
        await add_user_log(user_id, message)
        await redis_database.update_user_running_status(exchange_name, user_id, is_running=False)


#==============================================================================
# ENDPOINT : SELL ALL
#==============================================================================

async def sell_all_coins(exchange_name, user_id):
    print('========================[SELL ALL COINS]========================')
    await retry_async(manually_close_positions, exchange_name, user_id)
    print('========================[SELL ALL COINS END]========================')


#==============================================================================
# ENDPOINT : CANCEL ALL TASKS
#==============================================================================

async def cancel_all_tasks(loop):
    tasks = [task for task in asyncio.all_tasks(loop) if task is not asyncio.current_task(loop)]
    list(map(lambda task: task.cancel(), tasks))
    await asyncio.gather(*tasks, return_exceptions=True)



#==============================================================================
# D E B U G O N L Y
#==============================================================================
def start_feature():
    url = 'http://localhost:8000/feature/start'
    headers = {
        'accept': 'application/json',
        'Content-Type': 'application/json'
    }
    data = {
        "exchange_name": "upbit",
        "enter_strategy": "long",
        "enter_symbol_count": 5,
        "enter_symbol_amount_list": [50000],
        "grid_num": 20,
        "leverage": 1,
        "stop_loss": 3,
        "custom_stop": 240,
        "telegram_id": 1709556958,
        "user_id": 1234,
        "api_key": OKX_API_KEY,
        "api_secret": OKX_SECRET_KEY,
        "password": OKX_PASSPHRASE
    }
    response = requests.post(url, headers=headers, json=data)
    print(response.status_code, response.text)

if __name__ == "__main__":
    start_feature()
