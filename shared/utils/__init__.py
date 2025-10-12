"""Common utility module"""
from shared.utils.async_helpers import (
    ensure_async_loop,
    get_or_create_event_loop,
    retry_async,
    retry_decorator,
)
from shared.utils.path_config import configure_pythonpath, get_project_root
from shared.utils.redis_utils import (
    add_recent_symbol,
    delete_position,
    delete_redis_data,
    exists_redis_key,
    get_position,
    get_recent_symbols,
    get_redis_data,
    get_user_settings,
    set_position,
    set_redis_data,
    set_user_settings,
)
from shared.utils.symbol_helpers import (
    ccxt_to_okx_symbol,
    convert_symbol_to_okx_instrument,
    convert_to_trading_symbol,
    extract_base_currency,
    extract_quote_currency,
    is_swap_symbol,
    is_valid_symbol,
    normalize_symbol,
    okx_to_ccxt_symbol,
    parse_symbol,
)
from shared.utils.time_helpers import (
    calculate_current_timeframe_start,
    calculate_next_timeframe_start,
    calculate_sleep_duration,
    get_timeframe_boundaries,
    parse_timeframe,
    timeframe_to_seconds,
    timeframe_to_timedelta,
)
from shared.utils.trading_helpers import (
    contracts_to_qty,
    get_actual_order_type,
    get_contract_size,
    get_lot_sizes,
    get_minimum_qty,
    get_perpetual_instruments,
    get_tick_size_from_redis,
    is_break_even_order,
    is_sl_order,
    is_tp_order,
    is_valid_order_type,
    normalize_order_type,
    parse_order_info,
    round_to_qty,
    round_to_tick_size,
    split_contracts,
)
from shared.utils.type_converters import (
    convert_bool_to_int,
    convert_bool_to_string,
    is_true_value,
    parse_bool,
    parse_numeric,
    safe_decimal,
    safe_float,
    safe_int,
    validate_settings,
)

__all__ = [
    # Path configuration
    'configure_pythonpath', 'get_project_root',
    # Async helpers
    'retry_async', 'retry_decorator',
    'ensure_async_loop', 'get_or_create_event_loop',
    # Type converters
    'parse_bool', 'safe_float', 'safe_int', 'safe_decimal',
    'validate_settings', 'parse_numeric', 'is_true_value',
    'convert_bool_to_string', 'convert_bool_to_int',
    # Time helpers
    'parse_timeframe', 'calculate_current_timeframe_start',
    'calculate_next_timeframe_start', 'calculate_sleep_duration',
    'timeframe_to_seconds', 'timeframe_to_timedelta', 'get_timeframe_boundaries',
    # Symbol helpers
    'okx_to_ccxt_symbol', 'ccxt_to_okx_symbol', 'convert_symbol_to_okx_instrument',
    'parse_symbol', 'normalize_symbol', 'is_valid_symbol',
    'extract_base_currency', 'extract_quote_currency', 'is_swap_symbol',
    'convert_to_trading_symbol',
    # Redis utils
    'set_redis_data', 'get_redis_data', 'delete_redis_data', 'exists_redis_key',
    'get_user_settings', 'set_user_settings',
    'add_recent_symbol', 'get_recent_symbols',
    'get_position', 'set_position', 'delete_position',
    # Trading helpers
    'get_actual_order_type', 'is_valid_order_type', 'normalize_order_type',
    'parse_order_info', 'is_tp_order', 'is_sl_order', 'is_break_even_order',
    # Order contract helpers
    'get_perpetual_instruments', 'get_lot_sizes', 'round_to_qty',
    'contracts_to_qty', 'split_contracts',
    # Contract/Tick helpers
    'get_contract_size', 'get_tick_size_from_redis',
    'get_minimum_qty', 'round_to_tick_size',
]
