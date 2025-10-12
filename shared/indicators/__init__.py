"""
Shared Indicators Package

단일 진입점으로 모든 지표 함수를 import할 수 있습니다.

사용 예시:
    from shared.indicators import calc_rsi, calc_sma, compute_all_indicators
"""

# ADX
from ._adx import calculate_adx, calculate_dm_tr, calculate_tr, rma

# All indicators computation
from ._all_indicators import compute_all_indicators

# ATR
from ._atr import calc_atr

# Bollinger Bands
from ._bollinger import calc_bollinger_bands, calc_stddev

# Core utility functions
from ._core import crossover, crossunder, dynamic_round, falling, rising

# MAMA/FAMA
from ._mama_fama import (
    compute_alpha,
    compute_component,
    compute_ema,
    compute_mama_fama,
    hilbert_transform,
)

# Moving averages
from ._moving_averages import calc_ema, calc_jma, calc_rma, calc_sma, calc_t3, calc_vidya, get_ma

# RSI
from ._rsi import calc_rsi

# Trend analysis
from ._trend import compute_trend_state, rational_quadratic

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
    'calc_rma',
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
    # ADX
    'calculate_adx',
    'calculate_dm_tr',
    'calculate_tr',
    'rma',
    # MAMA/FAMA
    'compute_mama_fama',
    'compute_ema',
    'hilbert_transform',
    'compute_component',
    'compute_alpha',
    # All
    'compute_all_indicators',
]
