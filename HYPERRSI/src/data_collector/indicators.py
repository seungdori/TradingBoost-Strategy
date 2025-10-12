# indicators.py
# This file now re-exports indicator functions from shared.indicators module

#===============================================================================
# Re-export shared indicator functions for backward compatibility
#===============================================================================

# All indicator calculation functions
# Core utility functions
from shared.indicators import (
    calc_atr,
    calc_bollinger_bands,
    calc_ema,
    calc_jma,
    calc_rma,
    calc_rsi,
    calc_sma,
    calc_stddev,
    calc_t3,
    calc_vidya,
    compute_all_indicators,
    compute_trend_state,
    crossover,
    crossunder,
    dynamic_round,
    falling,
    get_ma,
    rational_quadratic,
    rising,
)

# Explicitly declare what's exported for linters
__all__ = [
    'crossover', 'crossunder', 'rising', 'falling', 'dynamic_round',
    'calc_sma', 'calc_ema', 'calc_rma', 'calc_t3', 'calc_vidya', 'calc_jma',
    'calc_atr', 'calc_rsi', 'calc_stddev', 'calc_bollinger_bands', 'get_ma',
    'compute_trend_state', 'rational_quadratic', 'compute_all_indicators'
]

# All indicator functions are now provided by shared.indicators module
# This file serves as a compatibility layer for existing code that imports from here
