"""
Shared Indicators Package

단일 진입점으로 모든 지표 함수를 import할 수 있습니다.

사용 예시:
    from shared.indicators import calc_rsi, calc_sma, compute_all_indicators
"""

# Core utility functions
from ._core import (
    crossover,
    crossunder,
    rising,
    falling,
    dynamic_round
)

# Moving averages
from ._moving_averages import (
    calc_sma,
    calc_ema,
    calc_rma_improved,
    calc_t3,
    calc_vidya,
    calc_jma,
    get_ma
)

# RSI
from ._rsi import calc_rsi

# ATR
from ._atr import calc_atr

# Bollinger Bands
from ._bollinger import (
    calc_stddev,
    calc_bollinger_bands
)

# Trend analysis
from ._trend import (
    rational_quadratic,
    compute_trend_state
)

# All indicators computation
from ._all_indicators import compute_all_indicators

__all__ = [
    # Core
    'crossover',
    'crossunder',
    'rising',
    'falling',
    'dynamic_round',
    # Moving averages
    'calc_sma',
    'calc_ema',
    'calc_rma_improved',
    'calc_t3',
    'calc_vidya',
    'calc_jma',
    'get_ma',
    # RSI
    'calc_rsi',
    # ATR
    'calc_atr',
    # Bollinger
    'calc_stddev',
    'calc_bollinger_bands',
    # Trend
    'rational_quadratic',
    'compute_trend_state',
    # All
    'compute_all_indicators',
]
