"""
Position Handler Constants

This module defines all Redis key patterns and configuration constants
used throughout the position handler package.
"""

# ============================================================================
# Redis Key Patterns
# ============================================================================
# Format strings use Python f-string style placeholders

# Margin and Blocking
MARGIN_BLOCK_KEY = "margin_block:{user_id}:{symbol}"

# Position Management
POSITION_KEY = "user:{user_id}:position:{symbol}:{side}"
MAIN_POSITION_DIRECTION_KEY = "user:{user_id}:position:{symbol}:main_position_direction"
MIN_SUSTAIN_CONTRACT_SIZE_KEY = "user:{user_id}:position:{symbol}:min_sustain_contract_size"

# DCA (Dollar Cost Averaging) / Pyramiding
DCA_COUNT_KEY = "user:{user_id}:position:{symbol}:{side}:dca_count"
DCA_LEVELS_KEY = "user:{user_id}:position:{symbol}:{side}:dca_levels"

# Take Profit
TP_DATA_KEY = "user:{user_id}:position:{symbol}:{side}:tp_data"
TP_STATE_KEY = "user:{user_id}:position:{symbol}:{side}:tp_state"

# Stop Loss
SL_DATA_KEY = "user:{user_id}:position:{symbol}:{side}:sl_data"

# Position Size Tracking
INITIAL_SIZE_KEY = "user:{user_id}:position:{symbol}:{side}:initial_size"
LAST_ENTRY_SIZE_KEY = "user:{user_id}:position:{symbol}:{side}:last_entry_size"

# Position State
POSITION_STATE_KEY = "user:{user_id}:position:{symbol}:position_state"
PENDING_DELETION_KEY = "user:{user_id}:position:{symbol}:{side}:pending_deletion"

# Trading Mode
HEDGE_MODE_KEY = "user:{user_id}:position:{symbol}:hedge_mode"
TD_MODE_KEY = "user:{user_id}:position:{symbol}:tdMode"
HEDGING_DIRECTION_KEY = "user:{user_id}:position:{symbol}:hedging_direction"

# ============================================================================
# Position Cleanup Key Patterns
# ============================================================================
# 포지션 청산/삭제 시 삭제해야 할 모든 키 패턴
# side 변수가 필요한 키 (long/short 별도 삭제)
POSITION_SIDE_KEYS = [
    POSITION_KEY,           # 메인 포지션 hash
    DCA_COUNT_KEY,          # DCA 카운트
    DCA_LEVELS_KEY,         # DCA 레벨 목록
    TP_DATA_KEY,            # TP 가격 데이터
    TP_STATE_KEY,           # TP 상태
    SL_DATA_KEY,            # SL 데이터
    INITIAL_SIZE_KEY,       # 초기 사이즈
    LAST_ENTRY_SIZE_KEY,    # 마지막 진입 사이즈
    PENDING_DELETION_KEY,   # 삭제 대기 플래그
    "trailing:user:{user_id}:{symbol}:{side}",  # Trailing Stop (TRAILING_STOP_KEY)
    "user:{user_id}:current_trade:{symbol}:{side}",  # Current Trade (CURRENT_TRADE_KEY)
    "user:{user_id}:cooldown:{symbol}:{side}",  # Cooldown (COOLDOWN_KEY)
]

# side 변수가 필요 없는 키 (심볼 전체에 적용)
POSITION_SYMBOL_KEYS = [
    MAIN_POSITION_DIRECTION_KEY,    # 메인 포지션 방향
    MIN_SUSTAIN_CONTRACT_SIZE_KEY,  # 최소 유지 사이즈
    POSITION_STATE_KEY,             # 포지션 상태
    HEDGE_MODE_KEY,                 # 헤지 모드
    TD_MODE_KEY,                    # 거래 모드
    HEDGING_DIRECTION_KEY,          # 헤징 방향
    "user:{user_id}:position:{symbol}:entry_price",  # 진입가 (레거시)
    "user:{user_id}:{symbol}:dual_side_position",  # Dual Side Position
    "user:{user_id}:{symbol}:entry_fail_count",  # Entry Fail Count
    "user:{user_id}:{symbol}:dual_side_count",  # Dual Side Count
]

# Trailing Stop
TRAILING_STOP_KEY = "trailing:user:{user_id}:{symbol}:{side}"

# Dual Side Trading
DUAL_SIDE_POSITION_KEY = "user:{user_id}:{symbol}:dual_side_position"

# Current Trade
CURRENT_TRADE_KEY = "user:{user_id}:current_trade:{symbol}:{side}"

# Cooldown and Locking
COOLDOWN_KEY = "user:{user_id}:cooldown:{symbol}:{side}"
POSITION_LOCK_KEY = "user:{user_id}:position_lock:{symbol}:{side}:{timeframe}"

# Entry Management (심볼별로 분리 - 멀티심볼 지원)
ENTRY_FAIL_COUNT_KEY = "user:{user_id}:{symbol}:entry_fail_count"
TREND_SIGNAL_ALERT_KEY = "user:{user_id}:{symbol}:trend_signal_alert"

# Dual Side Trading
DUAL_SIDE_COUNT_KEY = "user:{user_id}:{symbol}:dual_side_count"

# Candle Data
CANDLES_WITH_INDICATORS_KEY = "candles_with_indicators:{symbol}:{timeframe}"

# ============================================================================
# Configuration Constants
# ============================================================================

# Entry Failure Management
MAX_ENTRY_FAILURES = 5  # Maximum consecutive entry failures before stopping

# Alert Expiry
TREND_ALERT_EXPIRY_SECONDS = 7200  # 2 hours in seconds

# Position Lock Expiry (calculated dynamically based on timeframe)
# See core.calculate_next_candle_time() for timeframe-specific calculations

# Minimum Contract Sizes
MIN_CONTRACTS_RATIO_FULL_TP = 0.01  # 1% of initial when TP ratios sum to 1 or 100
MIN_CONTRACTS_RATIO_PARTIAL_TP = 0.0001  # 0.01% for partial TP
MIN_CONTRACTS_ABSOLUTE = 0.02  # Absolute minimum contracts

# ============================================================================
# Message Templates
# ============================================================================

# Entry Messages
ENTRY_MESSAGE_TEMPLATE_LONG = """
🔼 *롱 포지션 진입*

📊 종목: {symbol}
💰 진입가: ${entry_price}
📈 계약수: {contracts}
💵 투자금: ${investment}
🎯 익절가: {tp_prices}
📊 ATR: {atr}

"""

ENTRY_MESSAGE_TEMPLATE_SHORT = """
🔻 *숏 포지션 진입*

📊 종목: {symbol}
💰 진입가: ${entry_price}
📈 계약수: {contracts}
💵 투자금: ${investment}
🎯 익절가: {tp_prices}
📊 ATR: {atr}

"""

# DCA Messages
DCA_MESSAGE_TEMPLATE = """
= *DCA Entry #{dca_count}*

📊 종목: {symbol}
💰 현재가: ${current_price}
➕ 추가 계약수: {added_contracts}
📊 평균 진입가: ${avg_price}
📈 총 계약수: {total_contracts}
🎯 익절가: {tp_prices}
== Next DCA Level: {next_dca}

"""

# Exit Messages
EXIT_MESSAGE_TEMPLATE = """
= *Position Closed*

📊 종목: {symbol}
💰 청산가: ${exit_price}
💵 손익: {pnl}
📝 사유: {reason}

"""

# Error Messages
ERROR_INSUFFICIENT_MARGIN = "마진이 부족합니다"
ERROR_POSITION_LOCKED = "Position is locked for this timeframe"
ERROR_TREND_REVERSAL = "Trend reversal detected - position closed"
ERROR_MAX_FAILURES_REACHED = "Maximum entry failures reached"

# ============================================================================
# Trading Direction Constants
# ============================================================================

DIRECTION_LONG_SHORT = "롱숏"
DIRECTION_LONG = "롱"
DIRECTION_SHORT = "숏"

# ============================================================================
# Trend State Constants (PineScript 3-level system)
# ============================================================================
# HYPERRSI uses PineScript-based trend state calculation with 3 levels:
# - Only extreme states (-2, 2) are used for entry/exit filtering
# - Neutral state (0) allows all entries
# - Based on JMA/T3 + VIDYA moving averages with BBW analysis

TREND_STATE_STRONG_DOWNTREND = -2  # Extreme downtrend: blocks long entries, closes long positions
TREND_STATE_NEUTRAL = 0             # Neutral: allows all entries
TREND_STATE_STRONG_UPTREND = 2      # Extreme uptrend: blocks short entries, closes short positions
