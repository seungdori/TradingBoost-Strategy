"""
User Management Service Module

Handles user data initialization, validation, and management operations.
Extracted from grid_original.py for better maintainability.
"""

import asyncio
import json
import logging
import traceback
from typing import Any, Dict, Optional, Union

from GRID import telegram_message
from GRID.routes.logs_route import add_log_endpoint as add_user_log
from GRID.trading.shared_state import user_keys

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def get_redis_connection():
    """Get Redis connection from GRID.core.redis"""
    from GRID.core.redis import get_redis_connection as core_get_redis
    return await core_get_redis()


# ==================== User Data Management ====================

async def get_user_data(exchange_name: str, user_id: int, field: Optional[str] = None) -> Union[Dict[str, Any], Any]:
    """
    Get user data from Redis.

    Args:
        exchange_name: Exchange name
        user_id: User ID
        field: Optional specific field to retrieve

    Returns:
        User data dict or specific field value
    """
    redis = await get_redis_connection()
    user_key = f"{exchange_name}:user:{user_id}"

    json_fields = ["tasks", "running_symbols", "completed_trading_symbols", "enter_symbol_amount_list"]
    boolean_fields = ["is_running", "stop_task_only"]
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


async def initialize_user_data(redis, user_key):
    """
    Initialize user data in Redis if not exists.

    Args:
        redis: Redis connection
        user_key: Redis user key
    """
    if not await redis.exists(user_key):
        await redis.hset(user_key, mapping={
            'is_running': '0',
            'tasks': '[]',
            'running_symbols': '[]',
            'completed_trading_symbols': '[]',
            'stop_task_only': '0',
        })


async def get_user_data_from_redis(redis, user_key):
    """
    Get user data from Redis with byte decoding.

    Args:
        redis: Redis connection
        user_key: Redis user key

    Returns:
        Dict of user data
    """
    user_data = await redis.hgetall(user_key)
    return {k.decode('utf-8') if isinstance(k, bytes) else k:
            v.decode('utf-8') if isinstance(v, bytes) else v
            for k, v in user_data.items()}


async def update_user_data(exchange_name: str, user_id: int, **kwargs: Any) -> None:
    """
    Update user data in Redis.

    Args:
        exchange_name: Exchange name
        user_id: User ID
        **kwargs: Fields to update
    """
    redis = await get_redis_connection()
    user_key = f"{exchange_name}:user:{user_id}"

    for key, value in kwargs.items():
        if isinstance(value, (list, set, dict)):
            value = json.dumps(list(value) if isinstance(value, set) else value)
        elif isinstance(value, bool):
            value = str(value).lower()
        else:
            value = str(value)
        await redis.hset(user_key, key, value)


# ==================== User Keys Initialization ====================

def ensure_user_keys_initialized_old_struc(user_id, enter_symbol_amount_list, grid_num, leverage, stop_loss):
    """
    Ensure user keys are initialized in old structure (global user_keys).

    Args:
        user_id: User ID
        enter_symbol_amount_list: Initial capital list
        grid_num: Grid number
        leverage: Leverage value
        stop_loss: Stop loss value
    """
    global user_keys
    if user_id not in user_keys:
        user_keys[user_id] = {
            "api_key": None,
            "api_secret": None,
            "password": None,
            "is_running": False,
            "stop_loss": stop_loss,
            "tasks": [],
            "running_symbols": set(),
            "completed_trading_symbols": set(),
            "initial_capital": enter_symbol_amount_list,
            "grid_num": grid_num,
            "leverage": leverage,
            "symbols": {}
        }
    else:
        if "is_running" not in user_keys[user_id]:
            user_keys[user_id]["is_running"] = False
        if "tasks" not in user_keys[user_id]:
            user_keys[user_id]["tasks"] = []
        if "running_symbols" not in user_keys[user_id]:
            user_keys[user_id]["running_symbols"] = set()
        if "completed_trading_symbols" not in user_keys[user_id]:
            user_keys[user_id]["completed_trading_symbols"] = set()
        if "initial_capital" not in user_keys[user_id]:
            user_keys[user_id]["initial_capital"] = enter_symbol_amount_list
        if "grid_num" not in user_keys[user_id]:
            user_keys[user_id]["grid_num"] = grid_num
        if "leverage" not in user_keys[user_id] and leverage is not None:
            user_keys[user_id]["leverage"] = leverage
        if "stop_loss" not in user_keys[user_id] and stop_loss is not None:
            user_keys[user_id]["stop_loss"] = stop_loss
        if "symbols" not in user_keys[user_id]:
            user_keys[user_id]["symbols"] = {}


async def ensure_user_keys_initialized(exchange_name, user_id, enter_symbol_amount_list, grid_num, leverage, stop_loss):
    """
    Ensure user keys are initialized in Redis.

    Args:
        exchange_name: Exchange name
        user_id: User ID
        enter_symbol_amount_list: Initial capital list
        grid_num: Grid number
        leverage: Leverage value
        stop_loss: Stop loss value

    Returns:
        User data dict
    """
    redis = await get_redis_connection()
    try:
        user_key = f'{exchange_name}:user:{user_id}'

        # Check if user exists
        user_exists = await redis.exists(user_key)

        if not user_exists:
            # Create new user data
            user_data = {
                "api_key": "",
                "api_secret": "",
                "password": "",
                "is_running": "0",
                "stop_loss": str(stop_loss),
                "tasks": json.dumps([]),
                "running_symbols": json.dumps([]),
                "completed_trading_symbols": json.dumps([]),
                "initial_capital": json.dumps(enter_symbol_amount_list),
                "grid_num": str(grid_num),
                "leverage": str(leverage),
                "symbols": json.dumps({})
            }
            await redis.hset(user_key, mapping=user_data)
        else:
            # Update existing user data
            updates = {}

            # Check and update fields if they don't exist
            fields_to_check = [
                ("is_running", "0"),
                ("tasks", json.dumps([])),
                ("running_symbols", json.dumps([])),
                ("completed_trading_symbols", json.dumps([])),
                ("initial_capital", json.dumps(enter_symbol_amount_list)),
                ("grid_num", str(grid_num)),
                ("leverage", str(leverage)),
                ("stop_loss", str(stop_loss)),
                ("symbols", json.dumps({}))
            ]

            for field, default_value in fields_to_check:
                if not await redis.hexists(user_key, field):
                    updates[field] = default_value

            if updates:
                await redis.hset(user_key, mapping=updates)

        # Retrieve and return the user data
        user_data = await redis.hgetall(user_key)
        return {k.decode() if isinstance(k, bytes) else k:
                v.decode() if isinstance(v, bytes) else v
                for k, v in user_data.items()}

    finally:
        await redis.close()


# ==================== Symbol Initialization ====================

def encode_value(value):
    """Encode value for Redis storage"""
    if value is None:
        return 'None'
    return json.dumps(value)


def decode_value(value):
    """Decode value from Redis storage"""
    if value == 'None':
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def ensure_symbol_initialized_old_struc(user_id, symbol, grid_num):
    """
    Ensure symbol is initialized in old structure (global user_keys).

    Args:
        user_id: User ID
        symbol: Trading symbol
        grid_num: Grid number
    """
    global user_keys
    if symbol not in user_keys[user_id]["symbols"]:
        user_keys[user_id]["symbols"][symbol] = {
            "take_profit_orders_info": {n: {"order_id": None, "quantity": 0.0, "target_price": 0.0, "active": False, "side": None} for n in range(1, grid_num + 1)},
            "last_entry_time": None,
            "last_entry_size": 0.0,
            "previous_new_position_size": 0.0,
            "order_placed": {n: False for n in range(1, grid_num + 1)},
            "last_placed_prices": {n: 0.0 for n in range(0, grid_num + 1)},
            "initial_balance_of_symbol": 0.0,
            "order_ids": {n: None for n in range(1, grid_num + 1)},
            "level_quantities": {n: 0.0 for n in range(1, grid_num + 1)},
        }


async def ensure_symbol_initialized(exchange_name, user_id, symbol, grid_num):
    """
    Ensure symbol is initialized in Redis with proper structure.

    Args:
        exchange_name: Exchange name
        user_id: User ID
        symbol: Trading symbol
        grid_num: Grid number
    """
    redis = await get_redis_connection()
    try:
        user_key = f'{exchange_name}:user:{user_id}'
        # Check if user exists
        if not await redis.exists(user_key):
            raise KeyError(f"User ID {user_id} not found in Redis")

        # Try to get symbol data directly (new structure)
        symbol_key = f'symbol:{symbol}'
        symbol_data = await redis.hget(user_key, symbol_key)

        if symbol_data is None:
            # If not found, try to get all symbols data (old structure)
            all_symbols_data = await redis.hget(user_key, 'symbols')
            if all_symbols_data:
                # Old structure
                user_symbols = json.loads(all_symbols_data)
                if not isinstance(user_symbols, dict):
                    user_symbols = {}
            else:
                # Neither new nor old structure found, initialize new dictionary
                user_symbols = {}

            if symbol not in user_symbols:
                user_symbols[symbol] = {
                    "take_profit_orders_info": {
                        str(n): {
                            "order_id": None,
                            "quantity": 0.0,
                            "target_price": 0.0,
                            "active": False,
                            "side": None
                        } for n in range(0, grid_num + 1)
                    },
                    "last_entry_time": None,
                    "last_entry_size": 0.0,
                    "previous_new_position_size": 0.0
                }

                # Initialize order_placed
                order_placed_key = f'{exchange_name}:user:{user_id}:symbol:{symbol}:order_placed'
                if not await redis.exists(order_placed_key):
                    order_placed = {str(n): "false" for n in range(0, grid_num + 1)}
                    await redis.hmset(order_placed_key, order_placed)
                    await redis.expire(order_placed_key, 890)  # 890초 후 만료
                    print(f"Symbol {symbol} and order_placed initialized for user {user_id}")
                order_ids_key = f'{exchange_name}:user:{user_id}:symbol:{symbol}:order_ids'
                if not await redis.exists(order_ids_key):
                    order_ids = {str(n): encode_value(None) for n in range(0, grid_num + 1)}
                    await redis.hmset(order_ids_key, order_ids)
                    print(f"Symbol {symbol} and order_ids initialized for user {user_id}")
            else:
                print(f"Symbol {symbol} already exists for user {user_id}")
        else:
            print(f"Symbol {symbol} already initialized for user {user_id} in new structure")
            # Check if order_placed exists, if not, initialize it
            order_placed_key = f'{exchange_name}:user:{user_id}:symbol:{symbol}:order_placed'
            if not await redis.exists(order_placed_key):
                order_placed = {str(n): "false" for n in range(0, grid_num + 1)}
                await redis.hmset(order_placed_key, order_placed)
                await redis.expire(order_placed_key, 890)  # 890초 후 만료
                print(f"order_placed initialized for user {user_id} and symbol {symbol}")

    except Exception as e:
        print(f"An error occurred while initializing symbol {symbol} for user {user_id}: {e}")
        raise e
    except KeyError as e:
        print(f"KeyError in ensure_symbol_initialized: {e}")
    except json.JSONDecodeError as e:
        print(f"JSON Decode Error in ensure_symbol_initialized: {e}")
        print(f"Raw data: {all_symbols_data if 'all_symbols_data' in locals() else symbol_data}")
    except Exception as e:
        print(f"Unexpected error in ensure_symbol_initialized: {e}")
        print(traceback.format_exc())
    finally:
        await redis.close()


# ==================== User Validation & Checks ====================

def check_right_invitee(okx_api, okx_secret, okx_parra):
    """
    Check if user is a valid invitee.

    Args:
        okx_api: OKX API key
        okx_secret: OKX secret key
        okx_parra: OKX passphrase

    Returns:
        Tuple of (is_valid, uid)
    """
    import src.utils.check_invitee as check_invitee
    invitee = True
    try:
        invitee, uid = check_invitee.get_uid_from_api_keys(okx_api, okx_secret, okx_parra)
        if invitee:
            return True, uid
        else:
            return False, None
    except Exception as e:
        print(f"Error checking invitee: {e}")
        print(traceback.format_exc())
        return False


async def check_symbol_entry_info(exchange_name, user_id):
    """
    Check symbol entry information for debugging.

    Args:
        exchange_name: Exchange name
        user_id: User ID
    """
    redis = await get_redis_connection()
    try:
        user_key = f'{exchange_name}:user:{user_id}'

        # Get user symbols data
        user_symbols_data = await redis.hget(user_key, 'symbols')
        user_symbols = json.loads(user_symbols_data) if user_symbols_data else {}

        for symbol, symbol_info in user_symbols.items():
            last_entry_time = symbol_info.get("last_entry_time")
            last_entry_size = symbol_info.get("last_entry_size")
            print(f"Symbol: {symbol}, Last Entry Time: {last_entry_time}, Last Entry Size: {last_entry_size}")

    except Exception as e:
        print(f"Unexpected error in check_symbol_entry_info: {e}")
        print(traceback.format_exc())
    finally:
        await redis.close()


async def check_api_permissions(exchange_name, user_id):
    """
    Check API permissions for exchange.

    Args:
        exchange_name: Exchange name
        user_id: User ID
    """
    from GRID.trading.instance_manager import get_exchange_instance

    try:
        exchange = await get_exchange_instance(exchange_name, user_id)
        if exchange is not None and exchange_name == 'okx':
            positions_data = await exchange.private_get_account_positions()
            logging.info(f"✅ {user_id} API 연결 확인: {exchange_name}")
    except Exception as e:
        print(f"Error starting: {e}")
        logging.error(f"❌ {user_id} API 연결 실패: {exchange_name}")
        raise e


async def check_permissions_and_initialize(exchange_name, user_id, enter_symbol_amount_list, grid_num, leverage, stop_loss):
    """
    Check API permissions and initialize user data.

    Args:
        exchange_name: Exchange name
        user_id: User ID
        enter_symbol_amount_list: Initial capital list
        grid_num: Grid number
        leverage: Leverage value
        stop_loss: Stop loss value
    """
    await check_api_permissions(exchange_name, user_id)
    try:
        await ensure_user_keys_initialized(exchange_name, user_id, enter_symbol_amount_list, grid_num, leverage, stop_loss)
        ensure_user_keys_initialized_old_struc(user_id, enter_symbol_amount_list, grid_num, leverage, stop_loss)
    except Exception as e:
        print(f"Error on initializing user keys: {str(e)}")


# ==================== Symbol Utilities ====================

async def get_and_format_symbols(exchange_name, user_id, direction, n, force_restart):
    """
    Get and format symbols for trading.

    Args:
        exchange_name: Exchange name
        user_id: User ID
        direction: Trading direction
        n: Number of symbols
        force_restart: Whether to force restart

    Returns:
        Tuple of (symbols, modified_symbols)
    """
    from GRID.services.symbol_service import get_top_symbols, modify_symbols

    symbols = await get_top_symbols(user_id, exchange_name=exchange_name, direction=direction, limit=n, force_restart=force_restart)
    modified_symbols = modify_symbols(exchange_name, symbols)
    print(symbols)
    return symbols, modified_symbols


def format_symbols(symbols):
    """
    Format symbols for display.

    Args:
        symbols: List of symbols

    Returns:
        Formatted string
    """
    modified_symbols = [f"'{symbol}'" for symbol in symbols]
    return f"[{', '.join(modified_symbols)}]"


async def prepare_initial_messages(exchange_name, user_id, symbols, enter_symbol_amount_list, leverage, total_enter_symbol_amount):
    """
    Prepare initial trading messages for user.

    Args:
        exchange_name: Exchange name
        user_id: User ID
        symbols: List of trading symbols
        enter_symbol_amount_list: Initial capital list
        leverage: Leverage value
        total_enter_symbol_amount: Total capital amount

    Returns:
        Formatted message string
    """
    try:
        currency_symbol = '₩' if exchange_name in ['upbit'] else '$'
        user_id_str = str(user_id)
        symbols_formatted = format_symbols(symbols)
        initial_capital_formatted_list = [f"{amount:,.1f}{currency_symbol}" for amount in enter_symbol_amount_list]
        initial_capital_formatted = "\n".join(
            ', '.join(initial_capital_formatted_list[i:i+4]) for i in range(0, len(initial_capital_formatted_list), 4)
        )
        total_capital_formatted = "{:,.2f}".format(total_enter_symbol_amount)
        total_capital_leveraged_formatted = "{:,.2f}".format(total_enter_symbol_amount * leverage)
        initial_capital_formatted_20x = "{:,.1f}".format(total_enter_symbol_amount * leverage)

        message = (
            f"{user_id} : [{exchange_name.upper()}] 매매 시작 알림\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            f"📊 거래 종목: {symbols_formatted}\n\n"
            f"💰 그리드 당 투입금액: {initial_capital_formatted} $\n\n"
            "📈 투자 요약:\n"
        )
        if leverage != 1:
            message += (
                f"  종목 당 최대 투입 마진 : {total_capital_leveraged_formatted}{currency_symbol}\n"
                f"   ↳ 최대 투입 가능 금액: {initial_capital_formatted_20x}{currency_symbol} ({total_capital_formatted} * {leverage}배)\n"
            )
        else:
            message += (
                f"  종목 당 총 투입 금액: {total_capital_formatted}{currency_symbol}\n"
                f"   ↳ 최대 투입 금액: {initial_capital_formatted_20x}{currency_symbol}*20개\n"
            )
        message += "━━━━━━━━━━━━━━━━━━"
        print(message)
        await send_initial_logs(user_id_str, exchange_name, message)
        return message
    except Exception as e:
        print(f"Error preparing initial messages: {e}")
        print(traceback.format_exc())


async def send_initial_logs(user_id, exchange_name, message):
    """
    Send initial logs to user and telegram.

    Args:
        user_id: User ID
        exchange_name: Exchange name
        message: Message to send
    """
    await add_user_log(user_id, message)
    asyncio.create_task(telegram_message.send_telegram_message(message, exchange_name, user_id))


async def handle_completed_tasks(tasks, exchange_name, user_id, completed_symbols, running_symbols, user_key, redis):
    """
    Handle completed tasks and update symbol lists.

    Args:
        tasks: List of asyncio tasks
        exchange_name: Exchange name
        user_id: User ID
        completed_symbols: Set of completed symbols
        running_symbols: Set of running symbols
        user_key: Redis user key
        redis: Redis connection
    """
    done_tasks = [task for task in tasks if task.done()]
    for task in done_tasks:
        try:
            result = await task
            if result:
                completed_symbols.add(result)
                running_symbols.remove(result)
                await redis.hset(user_key, 'running_symbols', json.dumps(list(running_symbols)))
                await redis.hset(user_key, 'completed_trading_symbols', json.dumps(list(completed_symbols)))
        except Exception as e:
            print(f"Error handling completed task: {e}")
            print(traceback.format_exc())
