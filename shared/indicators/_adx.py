"""
ADX (Average Directional Index) indicator
"""
import numpy as np
import pandas as pd


def calculate_tr(df: pd.DataFrame) -> pd.DataFrame:
    """
    True Range를 계산합니다.

    Parameters:
    -----------
    df : pd.DataFrame
        OHLC 데이터프레임 (high, low, close 컬럼 필요)

    Returns:
    --------
    pd.DataFrame
        'tr' 컬럼이 추가된 데이터프레임
    """
    # 고가와 저가의 차이
    high_low = df['high'] - df['low']
    # 고가와 이전 종가의 절대 차이
    high_close = abs(df['high'] - df['close'].shift())
    # 저가와 이전 종가의 절대 차이
    low_close = abs(df['low'] - df['close'].shift())

    # 첫 번째 행에서 NaN 값을 처리
    high_close.fillna(0, inplace=True)
    low_close.fillna(0, inplace=True)

    # tr 계산
    df['tr'] = np.maximum(high_low, high_close, low_close)

    return df


def rma(src: pd.Series | np.ndarray | list[float], length: int) -> pd.Series:
    """
    RMA (Relative Moving Average) - Wilder's Smoothing Method

    Parameters:
    -----------
    src : pd.Series or array-like
        계산할 데이터 시리즈
    length : int
        RMA 기간

    Returns:
    --------
    pd.Series
        RMA 값
    """
    if not isinstance(src, pd.Series):
        src = pd.Series(src)
    if len(src) < length:
        return src  # 길이가 부족할 경우 src를 그대로 반환

    alpha = 1 / length
    result = src.copy()
    result.iloc[length-1] = src.iloc[:length].mean()  # 첫 RMA 값은 초기값으로 SMA를 사용

    for i in range(length, len(src)):
        result.iloc[i] = alpha * src.iloc[i] + (1 - alpha) * result.iloc[i-1]

    return result


def calculate_dm_tr(df: pd.DataFrame, length: int) -> pd.DataFrame:
    """
    Directional Movement (+DM, -DM)과 True Range를 계산합니다.

    Parameters:
    -----------
    df : pd.DataFrame
        OHLC 데이터프레임
    length : int
        평활 기간

    Returns:
    --------
    pd.DataFrame
        'plusDM', 'minusDM', 'tr' 컬럼이 추가된 데이터프레임
    """
    df['plusDM'] = df['high'].diff()
    df['minusDM'] = -df['low'].diff()

    df = calculate_tr(df)
    df['plusDM'] = rma(df['plusDM'], length) / df['tr'] * 100
    df['minusDM'] = rma(df['minusDM'], length) / df['tr'] * 100

    return df


def calculate_adx(df: pd.DataFrame, dilen: int = 28, adxlen: int = 28) -> pd.DataFrame:
    """
    ADX (Average Directional Index), +DI, -DI를 계산합니다.

    Parameters:
    -----------
    df : pd.DataFrame
        OHLC 데이터프레임 (high, low, close 컬럼 필요)
    dilen : int
        Directional Index 기간 (기본값 28)
    adxlen : int
        ADX 평활 기간 (기본값 28)

    Returns:
    --------
    pd.DataFrame
        'adx', 'plusDM', 'minusDM', 'tr', 'tr_ema', 'dm_plus_ema', 'dm_minus_ema',
        'di_diff', 'di_sum', 'dx' 컬럼이 추가된 데이터프레임
    """
    # True Range 계산
    if not isinstance(df, pd.DataFrame):
        raise TypeError(f"df is expected to be a pandas DataFrame, got {type(df)} instead.")

    df['tr'] = df[['high', 'close']].max(axis=1) - df[['low', 'close']].min(axis=1)

    # Directional Movement 계산
    df['plusDM'] = np.where((df['high'] - df['high'].shift(1)) > (df['low'].shift(1) - df['low']),
                            df['high'] - df['high'].shift(1), 0)
    df['plusDM'] = df['plusDM'].where(df['plusDM'] > 0, 0)

    df['minusDM'] = np.where((df['low'].shift(1) - df['low']) > (df['high'] - df['high'].shift(1)),
                             df['low'].shift(1) - df['low'], 0)
    df['minusDM'] = df['minusDM'].where(df['minusDM'] > 0, 0)

    # Exponential Moving Averages of TR, DM+ and DM-
    df['tr_ema'] = rma(df['tr'], dilen)
    df['dm_plus_ema'] = rma(df['plusDM'], dilen)
    df['dm_minus_ema'] = rma(df['minusDM'], dilen)

    # DI 계산
    df['plusDM'] = 100 * (df['dm_plus_ema'] / df['tr_ema'])
    df['minusDM'] = 100 * (df['dm_minus_ema'] / df['tr_ema'])

    # DI 차이와 합계 계산
    df['di_diff'] = abs(df['plusDM'] - df['minusDM'])
    df['di_sum'] = df['plusDM'] + df['minusDM']

    # DX 계산
    df['dx'] = 100 * (df['di_diff'] / df['di_sum'])

    # ADX 계산을 위한 RMA 사용
    df['adx'] = rma(df['dx'], adxlen)

    return df
