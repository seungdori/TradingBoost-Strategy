"""
Bollinger Bands indicator
"""
import math
from collections import deque

import numpy as np


def calc_stddev(series: list[float], length: int) -> list[float]:
    """표준편차(STDEV) - 원래 구현 (length만큼 데이터 필요)"""
    window: deque[float] = deque()
    sum_ = 0.0
    sum_sq = 0.0
    result = []

    for i, val in enumerate(series):
        window.append(val)
        sum_ += val
        sum_sq += val * val

        if i >= length:
            old = window.popleft()
            sum_ -= old
            sum_sq -= old * old

        if i < length - 1:
            result.append(math.nan)
        else:
            mean = sum_ / length
            var = (sum_sq / length) - (mean * mean)
            result.append(math.sqrt(var) if var > 0 else 0)
    return result


def calc_bollinger_bands(series, length=20, mult=2.0):
    """
    단순 이동평균 + 표준편차를 활용한 Bollinger Bands
    series: float 리스트(예: 종가 리스트)
    length: 볼린저 밴드 기간
    mult: 표준편차 곱
    """
    from ._moving_averages import calc_sma

    n = len(series)
    if n == 0:
        return [None]*n, [None]*n, [None]*n

    # 중간선(middle)은 SMA(length)
    middle = calc_sma(series, length)
    upper = [None]*n
    lower = [None]*n

    for i in range(n):
        if i < length - 1:
            # 아직 length기간만큼 데이터가 없음
            continue
        # length개 구간
        window = series[i - length + 1 : i + 1]
        stdev = float(np.std(window, ddof=1))  # sample std
        m = middle[i]
        upper[i] = m + mult*stdev
        lower[i] = m - mult*stdev

    return upper, middle, lower
