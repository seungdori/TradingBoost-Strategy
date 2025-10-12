"""
Shared utilities and helpers for TradingBoost-Strategy

This module provides common functionality used across HYPERRSI and GRID strategies.
"""

# Version
__version__ = "1.0.0"

# ============================================================================
# OKX Instrument Helpers
# ============================================================================
from shared.helpers.okx_instrument_helper import (
    contracts_to_qty,
    get_lot_sizes,
    get_perpetual_instruments,
    get_symbol_info,
    round_to_qty,
    split_contracts,
)

# ============================================================================
# User ID Conversion
# ============================================================================
from shared.helpers.user_id_converter import (
    get_identifier,
    get_telegram_id_from_uid,
    get_uid_from_telegramid,
)

# ============================================================================
# Async Helpers
# ============================================================================
from shared.utils.async_helpers import (
    async_debounce,
    custom_sleep,
    ensure_async_loop,
    get_or_create_event_loop,
    retry_async,
    retry_decorator,
)

# ============================================================================
# Exchange Precision
# ============================================================================
from shared.utils.exchange_precision import (
    adjust_price_precision,
    get_price_precision,
    get_upbit_precision,
)

# ============================================================================
# Profiling
# ============================================================================
from shared.utils.profiling import (
    profile_cpu_and_time,
    profile_sync,
)

# ============================================================================
# Redis Type Conversion
# ============================================================================
from shared.utils.redis_type_converter import (
    DUAL_SIDE_SETTINGS_SCHEMA,
    USER_SETTINGS_SCHEMA,
    parse_from_redis,
    prepare_for_redis,
)

# ============================================================================
# Note: Trading validators are not imported here to avoid circular dependencies.
# Import directly: from shared.validation.trading_validators import check_order_validity
# ============================================================================
# Time Helpers
# ============================================================================
from shared.utils.time_helpers import (
    calculate_current_timeframe_start,
    calculate_next_timeframe_start,
    calculate_sleep_duration,
    convert_timestamp_millis_to_readable,
    ensure_kst_timestamp,
    fill_missing_timestamps,
    get_timeframe_boundaries,
    parse_exchange_name,
    parse_timeframe,
    parse_timeframe_to_ms,
    parse_timestamp,
    timeframe_to_seconds,
    timeframe_to_timedelta,
)

# ============================================================================
# Public API
# ============================================================================
__all__ = [
    # Version
    "__version__",

    # Redis Type Conversion
    "prepare_for_redis",
    "parse_from_redis",
    "DUAL_SIDE_SETTINGS_SCHEMA",
    "USER_SETTINGS_SCHEMA",

    # User ID Conversion
    "get_uid_from_telegramid",
    "get_telegram_id_from_uid",
    "get_identifier",

    # OKX Instrument Helpers
    "get_perpetual_instruments",
    "get_lot_sizes",
    "get_symbol_info",
    "round_to_qty",
    "contracts_to_qty",
    "split_contracts",

    # Async Helpers
    "retry_async",
    "retry_decorator",
    "ensure_async_loop",
    "get_or_create_event_loop",
    "async_debounce",
    "custom_sleep",

    # Exchange Precision
    "get_upbit_precision",
    "get_price_precision",
    "adjust_price_precision",

    # Time Helpers
    "parse_timeframe",
    "calculate_current_timeframe_start",
    "calculate_next_timeframe_start",
    "calculate_sleep_duration",
    "timeframe_to_seconds",
    "timeframe_to_timedelta",
    "get_timeframe_boundaries",
    "parse_timeframe_to_ms",
    "convert_timestamp_millis_to_readable",
    "ensure_kst_timestamp",
    "parse_exchange_name",
    "parse_timestamp",
    "fill_missing_timestamps",

    # Profiling
    "profile_cpu_and_time",
    "profile_sync",
]
