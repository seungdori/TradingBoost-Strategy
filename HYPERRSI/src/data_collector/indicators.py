# indicators.py
# This file now re-exports indicator functions from shared.indicators module

import math
import numpy as np
from typing import List, Union
from shared.logging import get_logger

logger = get_logger(__name__)

#===============================================================================
# Re-export shared indicator functions for backward compatibility
#===============================================================================

# Core utility functions
from shared.indicators import (
    crossover,
    crossunder,
    rising,
    falling,
    dynamic_round
)

# All indicator calculation functions
from shared.indicators import (
    calc_sma,
    calc_ema,
    calc_rma,
    calc_t3,
    calc_vidya,
    calc_jma,
    calc_atr,
    calc_rsi,
    calc_stddev,
    calc_bollinger_bands,
    get_ma,
    compute_trend_state,
    rational_quadratic,
    compute_all_indicators
)

# All indicator functions are now provided by shared.indicators module
# This file serves as a compatibility layer for existing code that imports from here
