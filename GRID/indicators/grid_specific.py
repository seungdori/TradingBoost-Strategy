"""
GRID Strategy-specific ADX indicator logic
"""
import pandas as pd
from shared.indicators import crossover, crossunder, rising, falling


def compute_adx_state(plus, minus, sig, th):
    """
    ADX 상태를 계산합니다.

    Parameters:
    -----------
    plus : pd.Series
        +DI (Plus Directional Indicator)
    minus : pd.Series
        -DI (Minus Directional Indicator)
    sig : pd.Series
        ADX signal
    th : float
        Threshold 값

    Returns:
    --------
    int
        ADX state (-2, -1, 0, 1, 2)
    """
    th_series = pd.Series([th] * len(sig), index=sig.index)
    adx_state = 0

    # plus가 minus를 상향 돌파
    if crossover(plus, minus).any():
        adx_state = 1
    # 상태가 1이고 sig가 상승
    if adx_state == 1 and rising(sig, 2).any():
        adx_state = 2
    # minus가 plus를 상향 돌파
    if crossunder(minus, plus).any():
        adx_state = -1
    # 상태가 -1이고 sig가 상승
    if adx_state == -1 and rising(sig, 2).any():
        adx_state = -2
    # 상태가 0이 아니고 sig가 th 아래로 하락하거나 sig가 th보다 크면서 하락
    if adx_state != 0 and (crossunder(sig, th_series).any() or (falling(sig, 3).any() and (sig > th).any())):
        adx_state = 0

    return adx_state


def map_4h_adx_to_15m(df_4h: pd.DataFrame, df: pd.DataFrame) -> pd.DataFrame:
    """
    4시간봉 ADX 상태를 15분봉 데이터에 매핑합니다.

    Parameters:
    -----------
    df_4h : pd.DataFrame
        4시간봉 OHLCV 데이터 (adx_state 컬럼 포함)
    df : pd.DataFrame
        15분봉 OHLCV 데이터

    Returns:
    --------
    pd.DataFrame
        adx_state_4h 컬럼이 추가된 15분봉 데이터
    """
    # 4시간봉 데이터에 대한 시간 인덱스를 15분봉 데이터에 매핑하기 위한 준비
    # 15분봉 데이터에 'adx_state_4h' 컬럼 추가
    if not isinstance(df, pd.DataFrame):
        raise ValueError("ohlcv_data is not a DataFrame")
    if 'timestamp' not in df.columns:
        raise ValueError("'timestamp' column is missing from ohlcv_data")

    df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True).dt.tz_convert('Asia/Seoul')
    df_4h['timestamp'] = pd.to_datetime(df_4h['timestamp'], utc=True).dt.tz_convert('Asia/Seoul')
    df['adx_state_4h'] = 0

    # 각 4시간봉 데이터 포인트에 대해
    for i in range(len(df_4h)):
        # 현재 4시간봉 데이터 포인트의 timestamp
        current_timestamp = df_4h['timestamp'].iloc[i]

        # 다음 4시간봉 데이터 포인트의 timestamp (마지막 포인트의 경우 4시간 후로 설정)
        if i < len(df_4h) - 1:
            next_timestamp = df_4h['timestamp'].iloc[i + 1]
        else:
            next_timestamp = current_timestamp + pd.Timedelta(hours=4)

        # 15분봉 데이터에서 현재 4시간봉 구간에 해당하는 데이터 포인트 필터링
        mask = (df['timestamp'] >= current_timestamp) & (df['timestamp'] < next_timestamp)
        df.loc[mask, 'adx_state_4h'] = df_4h['adx_state'].iloc[i]

    return df


def update_adx_state(df: pd.DataFrame, th: int = 20) -> pd.DataFrame:
    """
    ADX 상태를 업데이트합니다.

    Parameters:
    -----------
    df : pd.DataFrame
        OHLCV 데이터프레임 (adx, plusDM, minusDM 컬럼 필요)
    th : int
        Threshold 값 (기본값 20)

    Returns:
    --------
    pd.DataFrame
        adx_state 컬럼이 업데이트된 데이터프레임
    """
    # 첫 번째 행에 대한 adx_state 초기화를 위한 컬럼 추가
    if 'adx_state' not in df.columns:
        df['adx_state'] = 0
    df['prev_adx_state'] = df['adx_state'].shift(1)

    # 50일 롤링 최고/최저가 계산
    df['rolling_high'] = df['high'].rolling(window=50).max()
    df['rolling_low'] = df['low'].rolling(window=50).min()

    # 상태 변화 후 대기 기간을 추적하는 변수 추가
    cooldown_period = 0
    cooldown_counter = 0

    # adx_state 업데이트 로직
    for i in range(1, len(df)):
        current_state = df.iloc[i-1]['adx_state']  # 이전 행의 adx_state 값을 현재 상태로 사용

        if cooldown_counter > 0:
            cooldown_counter -= 1
        elif current_state == 0:
            if df.iloc[i]['plusDM'] > df.iloc[i]['minusDM'] and df.iloc[i-1]['plusDM'] <= df.iloc[i-1]['minusDM']:
                current_state = 1
                cooldown_counter = cooldown_period
            elif df.iloc[i]['minusDM'] > df.iloc[i]['plusDM'] and df.iloc[i-1]['minusDM'] <= df.iloc[i-1]['plusDM']:
                current_state = -1
                cooldown_counter = cooldown_period
        elif current_state >= 1:
            if df.iloc[i]['adx'] > df.iloc[i-1]['adx'] and df.iloc[i-1]['adx'] > df.iloc[i-2]['adx']:
                current_state = 2
        elif current_state <= -1:
            if df.iloc[i]['adx'] > df.iloc[i-1]['adx'] and df.iloc[i-1]['adx'] > df.iloc[i-2]['adx']:
                current_state = -2

        # 새로운 조건 추가
        if current_state == -2 and df.iloc[i]['close'] >= df.iloc[i]['rolling_low'] * 1.1:
            current_state = 0
            cooldown_counter = cooldown_period
        elif current_state == 2 and df.iloc[i]['close'] <= df.iloc[i]['rolling_high'] * 0.9:
            current_state = 0
            cooldown_counter = cooldown_period

        if current_state != 0 and ((df.iloc[i]['adx'] < th and df.iloc[i-1]['adx'] >= th) or
                                   (df.iloc[i]['adx'] < df.iloc[i-1]['adx'] and
                                    df.iloc[i-1]['adx'] < df.iloc[i-2]['adx'] and
                                    df.iloc[i-2]['adx'] < df.iloc[i-3]['adx']) and
                                   df.iloc[i]['adx'] > th):
            current_state = 0
            cooldown_counter = cooldown_period

        df.at[df.index[i], 'adx_state'] = current_state  # 현재 계산된 상태를 현재 행에 할당

    # 불필요한 열 제거
    df = df.drop(['prev_adx_state', 'rolling_high', 'rolling_low'], axis=1)

    return df
