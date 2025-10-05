"""GRID 트레이딩 봇 메인 모듈 (Refactored v3 - Final)

완전히 모듈화된 구조:
- core/: 핵심 인프라 (Redis, WebSocket, 예외)
- utils/: 유틸리티 함수들
- handlers/: 거래소별 핸들러
- services/: 비즈니스 로직 (향후 확장)
- trading/: 트레이딩 로직 (향후 확장)
- database/: DB 접근 (향후 확장)
- main/: 메인 진입점 (향후 확장)

백업: grid_original.py (6,031줄)
"""

# ==================== 표준 라이브러리 ====================
import logging
import asyncio

# ==================== 프로젝트 모듈 ====================
from GRID.routes.connection_manager import ConnectionManager
from GRID.trading.shared_state import cancel_state, user_keys

# ==================== 리팩토링된 모듈 ====================
# Core
from GRID.core.exceptions import QuitException, AddAnotherException
from GRID.core.redis import (
    get_redis_connection,
    redis_client,
    set_redis_data,
    get_redis_data,
)
from GRID.core.websocket import log_exception, send_heartbeat, ws_client

# Utils
from GRID.utils.validators import parse_bool, check_order_validity
from GRID.utils.price import (
    round_to_upbit_tick_size,
    get_order_price_unit_upbit,
    get_corrected_rounded_price,
    get_min_notional
)
from GRID.utils.precision import (
    get_upbit_precision,
    get_price_precision,
    adjust_price_precision
)
from GRID.utils.quantity import calculate_order_quantity
from shared.utils import (parse_timeframe, calculate_current_timeframe_start, calculate_next_timeframe_start, calculate_sleep_duration)
from GRID.utils.redis_helpers import (
    set_running_symbols,
    check_running_symbols,
    get_placed_prices,
    add_placed_price,
    is_order_placed,
    is_price_placed,
    set_order_placed,
    get_order_placed,
    reset_order_placed
)
from GRID.utils.async_helpers import async_debounce, custom_sleep

# Handlers
from GRID.handlers.upbit import process_upbit_balance, handle_upbit
from GRID.handlers.okx import process_okx_position_data, handle_okx
from GRID.handlers.common import process_other_exchange_position, handle_other_exchanges

# ==================== 새로 모듈화된 함수들 Import ====================
# Visualization
from GRID.utils.visualization import plot_trading_signals

# Balance & Position
from GRID.services.balance_service import (
    get_balance_of_symbol,
    get_all_positions,
    get_position_size,
)

# Order Management
from GRID.services.order_service import (
    check_existing_order_at_price,
    okay_to_place_order,
    create_short_order,
    create_short_orders,
    get_take_profit_orders_info,
    fetch_order_with_retry,
    cancel_user_limit_orders,
)

# Symbol Management
from GRID.services.symbol_service import (
    sort_ai_trading_data,
    build_sort_ai_trading_data,
    get_all_binance_usdt_symbols,
    get_all_binance_usdt_spot_symbols,
    get_all_bitget_usdt_symbols,
    get_upbit_market_data,
    get_running_symbols,
    get_completed_symbols,
    get_top_symbols,
    modify_symbols,
    format_symbols,
)

# Symbol Repository (Database)
from GRID.repositories.symbol_repository import (
    get_ban_list_from_db,
    get_white_list_from_db,
    clear_blacklist,
    clear_whitelist,
    add_symbols,
)

# User Management
from GRID.services.user_management_service import (
    check_right_invitee,
    get_user_data,
    initialize_user_data,
    get_user_data_from_redis,
    update_user_data,
    ensure_user_keys_initialized_old_struc,
    ensure_user_keys_initialized,
    encode_value,
    decode_value,
    ensure_symbol_initialized,
    ensure_symbol_initialized_old_struc,
    check_symbol_entry_info,
    check_api_permissions,
    check_permissions_and_initialize,
    get_and_format_symbols,
    prepare_initial_messages,
    send_initial_logs,
    handle_completed_tasks,
)

# ==================== Grid Trading Core ====================
from GRID.trading.grid_core import (
    calculate_grid_levels,
    create_short_orders,
    place_grid_orders,
    periodic_15m_logic,
    long_logic,
    short_logic,
    check_order_status,
)

# ==================== Monitoring  ====================
from GRID.monitoring.position_monitor import (
    monitor_tp_orders_websocekts,
    monitor_positions,
    monitor_custom_stop,
    check_entry_order,
    check_and_close_positions,
    manually_close_positions,
    manually_close_symbol,
    monitor_and_handle_tasks,
)

# ==================== Task Management (모듈화 완료) ====================
from GRID.jobs.task_manager import (
    run_task,
    task_completed,
    cancel_tasks,
    summarize_trading_results,
    create_symbol_task,
    create_monitoring_tasks,
    create_recovery_tasks,
    initialize_and_load_user_data,
    create_individual_task,
    handle_skipped_symbols,
    process_new_symbols,
    create_tasks,
    handle_task_completion,
    create_new_task,
    create_stop_loss_task,
    create_custom_stop_task,
    get_new_symbols,
)

from GRID.main.grid_main import (
    main,
    sell_all_coins,
    cancel_all_tasks,
    start_feature,
)

# ==================== 전역 변수 ====================
completed_tasks = set()
running_symbols = set()
completed_symbols = set()
manager = ConnectionManager()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ==================== __all__ ====================
__all__ = [
    # Core
    'QuitException', 'AddAnotherException',
    'get_redis_connection', 'redis_client', 'set_redis_data', 'get_redis_data',
    'log_exception', 'send_heartbeat', 'ws_client',
    
    # Utils
    'parse_bool', 'check_order_validity',
    'round_to_upbit_tick_size', 'get_order_price_unit_upbit', 'get_corrected_rounded_price', 'get_min_notional',
    'get_upbit_precision', 'get_price_precision', 'adjust_price_precision',
    'calculate_order_quantity',
    'parse_timeframe', 'calculate_current_timeframe_start', 'calculate_next_timeframe_start', 'calculate_sleep_duration',
    'set_running_symbols', 'check_running_symbols',
    'get_placed_prices', 'add_placed_price', 'is_order_placed', 'is_price_placed',
    'set_order_placed', 'get_order_placed', 'reset_order_placed',
    'async_debounce', 'custom_sleep',
    
    # Handlers
    'process_upbit_balance', 'handle_upbit',
    'process_okx_position_data', 'handle_okx',
    'process_other_exchange_position', 'handle_other_exchanges',
    
    # From grid_original
    'plot_trading_signals',
    'get_balance_of_symbol', 'get_all_positions', 'get_position_size',
    'check_existing_order_at_price', 'okay_to_place_order',
    'create_short_order', 'create_short_orders', 'get_take_profit_orders_info',
    'fetch_order_with_retry', 'check_order_status', 'cancel_user_limit_orders',
    'place_grid_orders', 'periodic_15m_logic', 'long_logic', 'short_logic',
    'calculate_grid_levels', 'run_task',
    'monitor_tp_orders_websocekts', 'monitor_positions', 'monitor_custom_stop',
    'check_entry_order', 'check_and_close_positions', 'manually_close_positions', 'manually_close_symbol',
    'sort_ai_trading_data', 'build_sort_ai_trading_data',
    'get_all_binance_usdt_symbols', 'get_all_binance_usdt_spot_symbols', 'get_all_bitget_usdt_symbols',
    'generate_profit_data', 'process_exchange_data',
    'get_running_symbols', 'get_completed_symbols', 'get_top_symbols',
    'get_upbit_market_data', 'get_new_symbols', 'modify_symbols', 'format_symbols',
    'get_ban_list_from_db', 'get_white_list_from_db', 'clear_blacklist', 'clear_whitelist', 'add_symbols',
    'task_completed', 'cancel_tasks', 'summarize_trading_results',
    'create_symbol_task', 'create_monitoring_tasks', 'create_recovery_tasks',
    'initialize_and_load_user_data', 'create_individual_task',
    'handle_skipped_symbols', 'process_new_symbols', 'monitor_and_handle_tasks',
    'create_tasks', 'handle_task_completion', 'create_new_task',
    'create_stop_loss_task', 'create_custom_stop_task',
    'check_right_invitee', 'get_user_data', 'initialize_user_data',
    'get_user_data_from_redis', 'update_user_data',
    'ensure_user_keys_initialized_old_struc', 'ensure_user_keys_initialized',
    'encode_value', 'decode_value', 'ensure_symbol_initialized', 'ensure_symbol_initialized_old_struc',
    'check_symbol_entry_info', 'check_api_permissions', 'check_permissions_and_initialize',
    'get_and_format_symbols', 'prepare_initial_messages', 'send_initial_logs', 'handle_completed_tasks',
    'main', 'sell_all_coins', 'cancel_all_tasks', 'start_feature',
    
    # Globals
    'completed_tasks', 'running_symbols', 'completed_symbols', 'manager', 'logger',
]
