# -*- coding: utf-8 -*-
"""
GRID Strategy Pandas Helper Functions

Pandas-based helper functions for technical analysis in GRID strategy.
These are GRID-specific implementations optimized for pandas DataFrames.
"""

import pandas as pd


def atr(df, length=14):
    """
    Average True Range (ATR)을 계산합니다.

    :param df: OHLC 데이터를 포함하는 pandas DataFrame
    :param length: ATR을 계산하기 위한 기간
    :return: ATR 값이 추가된 pandas DataFrame
    """
    high = df['high']
    low = df['low']
    close = df['close']

    # True Range 계산
    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    # ATR 계산
    atr_values = true_range.rolling(window=length).mean()
    df['atr'] = atr_values
    return df


def crossover(series1, series2):
    """
    시리즈1이 시리즈2를 상향 돌파하는지 확인합니다.

    :param series1: 첫 번째 pandas Series
    :param series2: 두 번째 pandas Series
    :return: 상향 돌파 여부를 나타내는 boolean Series
    """
    return (series1 > series2) & (series1.shift() < series2.shift())


def crossunder(series1, series2):
    """
    시리즈1이 시리즈2를 하향 돌파하는지 확인합니다.

    :param series1: 첫 번째 pandas Series
    :param series2: 두 번째 pandas Series
    :return: 하향 돌파 여부를 나타내는 boolean Series
    """
    return (series1 < series2) & (series1.shift() > series2.shift())


def rising(series, periods=2):
    """
    시리즈가 지정된 기간 동안 상승하는지 확인합니다.

    :param series: pandas Series
    :param periods: 비교할 기간 수
    :return: 상승 여부를 나타내는 boolean Series
    """
    return series.diff(periods=periods) > 0


def falling(series, periods=3):
    """
    시리즈가 지정된 기간 동안 하락하는지 확인합니다.

    :param series: pandas Series
    :param periods: 비교할 기간 수
    :return: 하락 여부를 나타내는 boolean Series
    """
    return series.diff(periods=periods) < 0


__all__ = [
    'atr',
    'crossover',
    'crossunder',
    'rising',
    'falling',
]
