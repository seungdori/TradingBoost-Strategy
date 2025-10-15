
import asyncio
import json
import logging
import time
import traceback
from datetime import datetime
from functools import lru_cache
from typing import Any, Dict, List, Mapping, Optional, cast
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from redis.asyncio import Redis
from redis.exceptions import RedisError

from shared.config import settings
from shared.database.redis import get_redis
from shared.utils import parse_bool, safe_float

#================================================================================================
# REDIS SETTINGS
#================================================================================================
CACHE_EXPIRY = 60  # 캐시 유효 기간 (초)

REDIS_PASSWORD = settings.REDIS_PASSWORD

class UserKeyCache:
    def __init__(self) -> None:
        self.cache: dict[str, Any] = {}
        self.last_updated: dict[str, float] = {}

    def get(self, exchange_name: str, user_id: str | int) -> Any | None:
        key = f"{exchange_name}:{user_id}"
        cached_data = self.cache.get(key)
        if cached_data and time.time() - self.last_updated.get(key, 0) < CACHE_EXPIRY:
            return cached_data
        return None

    def set(self, exchange_name: str, user_id: str | int, data: Any) -> None:
        key = f"{exchange_name}:{user_id}"
        self.cache[key] = data
        self.last_updated[key] = time.time()

    def delete(self, exchange_name: str, user_id: str | int) -> None:
        key = f"{exchange_name}:{user_id}"
        self.cache.pop(key, None)
        self.last_updated.pop(key, None)


user_key_cache = UserKeyCache()


async def get_redis_connection() -> Redis:
    """Use shared Redis connection pool (backward compatibility wrapper)"""
    return await get_redis()

# parse_bool is now imported from shared.utils
#================================================================================================
# INIT
#================================================================================================


async def init_job_table(exchange_name: str) -> None:
    redis = await get_redis_connection()
    try:
        # Redis doesn't need table initialization, but we can set up some default values if needed
        await redis.set(f'{exchange_name}:job_table_initialized', 'true')
        print(f"Job table initialized successfully for {exchange_name}")
    except Exception as e:
        print(f"Error initializing job table for {exchange_name}: {e}")
        raise
    finally:
        await redis.close()

async def initialize_database(exchange_name: str) -> None:
    redis = await get_redis_connection()
    try:
        # Create a hash for default user settings
        default_settings = {
            'initial_capital': '10',
            'direction': 'long',
            'numbers_to_entry': '5',
            'leverage': '10',
            'is_running': '0',
            'stop_loss': '0',
            'tasks': '[]',
            'running_symbols': '[]',
            'grid_num': '20',
            'stop_task_only': '0',
        }
        await redis.hset(f'{exchange_name}:default_settings', mapping=cast(Mapping[str | bytes, bytes | float | int | str], default_settings))

        # Create an index to keep track of user IDs
        await redis.sadd(f'{exchange_name}:user_ids', '0')  # Start with 0 as we'll increment for new users

        # Initialize system-wide settings or metadata if needed
        await redis.set(f'{exchange_name}:last_update', str(int(time.time())))

        # Create sets for global blacklist and whitelist if needed
        await redis.sadd(f'{exchange_name}:global_blacklist', 'EXAMPLE_BLACKLISTED_SYMBOL')
        await redis.sadd(f'{exchange_name}:global_whitelist', 'EXAMPLE_WHITELISTED_SYMBOL')
        #print(f"Redis database for {exchange_name} initialized successfully.")
    except Exception as e:
        print(f"Error initializing Redis database for {exchange_name}: {e}")
    finally:
        await redis.close()

async def add_user(exchange_name: str, user_data: dict[str, Any]) -> int:
    redis = await get_redis_connection()

    try:
        # Get a new user ID
        user_id = await redis.incr(f'{exchange_name}:next_user_id')

        # Add the new user ID to the set of user IDs
        await redis.sadd(f'{exchange_name}:user_ids', str(user_id))

        # Create a hash for the user with default settings and provided data
        user_key = f'{exchange_name}:user:{user_id}'
        default_settings = await redis.hgetall(f'{exchange_name}:default_settings')
        merged_data = {**default_settings, **user_data}  # Merge default settings with provided data
        await redis.hset(user_key, mapping=cast(Mapping[str | bytes, bytes | float | int | str], merged_data))
        # Initialize empty blacklist and whitelist for the user
        await redis.sadd(f'{exchange_name}:blacklist:{user_id}', 'PLACEHOLDER')
        await redis.sadd(f'{exchange_name}:whitelist:{user_id}', 'PLACEHOLDER')
        await redis.srem(f'{exchange_name}:blacklist:{user_id}', 'PLACEHOLDER')
        await redis.srem(f'{exchange_name}:whitelist:{user_id}', 'PLACEHOLDER')

        return user_id
    finally:
        await redis.close()
#================================================================================================
# TRADING
#================================================================================================
async def initialize_active_grid(
    redis: Redis,
    exchange_name: str,
    user_id: int,
    symbol_name: str
) -> Dict[int, Dict[str, Any]]:
    key = f"{exchange_name}:user:{user_id}:symbol:{symbol_name}:active_grid"
    
    active_grid = {
        i: {
            'entry_price': 0.0,
            'position_size': 0.0,
            'grid_count': 0,
            'pnl': 0.0,
            'execution_time': None
        } for i in range(21)
    }
    
    # Convert grid_data to a flat dictionary
    flat_data: dict[str, str] = {}
    for level, data in active_grid.items():
        for field, value in data.items():
            flat_data[f"{level}:{field}"] = json.dumps(value)

    # Use hset with mapping instead of deprecated hmset
    await redis.hset(key, mapping=cast(Mapping[str | bytes, bytes | float | int | str], flat_data))

    return active_grid

async def get_active_grid(redis: Redis, exchange_name: str, user_id: int, symbol_name: str) -> dict[int, dict[str, Any]]:
    base_key = f"{exchange_name}:user:{user_id}:symbol:{symbol_name}"
    active_grid = {}

    # 먼저 키가 존재하는지 확인
    exists = await redis.exists(f"{base_key}:active_grid:0")
    if not exists:
        return {}  # 또는 빈 딕셔너리 return {}

    async with redis.pipeline(transaction=False) as pipe:
        for level in range(21):  # 0부터 20까지의 그리드 레벨에 대해 반복
            grid_key = f"{base_key}:active_grid:{level}"
            pipe.hgetall(grid_key)
        
        results = await pipe.execute()

    for level, grid_data in enumerate(results):
        if grid_data:  # 데이터가 있는 경우에만 처리
            try:
                if isinstance(grid_data, dict):
                    active_grid[level] = {
                    k: json.loads(v) if isinstance(v, str) else v
                    for k, v in grid_data.items()
                }
                elif isinstance(grid_data, list):  # 만약 Redis가 리스트로 반환한다면
                    active_grid[level] = {
                        k: json.loads(v) if isinstance(v, str) else v
                        for k, v in zip(grid_data[::2], grid_data[1::2])
                    }
                else:
                    print(f"Warning: Unexpected data type for level {level}")
            except json.JSONDecodeError:
                print(f"Warning: Invalid JSON data for level {level}")
            # 오류가 있는 데이터는 건너뛰거나, 기본값으로 처리할 수 있습니다.

    return active_grid

# 그리드 정보를 가져오는 함수 <-- 아래가 이전버젼인데, 새로운 버젼으로 먼저 시도.
#async def get_active_grid(
#    redis: Redis,
#    exchange_name: str,
#    user_id: int,
#    symbol_name: str
#) -> Dict[int, Dict[str, Any]]:
#    base_key = f"{exchange_name}:user:{user_id}:symbol:{symbol_name}"
#    active_grid_key = f"{base_key}:active_grid"
#    
#    active_grid = {}
#    for grid_level in range(21):
#        grid_key = f"{active_grid_key}:{grid_level}"
#        grid_info = await redis.hgetall(grid_key)
#        if grid_info:
#            active_grid[grid_level] = {
#                field: json.loads(value.decode()) if value else None
#                for field, value in grid_info.items()
#            }
#    
#    return active_grid

async def get_order_placed(redis: Redis, exchange_name: str, user_id: int, symbol_name: str, level: int) -> bool:
    key = f"orders:{exchange_name}:user:{user_id}:symbol:{symbol_name}:order_placed"
    value = await redis.hget(key, str(level))
    return value == "1"  # Redis returns str when decode_responses=True

async def set_order_placed(redis: Redis, exchange_name: str, user_id: int, symbol_name: str, level: int, status: bool) -> None:
    key = f"orders:{exchange_name}:user:{user_id}:symbol:{symbol_name}:order_placed"
    await redis.hset(key, str(level), 1 if status else 0)

# 특정 그리드 레벨의 정보를 업데이트하는 함수
async def update_grid_level(
    redis: Redis,
    exchange_name: str,
    user_id: int,
    symbol_name: str,
    grid_level: int,
    updated_info: Dict[str, Any]
) -> None:
    base_key = f"{exchange_name}:user:{user_id}:symbol:{symbol_name}"
    grid_key = f"{base_key}:active_grid:{grid_level}"
    
    async with redis.pipeline(transaction=True) as pipe:
        for field, value in updated_info.items():
            if value is not None:
                await pipe.hset(grid_key, field, json.dumps(value))
            else:
                await pipe.hset(grid_key, field, "")
        await pipe.execute()

async def update_active_grid(
    redis: Redis,
    exchange_name: str,
    user_id: int,
    symbol_name: str,
    grid_level: int,
    entry_price: Optional[float] = None,
    position_size: Optional[float] = None,
    execution_time: Optional[datetime] = None,
    grid_count: Optional[int] = None,
    pnl: Optional[float] = None
) -> dict[str, Any]:
    base_key = f"{exchange_name}:user:{user_id}:symbol:{symbol_name}"
    grid_key = f"{base_key}:active_grid:{grid_level}"

    # 현재 그리드 정보 가져오기
    current_grid_info = await redis.hgetall(grid_key)

    # 기존 데이터를 파싱하거나 새로운 데이터 초기화
    if current_grid_info:
        grid_data: dict[str, Any] = {}
        for field, value in current_grid_info.items():
            try:
                # value가 문자열이든 바이트든 처리할 수 있도록 함
                if isinstance(value, bytes):
                    value = value.decode()
                grid_data[field] = json.loads(value) if value else None
            except json.JSONDecodeError:
                print(f"Failed to decode JSON for field {field}: {value}")
                grid_data[field] = value  # JSON 디코딩에 실패하면 원래 값을 사용
    else:
        grid_data = {
            'entry_price': 0.0,
            'position_size': 0.0,
            'grid_count': 0,
            'pnl': 0.0,
            'execution_time': None
        }


    # 데이터 업데이트
    if entry_price is not None:
        grid_data['entry_price'] = entry_price
    if position_size is not None:
        grid_data['position_size'] = position_size
    if pnl is not None:
        current_pnl = grid_data.get('pnl', 0.0)
        grid_data['pnl'] = (current_pnl or 0.0) + pnl
    if grid_count is not None:
        current_count = grid_data.get('grid_count', 0)
        grid_data['grid_count'] = (current_count or 0) + grid_count
    if execution_time:
        grid_data['execution_time'] = execution_time.isoformat()

    # 업데이트된 데이터 저장
    update_dict: dict[str, str] = {}
    for field, value in grid_data.items():
        if value is not None:
            try:
                update_dict[field] = json.dumps(value)
            except (TypeError, ValueError) as e:
                print(f"Error encoding {field}: {e}")
                update_dict[field] = str(value)  # 인코딩 실패 시 문자열로 저장

    # Use hset with mapping instead of deprecated hmset
    async with redis.pipeline(transaction=True) as pipe:
        await pipe.hset(grid_key, mapping=cast(Mapping[str | bytes, bytes | float | int | str], update_dict))
        await pipe.execute()

    return grid_data

async def get_full_active_grid(
    redis: Redis,
    exchange_name: str,
    user_id: int,
    symbol_name: str
) -> dict[int, dict[str, Any]]:
    base_key = f"{exchange_name}:user:{user_id}:symbol:{symbol_name}"
    active_grid: dict[int, dict[str, Any]] = {}

    for grid_level in range(21):  # 0부터 20까지
        grid_key = f"{base_key}:active_grid:{grid_level}"
        grid_info = await redis.hgetall(grid_key)
        if grid_info:
            active_grid[grid_level] = {
                field: json.loads(value.decode()) if value else None
                for field, value in grid_info.items()
            }

    return active_grid

async def upload_order_placed(
    redis: Redis,
    exchange_name: str,
    user_id: int,
    symbol: str,
    order_placed: dict[str, bool]
) -> None:
    order_placed_key = f'orders:{exchange_name}:user:{user_id}:symbol:{symbol}:order_placed'

    # order_placed의 불리언 값을 정수로 변환
    redis_order_placed = {k: int(v) for k, v in order_placed.items()}

    # Use hset with mapping instead of deprecated hmset
    await redis.hset(order_placed_key, mapping=cast(Mapping[str | bytes, bytes | float | int | str], redis_order_placed))

async def update_take_profit_orders_info(
    redis: Redis,
    exchange_name: str,
    user_id: int,
    symbol_name: str,
    level: int,
    order_id: str | None = None,
    new_price: float | None = None,
    quantity: float = 0.0,
    active: bool = False,
    side: str | None = None
) -> dict[str, Any]:
    # Redis에서 현재 take_profit_orders_info 가져오기
    symbol_key = f"{exchange_name}:user:{user_id}:symbol:{symbol_name}"
    level_str = str(level)
    if active:
        print(f"{symbol_key} : {level_str}, {order_id}, {new_price}, {quantity}, {active}, {side}")
    take_profit_orders_info_json = await redis.hget(symbol_key, 'take_profit_orders_info')
    take_profit_orders_info: dict[str, Any] = json.loads(take_profit_orders_info_json) if take_profit_orders_info_json else {}

    # 해당 레벨의 정보 업데이트
    if level_str in take_profit_orders_info:
        take_profit_orders_info[level_str].update({
            'order_id': order_id,
            'target_price': new_price,
            'quantity': quantity,
            'active': active,
            'side': side
        })
    else:
        take_profit_orders_info[level_str] = {
            'order_id': order_id,
            'target_price': new_price,
            'quantity': quantity,
            'active': active,
            'side': None  # 또는 'sell', 상황에 따라 적절히 설정
        }
    if active:
        print(f"{symbol_name}에 대해 {level_str} 레벨의 take_profit_orders_info 업데이트됨: active : {active}")

    # 업데이트된 정보를 Redis에 저장
    await redis.hset(symbol_key, 'take_profit_orders_info', json.dumps(take_profit_orders_info))

    return take_profit_orders_info

#async def update_take_profit_order_info(redis ,exchange_name: str, user_id: int, symbol_name: str, level: int, order_id: str, new_price: float, quantity: float, active: bool, side : str= None):
#    key = f"{exchange_name}:user:{user_id}:symbol:{symbol_name}"
#
#    # 기존 데이터 가져오기
#    data = await redis.hgetall(key)
#    if data:
#                # 데이터 타입에 따라 적절히 처리
#        symbol_data = {}
#        for k, v in data.items():
#            if isinstance(k, bytes):
#                k = k.decode('utf-8')
#            if isinstance(v, bytes):
#                v = v.decode('utf-8')
#            symbol_data[k] = v
#
#        if 'take_profit_orders_info' in symbol_data:
#            symbol_data['take_profit_orders_info'] = json.loads(symbol_data['take_profit_orders_info'])
#    else:
#        symbol_data = {"take_profit_orders_info": {}}
#    
#    if int(level) not in symbol_data["take_profit_orders_info"]:
#        symbol_data["take_profit_orders_info"][int(level)] = {}
#
#    symbol_data["take_profit_orders_info"][int(level)].update({
#        "order_id": order_id,
#        "target_price": new_price,
#        "quantity": quantity,
#        "active": active,
#        "side": side
#    })
#
#    # 업데이트된 데이터 저장
#    symbol_data['take_profit_orders_info'] = json.dumps(symbol_data['take_profit_orders_info'])
#    await redis.hset(key, mapping=symbol_data)
#    #print(f"Updated take profit order info for user {user_id}, symbol {symbol_name}, level {level}, active: {active}, side: {side}")



#================================================================================================
# SAVE
#================================================================================================

async def save_user_key(exchange_name: str, user_id: int | str, field: str, value: Any) -> None:
    key = f"{exchange_name}:user:{user_id}"
    redis = await get_redis_connection()

    try:
        if isinstance(value, (dict, list, set)):
            value_str = json.dumps(value)
        elif isinstance(value, bool):
            value_str = str(int(value))
        else:
            value_str = str(value)

        await redis.hset(key, field, value_str)
        print(f"Saved {field} for user {user_id} in {exchange_name}")

        # 캐시 무효화
        user_key_cache.cache.pop(f"{exchange_name}:{user_id}", None)
    except RedisError as e:
        print(f"Error saving to Redis: {e}")

async def save_job_id(exchange_name: str, user_id: int, job_id: str) -> None:
    redis = await get_redis_connection()
    try:
        start_time = datetime.now().isoformat()
        job_key = f'{exchange_name}:job:{user_id}'
        job_data = {
            'job_id': job_id,
            'status': 'running',
            'start_time': start_time
        }
        await redis.hset(job_key, mapping={k: str(v) for k, v in job_data.items()})
        print(f"Job ID saved for user {user_id} in {exchange_name}: {job_id}")
    except Exception as e:
        print(f"Error saving job ID: {e}")
    finally:
        await redis.close()

async def get_job_id(exchange_name: str, user_id: int) -> str | None:
    redis = await get_redis_connection()
    try:
        job_key = f'{exchange_name}:job:{user_id}'
        job_id = await redis.hget(job_key, 'job_id')
        return job_id if job_id else None
    finally:
        await redis.close()

async def update_job_status(exchange_name: str, user_id: int, status: str, job_id: str | None = None) -> None:
    redis = None
    try:
        redis = await get_redis_connection()
        job_key = f'{exchange_name}:job:{user_id}'
        user_key = f'{exchange_name}:user:{user_id}'

        # Get existing job data (decode_responses=True returns str, not bytes)
        existing_job = await redis.hgetall(job_key)
        
        current_time = datetime.now().isoformat()

        if existing_job:
            print(f"Existing job found: {existing_job}")
            if job_id is None:
                job_id = existing_job.get('job_id')
            start_time = existing_job.get('start_time', current_time)
        else:
            print("No existing job found, creating new job")
            if job_id is None:
                raise ValueError("job_id cannot be None for new job creation")
            start_time = current_time

        job_data = {
            'job_id': job_id,
            'status': status,
            'start_time': start_time
        }

        await asyncio.wait_for(redis.hset(job_key, mapping={k: str(v) for k, v in job_data.items()}), timeout=7.0)


        # Update user's running status
        await redis.hset(user_key, 'is_running', '1' if status == 'running' else '0')

        print(f"Job status updated successfully: user_id={user_id}, job_id={job_id}, status={status}")

    except Exception as e:
        print(f"Error updating job status: {e}")
        raise
    finally:
        if redis:
            await redis.close()
        
        
        
####TODO : 아래 구조와 위의 구조 두 개가 동시에 있었다. 일단 이건 가려놓았으니, 위걸로 확인.,
#async def update_job_status(exchange_name: str, user_id: int, status: str, job_id: str = None):
#    redis = await get_redis_connection()
#    try:
#        job_key = f'{exchange_name}:job:{user_id}'
#        user_key = f'{exchange_name}:user:{user_id}'
#        
#        # Get existing job data
#        existing_job = await redis.hgetall(job_key)
#        existing_job = {k.decode(): v.decode() for k, v in existing_job.items()}
#        
#        current_time = datetime.now().isoformat()
#        
#        if existing_job:
#            print(f"Existing job found: {existing_job}")
#            if job_id is None:
#                job_id = existing_job.get('job_id')
#            start_time = existing_job.get('start_time', current_time)
#        else:
#            print("No existing job found, creating new job")
#            if job_id is None:
#                raise ValueError("job_id cannot be None for new job creation")
#            start_time = current_time
#        
#        # Update job data
#        job_data = {
#            'job_id': job_id,
#            'status': status,
#            'start_time': start_time
#        }
#        
#        # Use hset instead of hmset_dict
#        for key, value in job_data.items():
#            await redis.hset(job_key, key, value)
#        
#        # Update user's running status
#        await redis.hset(user_key, 'is_running', '1' if status == 'running' else '0')
#        
#        print(f"Job status updated successfully: user_id={user_id}, job_id={job_id}, status={status}")
#    except Exception as e:
#        print(f"Error updating job status: {e}")
#        raise
#    finally:
#        await redis.close()




async def update_telegram_id(exchange_name: str, user_id: int, telegram_id: str) -> None:
    redis = await get_redis_connection()
    try:
        user_key = f'{exchange_name}:user:{user_id}'
        await redis.hset(user_key, 'telegram_id', telegram_id)
        print(f"Telegram ID updated for user {user_id} in Redis for {exchange_name}.")
    except Exception as e:
        print(f"Error updating Telegram ID for user {user_id} in Redis for {exchange_name}: {e}")
    finally:
        await redis.close()

# This function replaces the original get_db_name function
async def get_exchange_prefix(exchange_name: str) -> str:
    exchange_prefixes = {
        'binance': 'binance',
        'binance_spot': 'binance_spot',
        'okx': 'okx',
        'okx_spot': 'okx_spot',
        'bitget': 'bitget',
        'bitget_spot': 'bitget_spot',
        'upbit': 'upbit',
        'bybit': 'bybit',
        'bybit_spot': 'bybit_spot'
    }
    return exchange_prefixes.get(exchange_name, exchange_name)

async def get_user(exchange_name: str, user_id: int) -> dict[str, str]:
    redis = await get_redis_connection()

    try:
        user_key = f'{exchange_name}:user:{user_id}'
        user_data = await redis.hgetall(user_key)
        # Redis with decode_responses=True returns str, not bytes
        return user_data
    finally:
        await redis.close()

async def add_to_blacklist(exchange_name: str, user_id: int, symbol: str) -> None:
    redis = await get_redis_connection()

    try:
        blacklist_key = f'{exchange_name}:blacklist:{user_id}'
        await redis.sadd(blacklist_key, symbol)
    finally:
        await redis.close()

async def add_to_whitelist(exchange_name: str, user_id: int, symbol: str) -> None:
    redis = await get_redis_connection()

    try:
        whitelist_key = f'{exchange_name}:whitelist:{user_id}'
        await redis.sadd(whitelist_key, symbol)
    finally:
        await redis.close()

async def set_telegram_id(exchange_name: str, user_id: int, telegram_id: str) -> None:
    redis = await get_redis_connection()

    try:
        telegram_key = f'{exchange_name}:telegram_ids'
        await redis.hset(telegram_key, str(user_id), telegram_id)
    finally:
        await redis.close()

async def get_running_user_ids(exchange_name: str) -> list[str]:
    redis = await get_redis_connection()

    try:
        running_user_ids: list[str] = []
        user_ids = await redis.smembers(f'{exchange_name}:user_ids')

        # Redis with decode_responses=True returns str, not bytes
        for user_id in user_ids:
            user_key = f'{exchange_name}:user:{user_id}'
            is_running = await redis.hget(user_key, 'is_running')
            if is_running == '1':
                running_user_ids.append(user_id)

        return running_user_ids
    finally:
        await redis.close()
        
        




async def update_user_info(user_id: int, exchange_name: str, running_status: bool, **user_data: Any) -> dict[str, str]:
    redis = None
    try:
        redis = await _redis_manager.get_connection_async(decode_responses=True)
        user_key = f'{exchange_name}:user:{user_id}'

        # Prepare user data
        update_data = {
            'is_running': '1' if running_status else '0',
            **{k: json.dumps(v) if isinstance(v, (dict, list, set)) else str(v) for k, v in user_data.items()}
        }

        # Update user info in Redis
        await redis.hset(user_key, mapping=cast(Mapping[str | bytes, bytes | float | int | str], update_data))
        #print(f"User info updated for user {user_id} in {exchange_name}")

        # Retrieve and print saved info
        saved_info = await redis.hgetall(user_key)
        #print(f"Saved info for user {user_id}: {saved_info}")

        return saved_info
    except Exception as e:
        print(f"Error updating user info: {e}")
        raise

async def update_user_running_status(exchange_name: str, user_id: int, is_running: bool, redis: Redis | None = None) -> None:
    redis_close_flag = False
    try:
        if redis is None:
            redis = await get_redis()
            redis_close_flag = True

        user_key = f'{exchange_name}:user:{user_id}'
        job_key = f'{exchange_name}:job:{user_id}'
        time = datetime.now().isoformat()
        print(f"Updating user status: exchange={exchange_name}, user_id={user_id}, is_running={is_running}")

        # Check for existing job
        job_id = await redis.hget(job_key, 'job_id')
        #if job_id:
        #    print(f"Found existing job_id: {job_id}")
        #else:
        #    print("No existing job_id found")

        # Update user running status
        await redis.hset(user_key, 'is_running', '1' if is_running else '0')
        status = 'running' if is_running else 'stopped'

        if is_running:
            if job_id:
                await redis.hset(job_key, mapping={'status': status, 'start_time': time})
            else:
                print("Warning: Attempting to set status to running but no job_id found")
        else:
            if job_id:
                await redis.delete(job_key)

        print(f"User running status updated for {user_id} in {exchange_name}: {is_running}, job_id: {job_id}")
    except Exception as e:
        print(f"Error updating user running status: {e}")
        raise
    finally:
        if redis_close_flag and redis:
            # RedisConnectionManager가 연결 풀을 관리하므로 명시적으로 닫지 않음
            pass


async def reset_user_data(user_id: int, exchange_name: str) -> None:
    redis = await get_redis_connection()
    try:
        user_key = f'{exchange_name}:user:{user_id}'
        korea_tz = ZoneInfo("Asia/Seoul")
        current_time = datetime.now(korea_tz).isoformat()

        # Fetch current user data
        current_data = await redis.hgetall(user_key)

        # Update specific fields
        current_data['is_running'] = '0'  # False
        current_data['tasks'] = '[]'  # Empty list
        current_data['is_stopped'] = '1'  # True
        current_data['running_symbols'] = '[]'  # Empty list
        current_data['completed_symbols'] = '[]'  # Empty list
        current_data['last_updated_time'] = current_time  # 마지막 리셋 시간 추가

        # Save updated data back to Redis
        await redis.hset(user_key, mapping=cast(Mapping[str | bytes, bytes | float | int | str], current_data))

        ## Update local cache
        #cached_data = user_key_cache.get(exchange_name, user_id) or {}
        #cached_data.update({
        #    'is_running': False,
        #    'tasks': [],
        #    'running_symbols': set(),
        #    'completed_symbols': set()
        #})
        #user_key_cache.set(exchange_name, user_id, cached_data)

        print(f"User data reset for user {user_id} in {exchange_name}")
    except RedisError as e:
        print(f"Error resetting user data: {e}")
        #raise e


            
async def save_user(
    user_id: int,
    api_key: str | None = None,
    api_secret: str | None = None,
    password: str | None = None,
    initial_capital: dict[str, float] | None = None,
    direction: str | None = None,
    numbers_to_entry: int | None = None,
    leverage: int | None = None,
    is_running: bool | None = None,
    stop_loss: float | None = None,
    tasks: list[str] | None = None,
    running_symbols: set[str] | None = None,
    grid_num: int | None = None,
    stop_task_only: bool | None = None,
    exchange_name: str = 'okx'
) -> None:
    redis = await get_redis_connection()
    korea_tz = ZoneInfo("Asia/Seoul")
    current_time = datetime.now(korea_tz).isoformat()
    try:
        user_key = f'{exchange_name}:user:{user_id}'
        user_key_key = f'{exchange_name}:user:{user_id}:key'
        user_data = {
            'api_key': api_key,
            'api_secret': api_secret,
            'password': password,
            'initial_capital': json.dumps(initial_capital) if initial_capital is not None else None,
            'direction': direction,
            'numbers_to_entry': str(numbers_to_entry) if numbers_to_entry is not None else None,
            'leverage': str(leverage) if leverage is not None else None,
            'is_running': '1' if is_running else '0',
            'stop_loss': str(stop_loss) if stop_loss is not None else None,
            'tasks': json.dumps(tasks) if tasks is not None else '[]',
            'running_symbols': json.dumps(list(running_symbols)) if running_symbols is not None else '[]',
            'grid_num': str(grid_num) if grid_num is not None else None,
            'stop_task_only': '1' if stop_task_only else '0',
            'last_updated_time': current_time
        }
        # Remove None values
        user_data = {k: v for k, v in user_data.items() if v is not None}
        
        # Save to Redis
        await redis.hset(user_key, mapping=cast(Mapping[str | bytes, bytes | float | int | str], user_data))
        await redis.hset(user_key_key, mapping=cast(Mapping[str | bytes, bytes | float | int | str], user_data))
        
        # Update local cache
        cached_data = user_key_cache.get(exchange_name, user_id) or {}
        cached_data.update(user_data)
        cached_data['user_id'] = user_id
        cached_data['is_running'] = bool(is_running)
        cached_data['running_symbols'] = set(running_symbols) if running_symbols is not None else set()
        cached_data['initial_capital'] = initial_capital
        cached_data['tasks'] = tasks or []
        
        user_key_cache.set(exchange_name, user_id, cached_data)
        
        print(f"User data saved for user {user_id} in {exchange_name}")
    except RedisError as e:
        print(f"Error saving user data: {e}")
        raise
    finally:
        await redis.close()      
        
async def remove_tasks(user_id: int, task: str, exchange_name: str) -> None:
    redis = await get_redis_connection()
    try:
        user_key = f'{exchange_name}:user:{user_id}'
        tasks_json = await redis.hget(user_key, 'tasks')

        if tasks_json is None:
            tasks: list[str] = []
        else:
            tasks = json.loads(tasks_json)

        if task in tasks:
            tasks.remove(task)
            await redis.hset(user_key, 'tasks', json.dumps(tasks))
            print(f"Task removed for user {user_id} in Redis for {exchange_name}.")
        else:
            print(f"Task {task} not found for user {user_id} in Redis for {exchange_name}.")
    except Exception as e:
        print(f"Error removing task for user {user_id} in Redis for {exchange_name}: {e}")
    finally:
        await redis.close()

async def add_tasks(user_id: int, task: str, exchange_name: str) -> None:
    redis = await get_redis_connection()
    try:
        user_key = f'{exchange_name}:user:{user_id}'
        tasks_json = await redis.hget(user_key, 'tasks')

        if tasks_json is None:
            tasks: list[str] = []
        else:
            tasks = json.loads(tasks_json)

        tasks.append(task)
        await redis.hset(user_key, 'tasks', json.dumps(tasks))
        print(f"Task added for user {user_id} in Redis for {exchange_name}.")
    except Exception as e:
        print(f"Error adding task for user {user_id} in Redis for {exchange_name}: {e}")
    finally:
        await redis.close()

async def add_running_symbol(user_id: int, new_symbols: str | list[str] | set[str], exchange_name: str) -> None:
    redis = await get_redis_connection()
    try:
        user_key = f'{exchange_name}:user:{user_id}'
        running_symbols_json = await redis.hget(user_key, 'running_symbols')

        if running_symbols_json is None:
            running_symbols: set[str] = set()
        else:
            running_symbols = set(json.loads(running_symbols_json))

        if isinstance(new_symbols, (list, set)):
            running_symbols.update(new_symbols)
        else:
            running_symbols.add(new_symbols)

        await redis.hset(user_key, 'running_symbols', json.dumps(list(running_symbols)))
        print(f"Running symbols updated for user {user_id} in Redis for {exchange_name}.")
    except Exception as e:
        print(f"Error updating running symbols for user {user_id} in Redis for {exchange_name}: {e}")
    finally:
        await redis.close()

async def remove_running_symbol(user_id: int, symbol_to_remove: str, exchange_name: str, redis: Redis | None = None) -> None:
    redis_flag = False
    if redis is None:
        redis = await get_redis_connection()
        redis_flag = True
    try:
        user_key = f'{exchange_name}:user:{user_id}'
        running_symbols_json = await redis.hget(user_key, 'running_symbols')

        if running_symbols_json is None:
            running_symbols_set: set[str] = set()
        else:
            running_symbols_set = set(json.loads(running_symbols_json))

        if symbol_to_remove in running_symbols_set:
            running_symbols_set.remove(symbol_to_remove)

        await redis.hset(user_key, 'running_symbols', json.dumps(list(running_symbols_set)))
        print(f"Symbol {symbol_to_remove} removed for user {user_id} in Redis for {exchange_name}.")
    except Exception as e:
        print(f"Error removing symbol {symbol_to_remove} for user {user_id} in Redis for {exchange_name}: {e}")
    finally:
        if redis_flag:
            await redis.close()
            
async def save_running_symbols(exchange_name: str, user_id: int) -> None:
    redis = await get_redis_connection()
    try:
        # 기존 키에서 running_symbols 정보 가져오기
        user_key = f'{exchange_name}:user:{user_id}'
        running_symbols_json = await redis.hget(user_key, 'running_symbols')

        if running_symbols_json is not None:
            running_symbols = json.loads(running_symbols_json)

            # 새로운 키 형식으로 저장
            new_key = f'running_symbols:{exchange_name}:{user_id}'
            await redis.set(new_key, json.dumps(running_symbols))

            print(f"Running symbols saved for user {user_id} in Redis under key {new_key}")
        else:
            print(f"No running symbols found for user {user_id} in Redis for {exchange_name}")

    except Exception as e:
        print(f"Error saving running symbols for user {user_id} in Redis for {exchange_name}: {e}")

    finally:
        await redis.close()
        #================================================================================================
# GET
#================================================================================================
@lru_cache(maxsize=100)
async def get_user_key(exchange_name: str, user_id: str | int) -> dict[str, Any] | None:
    cached_data = user_key_cache.get(exchange_name, user_id)
    if cached_data:
        # Cast to proper type since cache can contain Any
        return cast(dict[str, Any], cached_data)

    key = f"{exchange_name}:user:{user_id}"
    redis = await get_redis_connection()

    try:
        # Redis with decode_responses=True returns dict[str, str], no encoding param needed
        user_data = await redis.hgetall(key)
        if not user_data:
            return None

        processed_user_data: dict[str, Any] = {
            "user_id": user_id,
            "api_key": user_data.get('api_key'),
            "api_secret": user_data.get('api_secret'),
            "password": user_data.get('password'),
            "initial_capital": json.loads(user_data.get('initial_capital', '{}')),
            "direction": user_data.get('direction'),
            "numbers_to_entry": float(user_data.get('numbers_to_entry', 0)),
            "leverage": float(user_data.get('leverage', 1)),
            "is_running": parse_bool(user_data.get('is_running', '0')),
            "stop_loss": float(user_data.get('stop_loss', 0)),
            "tasks": json.loads(user_data.get('tasks', '[]')),
            "running_symbols": set(json.loads(user_data.get('running_symbols', '[]'))),
            "grid_num": int(user_data.get('grid_num', 0))
        }

        user_key_cache.set(exchange_name, user_id, processed_user_data)
        return processed_user_data
    except RedisError as e:
        print(f"Error getting from Redis: {e}")
        return None

async def get_all_user_keys(exchange_name: str) -> Dict[str, Any]:
    logging.info(f"Getting all user keys for exchange: {exchange_name}")
    redis = await get_redis_connection()
    user_keys = {}

    try:
        all_users = await redis.keys(f"{exchange_name}:user:*", encoding='utf-8')
        
        for user_key in all_users:
            try:
                user_id = user_key.split(':')[-1]
                user_data = await get_user_key(exchange_name, user_id)
                if user_data:
                    user_keys[user_id] = user_data
            except Exception as e:
                logging.error(f"Error processing user key {user_key}: {e}")
                continue  # 개별 사용자 처리 실패 시 다음 사용자로 진행

    except RedisError as e:
        logging.error(f"Redis error while getting user keys: {e}")
    except Exception as e:
        logging.error(f"Unexpected error in get_all_user_keys: {e}")
    finally:
        try:
            await redis.close()
        except Exception as e:
            logging.error(f"Error closing Redis connection: {e}")

    logging.info(f"Retrieved {len(user_keys)} user keys for {exchange_name}")
    return user_keys
    

async def get_position_size(exchange_name: str, user_id: int, symbol: str) -> float:
    redis = await get_redis_connection()

    # Try new Hash pattern first (Phase 2)
    index_key = f'positions:index:{user_id}:{exchange_name}'
    position_keys = await redis.smembers(index_key)

    if position_keys:
        # New Hash pattern: check for this specific symbol
        total_pos = 0.0

        for pos_key in position_keys:
            # pos_key format: "{symbol}:{side}"
            try:
                pos_symbol, side = pos_key.split(':')
                if pos_symbol == symbol:
                    position_key = f'positions:{user_id}:{exchange_name}:{symbol}:{side}'
                    position = await redis.hgetall(position_key)
                    if position:
                        pos = float(position.get('pos', 0))
                        # Sum both long and short positions for the symbol
                        total_pos += pos
            except (ValueError, KeyError) as e:
                print(f"Error processing position key {pos_key}: {e}")
                continue

        return total_pos

    # Fallback to legacy JSON array pattern
    position_key = f'{exchange_name}:positions:{user_id}'
    position_data = await redis.get(position_key)

    if position_data is None:
        return 0.0  # 포지션 정보가 없으면 0 반환

    try:
        positions = json.loads(position_data)
        if isinstance(positions, list):
            for position in positions:
                if isinstance(position, dict) and position.get('instId') == symbol:
                    return float(position.get('pos', 0))
        elif isinstance(positions, dict):
            position = positions.get(symbol)
            if position:
                return float(position.get('pos', 0))
        return 0.0  # 해당 심볼에 대한 포지션이 없으면 0 반환
    except (json.JSONDecodeError, ValueError, AttributeError) as e:
        print(f"Error processing position data: {e}")
        return 0.0  # 데이터 파싱 오류 시 0 반환



async def set_trading_volume(exchange_name: str, user_id: int, symbol: str, volume: float) -> float:
    try:
        redis = await get_redis_connection()
        korean_time = datetime.now(ZoneInfo("Asia/Seoul"))
        today = korean_time.strftime('%Y-%m-%d')

        # 사용자별 심볼 거래량 누적
        user_symbol_key = f'{exchange_name}:user:{user_id}:symbol:{symbol}'
        current_volume = float(await redis.zscore(user_symbol_key, today) or 0)
        new_volume = current_volume + volume
        await redis.zadd(user_symbol_key, {today: new_volume})

        # 전체 심볼 거래량 누적
        total_symbol_key = f'{exchange_name}:symbol:{symbol}'
        current_total_volume = float(await redis.zscore(total_symbol_key, today) or 0)
        new_total_volume = current_total_volume + volume
        await redis.zadd(total_symbol_key, {today: new_total_volume})

        return new_volume
    except RedisError as e:
        raise HTTPException(status_code=500, detail=f"Redis 오류: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"알 수 없는 오류: {str(e)}")


async def set_trading_pnl(exchange_name: str, user_id: int, symbol: str, pnl: float) -> float:
    try:
        redis = await get_redis_connection()
        korean_time = datetime.now(ZoneInfo("Asia/Seoul"))
        today = korean_time.strftime('%Y-%m-%d')

        # 사용자별 심볼 PnL 누적
        user_symbol_key = f'{exchange_name}:user:{user_id}:pnl:{symbol}'
        current_pnl = float(await redis.zscore(user_symbol_key, today) or 0)
        new_pnl = current_pnl + pnl
        await redis.zadd(user_symbol_key, {today: new_pnl})

        # 전체 심볼 PnL 누적
        total_symbol_key = f'{exchange_name}:pnl:{symbol}'
        current_total_pnl = float(await redis.zscore(total_symbol_key, today) or 0)
        new_total_pnl = current_total_pnl + pnl
        await redis.zadd(total_symbol_key, {today: new_total_pnl})

        return new_pnl
    except RedisError as e:
        raise HTTPException(status_code=500, detail=f"Redis 오류: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"알 수 없는 오류: {str(e)}")


async def get_total_grid_count(redis: Redis, exchange_name: str, user_id: int, symbol_name: str) -> int:
    base_key = f"{exchange_name}:user:{user_id}:symbol:{symbol_name}"
    total_grid_count = 0
    position_size = await get_position_size(exchange_name, user_id, symbol_name)
    # 0부터 20까지의 그리드 레벨에 대해 반복 (필요에 따라 범위 조정)
    if position_size is None or position_size == 0.0:
        #print(f"{user_id} : {symbol_name} : position_size is None. Therefore, reset grid count")
        for level in range(21):
            
            grid_level = f"{base_key}:active_grid:{level}"
            await redis.hset(grid_level, "grid_count", 0)
        total_grid_count = 0
        return total_grid_count
    else:
        for level in range(21):    
            grid_key = f"{base_key}:active_grid:{level}"
            grid_count = await redis.hget(grid_key, "grid_count")
            if grid_count:
                total_grid_count += int(grid_count)
    

    return total_grid_count
        

async def get_telegram_id(exchange_name: str, user_id: int) -> str | None:
    redis = await get_redis_connection()
    try:
        user_key = f'{exchange_name}:user:{user_id}'
        telegram_id = await redis.hget(user_key, 'telegram_id')
        return telegram_id if telegram_id else None
    except Exception as e:
        print(f"Error getting Telegram ID: {e}")
        return None
    finally:
        await redis.close()

async def get_job_status(exchange_name: str, user_id: int, redis: Redis | None = None) -> tuple[str, str] | None:
    redis = await get_redis_connection()
    try:
        job_key = f'{exchange_name}:job:{user_id}'
        job_info = await redis.hmget(job_key, 'status', 'job_id')

        # Redis with decode_responses=True returns str, not bytes
        if job_info[0] and job_info[1]:
            status = job_info[0]
            job_id = job_info[1]
            return status, job_id
        else:
            return None

    except Exception as e:
        print(f"Error getting job status: {e}")
        return None
    finally:
        await redis.close()


async def get_user_info(exchange_name: str, user_id: int) -> dict[str, str]:
    redis = await get_redis_connection()
    try:
        user_key = f'{exchange_name}:user:{user_id}'
        user_info = await redis.hgetall(user_key)
        # Redis with decode_responses=True returns dict[str, str] directly
        return user_info
    except Exception as e:
        print(f"Error in get_user_info for user {user_id} on {exchange_name}: {e}")
        print(traceback.format_exc())
        return {}
    finally:
        await redis.close() 

async def get_user_data(exchange_name: str, user_id: str) -> Dict[str, Any]:
    redis = await get_redis_connection()
    try:
        user_key = f'{exchange_name}:user:{user_id}'
        user_data = await redis.hgetall(user_key)

        if not user_data:
            print(f"Warning: No data found for user {user_id} on {exchange_name}")
            return {}

        # Redis with decode_responses=True returns dict[str, str] directly
        print(f"Debug: Retrieved data for user {user_id} on {exchange_name}: {user_data.keys()}")
        return user_data

    except Exception as e:
        print(f"Error in get_user_data for user {user_id} on {exchange_name}: {e}")
        print(traceback.format_exc())
        return {}
    finally:
        await redis.close()
        
async def set_user_data(exchange_name: str, user_id: int, data: Dict[str, Any], field: str | None = None) -> None:
    redis = await get_redis_connection()
    user_key = f"{exchange_name}:user:{user_id}"

    json_fields = ["tasks", "running_symbols", "completed_trading_symbols", "enter_symbol_amount_list"]
    boolean_fields = ["is_running", "stop_task_only"]
    numeric_fields = ["leverage", "initial_capital"]

    def serialize_value(key: str, value: Any) -> str:
        if key in json_fields:
            return json.dumps(value)
        elif key in boolean_fields:
            return str(value).lower()
        elif key in numeric_fields:
            return str(float(value))
        else:
            return str(value)

    if field:
        value = serialize_value(field, data)
        await redis.hset(user_key, field, value)
    else:
        serialized_data = {key: serialize_value(key, value) for key, value in data.items()}
        # Use hset with mapping instead of deprecated hmset
        await redis.hset(user_key, mapping=cast(Mapping[str | bytes, bytes | float | int | str], serialized_data))
        
async def get_all_running_user_ids() -> List[str]:
    redis = await get_redis_connection()
    all_running_user_ids = []
    exchanges = ['binance', 'upbit', 'bitget', 'binance_spot', 'bitget_spot', 'okx', 'okx_spot', 'bybit', 'bybit_spot']
    
    try:
        for exchange_name in exchanges:
            user_pattern = f'{exchange_name}:user:*'
            try:
                user_keys = await redis.keys(user_pattern)
                for user_key in user_keys:
                    try:
                        # 먼저 decode()를 시도하고, 실패하면 문자열로 처리
                        
                        user_id = user_key.split(':')[-1]

                        is_running = await redis.hget(user_key, 'is_running')
                        if is_running in [b'1', '1']:  # 바이트 문자열과 일반 문자열 모두 처리
                            all_running_user_ids.append(user_id)
                    except Exception as e:
                        logging.error(f"Error processing user key {user_key} for exchange {exchange_name}: {e}")
                        continue  # 개별 사용자 처리 실패 시 다음 사용자로 진행
            except Exception as e:
                logging.error(f"Error processing exchange {exchange_name}: {e}")
                continue  # 개별 거래소 처리 실패 시 다음 거래소로 진행
        
        return all_running_user_ids
    except Exception as e:
        logging.error(f"Unexpected error in get_all_running_user_ids: {e}")
        return []
    finally:
        try:
            await redis.close()
        except Exception as e:
            logging.error(f"Error closing Redis connection: {e}")
        
# safe_float is now imported from shared.utils

async def get_user_keys(exchange_name: str) -> dict[str, dict[str, Any]]:
    #print(f"Getting user keys for exchange: {exchange_name}...")
    redis = await get_redis_connection()
    user_keys: dict[str, dict[str, Any]] = {}
    try:
        # Redis에서 해당 exchange의 모든 사용자 키 가져오기
        try:
            all_user_keys = await redis.keys(f'{exchange_name}:user:*')
        except Exception as e:
            print(f"Error getting user keys for {exchange_name}: {e}")
            print(traceback.format_exc())
        #print(f"Debug: all_user_keys type: {type(all_user_keys)}, content: {all_user_keys}")  # 디버그 출력
        
        for user_key in all_user_keys:
            try:
                # Redis with decode_responses=True returns str, not bytes
                user_id = user_key.split(':')[-1]

                #print(f"Debug: Processing user_key: {user_key}, user_id: {user_id}")  # 디버그 출력

                # 캐시에서 사용자 데이터 확인
                cached_data = user_key_cache.get(exchange_name, user_id)
                if cached_data:
                    user_keys[user_id] = cached_data
                    continue
                # 캐시에 없으면 Redis에서 가져오기
                try:
                    user_data = await redis.hgetall(user_key)
                except Exception as e:
                    print(f"Error getting user data for user_key: {user_key}: {e}")
                    print(traceback.format_exc())
                if not user_data:
                    print(f"Debug: No data found for user_key: {user_key}")  # 디버그 출력
                    continue

                # Redis with decode_responses=True returns dict[str, str] directly
                decoded_user_data = user_data
            
                processed_data = {
                    "user_id": user_id,
                    "api_key": decoded_user_data.get('api_key'),
                    "api_secret": decoded_user_data.get('api_secret'),
                    "password": decoded_user_data.get('password'),
                    "initial_capital": json.loads(decoded_user_data.get('initial_capital', '{}')),
                    "direction": decoded_user_data.get('direction'),
                    "numbers_to_entry": float(decoded_user_data.get('numbers_to_entry', 0)),
                    "leverage": float(decoded_user_data.get('leverage', 1)),
                    "is_running": parse_bool(decoded_user_data.get('is_running', '0')),
                    "stop_loss": safe_float(decoded_user_data.get('stop_loss')),
                    "tasks": json.loads(decoded_user_data.get('tasks', '[]')),
                    "running_symbols": set(json.loads(decoded_user_data.get('running_symbols', '[]'))),
                    "grid_num": int(decoded_user_data.get('grid_num', 0))
                }
                
               # 캐시 업데이트
                user_key_cache.set(exchange_name, user_id, processed_data)
                user_keys[user_id] = processed_data
            except Exception as e:
                print(f"Error processing user key {user_key}: {e}")
                print(traceback.format_exc())
        
        return user_keys
    except Exception as e:
        print(f"Error in get_user_keys: {e}")
        print(traceback.format_exc())
        return {}
    finally:
        await redis.close()

#================================================================================================
# CLOSE
#================================================================================================
# 캐시 무효화 함수
def invalidate_cache(exchange_name: str, user_id: int | str) -> None:
    key = f"{exchange_name}:{user_id}"
    user_key_cache.cache.pop(key, None)
    get_user_key.cache_clear()  # lru_cache 클리어

# Redis 연결 종료
async def close_redis() -> None:
    redis = await get_redis_connection()
    await redis.close()