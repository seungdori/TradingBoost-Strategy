import aiohttp
import asyncio
import json
import pandas as pd
import redis
from shared.utils import path_helper
import glob
import os
import traceback   
from GRID.trading import redis_connection_manager
from GRID.database import redis_database
from GRID.database.redis_database import RedisConnectionManager
from GRID.repositories.symbol_repository import (
    add_symbols,
    clear_blacklist,
    clear_whitelist,
    get_ban_list_from_db,
    get_white_list_from_db,
)
import redis.asyncio as aioredis
import concurrent.futures
from shared.dtos.trading import WinrateDto
from typing import List, Optional, Any
from functools import partial
from shared.utils import retry_async
from GRID.strategies import strategy
from GRID.strategies.grid import place_grid_orders, ws_client, monitor_positions, monitor_custom_stop
from GRID.main import periodic_analysis
import random
from GRID.strategies import grid
from GRID import telegram_message
from GRID.routes.trading_route import ConnectionManager

manager = ConnectionManager()

from shared.config import settings

REDIS_PASSWORD = settings.REDIS_PASSWORD

redis_manager = RedisConnectionManager()



class QuitException(Exception):
    pass

class AddAnotherException(Exception):
    pass

async def add_user_log(user_id: int, log_message: str) -> None:
    message = f"User {user_id}: {log_message}"
    await manager.add_user_message(user_id, message)
    #print("[LOG ADDED]", message)



pool: aioredis.ConnectionPool
if REDIS_PASSWORD:
    pool = aioredis.ConnectionPool.from_url(
        'redis://localhost', 
        max_connections=150,
        encoding='utf-8', 
        decode_responses=True,
        password=REDIS_PASSWORD
    )
    redis_client = aioredis.Redis(connection_pool=pool) 
else:
    pool = aioredis.ConnectionPool.from_url(
        'redis://localhost', 
        max_connections=150,
        encoding='utf-8', 
        decode_responses=True
    )
    redis_client = aioredis.Redis(connection_pool=pool)

MAX_RETRIES = 3
RETRY_DELAY = 3  # 재시도 사이의 대기 시간(초)

# retry_async is now imported from shared.utils




async def get_redis_connection():
    return redis_client

#================================================================================================
# GET SYMBOLS
#================================================================================================


async def get_new_symbols(user_id, exchange_name, direction, limit):
    redis = await get_redis_connection()
    try:
        user_key = f'{exchange_name}:user:{user_id}'
        user_data = await redis.hgetall(user_key)

        is_running = bool(int(user_data.get('is_running', '0')))
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
    finally:
        await redis.close()

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
        summary_df = pd.DataFrame(results)
        summary_file_path = path_helper.grid_dir / exchange_name / direction / f"{exchange_name}_summary_trading_results.csv"
        summary_df.to_csv(summary_file_path, index=False)
        print(f"{exchange_name}의 거래 전략 요약이 완료되었습니다. 파일 경로: {summary_file_path}")
    except Exception as e:
        print(f"An error occurred24: {e}")
        print(traceback.format_exc())


def process_exchange_data(exchange_name, direction, ban_list, white_list, market_data=None):
    if exchange_name == 'upbit':
        symbols = pd.DataFrame(market_data.items(), columns=['name', 'change_rate'])
        symbols = symbols[~symbols['name'].isin(ban_list)]
        sorted_column = 'change_rate'
    else:
        exchange_folder = exchange_name
        summarize_trading_results(exchange_name=exchange_name, direction=direction)
        profit_data = sort_ai_trading_data(exchange_name=exchange_name, direction=direction)

        if exchange_folder in ['binance', 'bitget', 'binance_spot', 'bitget_spot', 'okx_spot']:
            symbols = profit_data[(profit_data['name'].astype(str).str.endswith('USDT')) & 
                                  ~(profit_data['name'].astype(str).str.contains('USDC')) & 
                                  ~(profit_data['name'].astype(str).str.contains('USTC'))]
            sorted_column = 'win_rate'
        elif exchange_folder == 'okx':
            symbols = profit_data[(profit_data['name'].astype(str).str.endswith('USDT-SWAP')) & 
                                  ~(profit_data['name'].astype(str).str.contains('USDC')) & 
                                  ~(profit_data['name'].astype(str).str.contains('USTC'))]
            sorted_column = 'win_rate'
        else:
            symbols = profit_data
            sorted_column = 'win_rate'

    for ban_word in ban_list:
        symbols = symbols[~symbols['name'].str.contains(ban_word, case = False)]

    return symbols, sorted_column



def sort_ai_trading_data(exchange_name, direction):
    if exchange_name is None:
        raise ValueError("exchange 변수가 None입니다. 올바른 값을 제공해야 합니다.")

    summary_path = path_helper.grid_dir / str(exchange_name) / str(direction) / f"{exchange_name}_summary_trading_results.csv"
    print(summary_path)
    df_summary = pd.read_csv(summary_path)

    # 'symbol' 열을 'name'으로 이름 변경
    df_summary.rename(columns={'symbol': 'name'}, inplace=True)
    # 'total_profit' 열을 'win_rate'로 이름 변경하여 사용하기
    df_summary.rename(columns={'total_profit': 'win_rate'}, inplace=True)

    return df_summary[['name', 'win_rate']]

async def build_sort_ai_trading_data(exchange_name: str, enter_strategy: str) -> List[WinrateDto]:
    direction = str(enter_strategy).lower()
    if exchange_name is None:
        raise ValueError("exchange 변수가 None입니다. 올바른 값을 제공해야 합니다.")
    if direction is None:
        raise ValueError("direction 변수가 None입니다. 올바른 값을 제공해야 합니다.")

    exchange_name = str(exchange_name).lower()
    summary_path = path_helper.grid_dir / str(exchange_name) / direction / f"{exchange_name}_summary_trading_results.csv"
    # summary_trading_results.csv 파일에서 데이터 읽기
    df_summary = pd.read_csv(summary_path)

    # 'total_profit' 열을 기반으로 각 win_rate 값 설정, assuming 'total_profit' column exists
    df_summary['long_win_rate'] = df_summary['total_profit']
    df_summary['short_win_rate'] = df_summary['total_profit']
    df_summary['total_win_rate'] = df_summary['total_profit']

    # Ensure that 'symbol' column is correctly renamed to 'name'
    df_summary_renamed = df_summary.rename(columns={'symbol': 'name'})

    # Create WinrateDto objects from the DataFrame
    win_rate_data = [
        WinrateDto(
            name=row['name'],  # Correctly reference the 'name' column after renaming
            long_win_rate=row['long_win_rate'],
            short_win_rate=row['short_win_rate'],
            total_win_rate=row['total_win_rate']
        )
        for _, row in df_summary_renamed.iterrows()
    ]

    return win_rate_data



async def get_running_symbols(exchange_id: str, user_id: str) -> list:
    redis = await get_redis_connection()
    redis_key = f"running_symbols:{exchange_id}:{user_id}"
    running_symbols_json = await redis.get(redis_key)
    
    
    if running_symbols_json:
        await redis.delete(redis_key)
        result: list = json.loads(running_symbols_json)
        return result
    return []
    
    
#================================================================================================
def safe_json_loads(data, default):
    if isinstance(data, str):
        try:
            return json.loads(data)
        except json.JSONDecodeError:
            print(f"Invalid JSON: {data}")
            return default
    return data if isinstance(data, (list, set)) else default

async def task_completed(task: Any, new_symbol: str, exchange_name: str, user_id: str) -> None:
    print(f'매개변수 확인. task: {task}, new_symbol: {new_symbol}, exchange_name: {exchange_name}, user_id: {user_id}')
    redis = await get_redis_connection()
    try:
        user_key = f'{exchange_name}:user:{user_id}'
        user_data = await redis.hgetall(user_key)

        grid_num = int(user_data.get("grid_num", 20))
        leverage = float(user_data.get("leverage", 1))
        direction = user_data.get("direction", "long")
        initial_capital_json = user_data.get("initial_capital", "[]")
        initial_capital_list = json.loads(initial_capital_json) if isinstance(initial_capital_json, str) else initial_capital_json
        stop_loss = float(user_data.get("stop_loss", 0))
        running_symbols = set(json.loads(user_data.get('running_symbols', '[]')))
        completed_symbols = set(json.loads(user_data.get('completed_trading_symbols', '[]')))
        tasks = safe_json_loads(user_data.get('tasks', '[]'), [])

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

        is_running = bool(int(user_data.get('is_running', '0')))
        if is_running:
            for symbol in filtered_symbols[:limit]:
                print(f"filtered_symbols[:limit] : {filtered_symbols[:limit]}")
                print(f"symbol {symbol}")
                symbol_queues: dict[str, asyncio.Queue[Any]] = {symbol: asyncio.Queue(maxsize=1)}
                await asyncio.create_task(grid.create_new_task(new_symbol=symbol, symbol_queues=symbol_queues,
                                                          initial_investment=initial_capital_list, direction=direction,
                                                          timeframe='15m', grid_num=grid_num, exchange_name=exchange_name,
                                                          leverage=leverage, user_id=user_id, stop_loss=stop_loss, numbers_to_entry=limit))
            message = f"🚀 새로운 심볼{new_entry_symbols}에 대한 매매를 시작합니다."
            await telegram_message.send_telegram_message(message, exchange_name, user_id)
            await add_user_log(int(user_id), message)
        else:
            print("테스크가 종료 되었습니다.")
            message = f"🚀 매매가 종료되었습니다.\n모든 트레이딩이 종료되었습니다."
            await telegram_message.send_telegram_message(message, exchange_name, user_id)
            await add_user_log(int(user_id), message)
            return
    except Exception as e:
        print(f"An error occurred on task_completed: {e}")
        print(traceback.format_exc())
    finally:
        await redis.close()

    

async def get_top_symbols(user_id, exchange_name, direction='long-short', limit=20, force_restart=False):
    try:
        ban_list = await get_ban_list_from_db(user_id, exchange_name)
        print("ban_list : ", ban_list)
    except FileNotFoundError:
        ban_list = []
        print('ban_list.json 파일이 존재하지 않습니다. 빈 리스트로 초기화합니다.')

    ban_list.extend(['XEC', 'USTC', 'USDC', 'TRY', 'CEL', 'GAL', 'OMG', 'SPELL', 'KSM'])

    try:
        white_list = await get_white_list_from_db(user_id, exchange_name)
    except FileNotFoundError:
        white_list = []
        print('white_list.json 파일이 존재하지 않습니다. 빈 리스트로 초기화합니다.')



    market_data = await get_upbit_market_data() if exchange_name == 'upbit' else None

    loop = asyncio.get_event_loop()
    with concurrent.futures.ThreadPoolExecutor() as pool:
        symbols, sorted_column = await loop.run_in_executor(
            pool,
            partial(process_exchange_data, exchange_name, direction, ban_list, white_list, market_data)
        )

    if white_list:
        if exchange_name in ['binance', 'bitget', 'binance_spot', 'bitget_spot']:
            white_list = [symbol + 'USDT' for symbol in white_list]
        elif exchange_name == 'upbit':
            white_list = ['KRW-' + symbol for symbol in white_list]
        elif exchange_name == 'okx':
            white_list = [symbol + '-USDT-SWAP' for symbol in white_list]
        elif exchange_name == 'okx_spot':
            white_list = [symbol + '-USDT' for symbol in white_list]


    try:
        if force_restart :
            former_running_symbols = await get_running_symbols(exchange_name, user_id)
            print(f"former_running_symbols : {former_running_symbols}")
        else:
            former_running_symbols = []
    except Exception as e:
        print(f"An error occurred while fetching running symbols: {e}")
        former_running_symbols = []

    # former_running_symbols를 우선 포함
    top_symbols = []
    for symbol in former_running_symbols:
        if symbol in symbols['name'].tolist():
            top_symbols.append(symbol)
    
    remaining_limit = limit - len(top_symbols)

    if remaining_limit > 0:
        # white_list에서 남은 종목 선택
        white_list_symbols = symbols[symbols['name'].str.lower().isin([w.lower() for w in white_list])]
        white_list_top_symbols = white_list_symbols.sort_values(by=sorted_column, ascending=False).head(remaining_limit)
        
        top_symbols.extend(white_list_top_symbols['name'].tolist())
        remaining_limit -= len(white_list_top_symbols)

    if remaining_limit > 0:
        # 나머지 종목에서 선택
        non_selected_symbols = symbols[~symbols['name'].isin(top_symbols)]
        non_selected_top_symbols = non_selected_symbols.sort_values(by=sorted_column, ascending=False).head(remaining_limit)
        top_symbols.extend(non_selected_top_symbols['name'].tolist())

    print(f"ban_list : {ban_list}")
    print(top_symbols)
    return top_symbols

async def get_upbit_market_data():
    url = "https://api.upbit.com/v1/market/all"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            markets = await response.json()
    
    krw_markets = [market['market'] for market in markets if market['market'].startswith('KRW-')]
    
    url = "https://api.upbit.com/v1/ticker"
    params = {"markets": ",".join(krw_markets)}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params) as response:
            tickers = await response.json()
    # 변화율을 절대값이 아닌 실제 값으로 가져오기
    market_data = {ticker['market']: ticker['signed_change_rate'] for ticker in tickers}
    
    # 변화율이 높은 것부터 낮은 순서대로 소팅
    sorted_market_data = dict(sorted(market_data.items(), key=lambda item: item[1], reverse=True))
    
    return sorted_market_data




async def create_tasks(new_symbols, symbol_queues, initial_investment, direction, timeframe, grid_num, exchange_name, leverage, user_id, stop_loss, exchange_instance, custom_stop=False):
    redis = await get_redis_connection()
    created_tasks = []
    try:
        user_key = f'{exchange_name}:user:{user_id}'

        # Get user data
        user_data = await redis.hgetall(user_key)
        user_data = {k.decode('utf-8') if isinstance(k, bytes) else k: 
                     v.decode('utf-8') if isinstance(v, bytes) else v 
                     for k, v in user_data.items()}

        running_symbols = set(json.loads(user_data.get('running_symbols', '[]')))
        completed_symbols = set(json.loads(user_data.get('completed_trading_symbols', '[]')))
        existing_tasks = json.loads(user_data.get('tasks', '[]'))

        for new_symbol in new_symbols:
            if new_symbol in completed_symbols or new_symbol in running_symbols:
                print(f"Symbol {new_symbol} is already completed or running. Skipping.")
                continue

            try:
                running_symbols.add(new_symbol)
                
                grid_levels = await periodic_analysis.calculate_grid_logic(direction, grid_num, new_symbol, exchange_name, user_id, exchange_instance)
                
                if grid_levels is None:
                    print(f"Grid levels for {new_symbol} is None. Skipping.")
                    running_symbols.remove(new_symbol)
                    continue

                if not isinstance(symbol_queues, dict):
                    symbol_queues = {symbol: asyncio.Queue(maxsize=1) for symbol in new_symbols}

                queue = symbol_queues[new_symbol]
                await asyncio.sleep(0.1)  # Short delay to prevent overloading

                task = asyncio.create_task(run_task(new_symbol, queue, initial_investment, direction, grid_levels, grid_num, exchange_name, leverage, timeframe, stop_loss, user_id))
                task_name = f"task_{new_symbol}_{user_id}"
                task.set_name(task_name)
                existing_tasks.append(task_name)
                created_tasks.append(task)
                
                print(f"Starting trading for {new_symbol}")
            except Exception as e:
                print(f"Error creating task for {new_symbol}: {e}")
                print(traceback.format_exc())
                if new_symbol in running_symbols:
                    running_symbols.remove(new_symbol)
                continue

        # Update Redis with new running symbols and tasks
        await redis.hset(user_key, 'running_symbols', json.dumps(list(running_symbols)))
        await redis.hset(user_key, 'tasks', json.dumps(existing_tasks))

        # Create stop loss monitoring task if needed
        if stop_loss is not None and stop_loss > 0 and exchange_name != 'upbit':
            monitor_sl_task = asyncio.create_task(monitor_positions(exchange_name, user_id))
            monitor_sl_task_name = f"monitor_sl_{user_id}"
            monitor_sl_task.set_name(monitor_sl_task_name)
            existing_tasks.append(monitor_sl_task_name)
            created_tasks.append(monitor_sl_task)

        # Create custom stop monitoring task if needed
        if custom_stop is not None:
            monitor_custom_stop_task = asyncio.create_task(monitor_custom_stop(exchange_name, user_id, custom_stop))
            monitor_custom_stop_task_name = f"monitor_custom_stop_{user_id}"
            monitor_custom_stop_task.set_name(monitor_custom_stop_task_name)
            existing_tasks.append(monitor_custom_stop_task_name)
            created_tasks.append(monitor_custom_stop_task)

        await redis.hset(user_key, 'tasks', json.dumps(existing_tasks))
                
    except Exception as e:
        print(f"An error occurred on create_tasks: {e}")
        print(traceback.format_exc())
    finally:
        await redis.close()
        return created_tasks



#================================================================================================
# 트레이딩 루프 TRADING LOOP
#================================================================================================
async def create_tasks(new_symbols, symbol_queues, initial_investment, direction, timeframe, grid_num, exchange_name, leverage, user_id, stop_loss, exchange_instance , custom_stop=False):  # type: ignore[no-redef]
    redis = await get_redis_connection()
    created_tasks = []
    try:
        user_key = f'{exchange_name}:user:{user_id}'

        # Get user data
        user_data = await redis.hgetall(user_key)
        user_data = {k.decode('utf-8') if isinstance(k, bytes) else k: 
                     v.decode('utf-8') if isinstance(v, bytes) else v 
                     for k, v in user_data.items()}

        running_symbols = set(json.loads(user_data.get('running_symbols', '[]')))
        completed_symbols = set(json.loads(user_data.get('completed_trading_symbols', '[]')))
        existing_tasks = json.loads(user_data.get('tasks', '[]'))

        for new_symbol in new_symbols:
            if new_symbol in completed_symbols or new_symbol in running_symbols:
                print(f"Symbol {new_symbol} is already completed or running. Skipping.")
                continue

            try:
                running_symbols.add(new_symbol)
                
                grid_levels = await periodic_analysis.calculate_grid_logic(direction, grid_num, new_symbol, exchange_name, user_id)
                
                if grid_levels is None:
                    print(f"Grid levels for {new_symbol} is None. Skipping.")
                    running_symbols.remove(new_symbol)
                    continue

                if not isinstance(symbol_queues, dict):
                    symbol_queues = {symbol: asyncio.Queue(maxsize=1) for symbol in new_symbols}

                queue = symbol_queues[new_symbol]
                await asyncio.sleep(0.1)  # Short delay to prevent overloading

                task = asyncio.create_task(run_task(new_symbol, queue, initial_investment, direction, grid_levels, grid_num, exchange_name, leverage, timeframe, stop_loss, user_id))
                task_name = f"task_{new_symbol}_{user_id}"
                task.set_name(task_name)
                existing_tasks.append(task_name)
                created_tasks.append(task)
                
                print(f"Starting trading for {new_symbol}")
            except Exception as e:
                print(f"Error creating task for {new_symbol}: {e}")
                print(traceback.format_exc())
                if new_symbol in running_symbols:
                    running_symbols.remove(new_symbol)
                continue

        # Update Redis with new running symbols and tasks
        await redis.hset(user_key, 'running_symbols', json.dumps(list(running_symbols)))
        await redis.hset(user_key, 'tasks', json.dumps(existing_tasks))

        # Create stop loss monitoring task if needed
        if stop_loss is not None and stop_loss > 0 and exchange_name != 'upbit':
            monitor_sl_task = asyncio.create_task(monitor_positions(exchange_name, user_id))
            monitor_sl_task_name = f"monitor_sl_{user_id}"
            monitor_sl_task.set_name(monitor_sl_task_name)
            existing_tasks.append(monitor_sl_task_name)
            created_tasks.append(monitor_sl_task)

        # Create custom stop monitoring task if needed
        if custom_stop is not None:
            monitor_custom_stop_task = asyncio.create_task(monitor_custom_stop(exchange_name, user_id, custom_stop))
            monitor_custom_stop_task_name = f"monitor_custom_stop_{user_id}"
            monitor_custom_stop_task.set_name(monitor_custom_stop_task_name)
            existing_tasks.append(monitor_custom_stop_task_name)
            created_tasks.append(monitor_custom_stop_task)

        await redis.hset(user_key, 'tasks', json.dumps(existing_tasks))
                
    except Exception as e:
        print(f"An error occurred on create_tasks: {e}")
        print(traceback.format_exc())
    finally:
        await redis.close()
        return created_tasks


async def run_task(symbol, queue, initial_investment, direction, grid_levels, grid_num, exchange_name, leverage, timeframe, stop_loss, user_id):
    redis = await get_redis_connection()
    try:
        user_key = f'{exchange_name}:user:{user_id}'
        if not await redis.exists(user_key):
            await redis.hset(user_key, mapping = {
                'is_running': '0',
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
        
        if is_running:
            if exchange_name in ['binance', 'bitget', 'okx'] and int(leverage) > 1:
                try:
                    await asyncio.sleep(random.uniform(0.8, 1.3))
                    await retry_async(strategy.change_leverage, exchange_name, symbol, leverage, user_id)
                except Exception as e:
                    print(f"Error changing leverage for {symbol}: {e}")
                    print(traceback.format_exc())
                    return symbol
            try:
                user_key = f'{exchange_name}:user:{user_id}'
                
                await asyncio.sleep(random.uniform(1, 1.7))
                
                ws_task = asyncio.create_task(ws_client(exchange_name, symbol, queue, user_id))
                order_task = asyncio.create_task(place_grid_orders(symbol, initial_investment, direction, grid_levels, queue, grid_num, exchange_name, user_id))  # type: ignore[call-arg]
                tasks = json.loads(await redis.hget(user_key, 'tasks') or '[]')
                tasks.extend([str(ws_task.get_name()), str(order_task.get_name())])
                await redis.hset(user_key, 'tasks', json.dumps(tasks))
                results = await asyncio.gather(ws_task, order_task, return_exceptions=True)
            except Exception as e:
                print(f"Error running tasks for symbol {symbol}: {e}")
                print(traceback.format_exc())
                return symbol
            # Check if user is still running
            is_running = await redis.hget(user_key, 'is_running')
            if is_running == b'1':
                for result in results:
                    if isinstance(result, QuitException):
                        await grid.cancel_tasks(user_id, exchange_name)
                        print(f"Task for {symbol} completed. Finding new task...")
                        return symbol
                    elif isinstance(result, AddAnotherException):
                        await task_completed(task=order_task, new_symbol=symbol, exchange_name=exchange_name, user_id=user_id)
                        print(f"Task for {symbol} failed. Finding new task...")
                        return None
                
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
        print(f"Error running tasks for symbol {symbol}: {e}")
        print(traceback.format_exc())
        return None



async def trading_loop(exchange_name, user_id, initial_investment, direction, timeframe, grid_num, leverage, stop_loss, custom_stop):
    trading_semaphore = asyncio.Semaphore(5)  # Limit concurrent operations
    symbol_queues: dict[str, asyncio.Queue[Any]] = {}
    tasks = []
    completed_symbols = set()
    running_symbols = set()

    while True:
        is_running = await grid.get_user_data(exchange_name, user_id, "is_running")
        if not is_running:
            break

        async with trading_semaphore:
            try:
                # Get new symbols
                potential_symbols = await get_top_symbols(user_id, exchange_name, direction, limit=10)
                new_symbols = [s for s in potential_symbols if s not in completed_symbols and s not in running_symbols]

                if new_symbols:
                    created_tasks = await create_tasks(new_symbols, symbol_queues, initial_investment, direction, timeframe, grid_num, exchange_name, leverage, user_id, stop_loss, custom_stop)
                    if created_tasks:
                        tasks.extend(created_tasks)
                        running_symbols.update(new_symbols)
                        print(f"Created and managed {len(created_tasks)} new tasks.")
                    else:
                        print("No new tasks were created.")
                else:
                    print("No suitable new symbols found.")

            except Exception as e:
                print(f"An error occurred during task creation: {e}")
                print(traceback.format_exc())

            # Process completed tasks
            done_tasks = [task for task in tasks if task.done()]
            for task in done_tasks:
                try:
                    result = await task
                    if result:
                        completed_symbols.add(result)
                        running_symbols.remove(result)
                        print(f"Completed symbol: {result}")
                except Exception as task_e:
                    print(f"Error processing completed task: {task_e}")
                tasks.remove(task)

            # Replace completed or failed tasks
            if len(running_symbols) < 5:  # Maintain at least 5 running tasks
                replacement_needed = 5 - len(running_symbols)
                potential_replacement_symbols = await get_top_symbols(user_id, exchange_name, direction, limit=replacement_needed + 3)
                replacement_symbols = [s for s in potential_replacement_symbols if s not in completed_symbols and s not in running_symbols][:replacement_needed]
                
                if replacement_symbols:
                    print(f"Attempting to add replacement symbols: {replacement_symbols}")
                    replacement_tasks = await create_tasks(replacement_symbols, symbol_queues, initial_investment, direction, timeframe, grid_num, exchange_name, leverage, user_id, stop_loss, custom_stop)
                    if replacement_tasks:
                        tasks.extend(replacement_tasks)
                        running_symbols.update(replacement_symbols)
                        print(f"Successfully added {len(replacement_tasks)} replacement tasks.")
                    else:
                        print("No replacement tasks were created.")
                else:
                    print("No suitable replacement symbols found.")

        await asyncio.sleep(60)  # Wait for 1 minute before the next iteration
