# -*- coding: utf-8 -*-

from math import e
import os
import sys
from datetime import datetime, timedelta
import datetime as dt
import pandas as pd
import asyncio
import pytz
import ccxt.async_support as ccxt  # noqa: E402
import random
import traceback
import numpy as np
from pathlib import Path
import aiohttp
import time
import logging
import psutil
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from GRID.trading.instance_manager import get_exchange_instance, start_cleanup_task
import fcntl
from dateutil import parser
from functools import lru_cache
from collections import defaultdict
from redis.asyncio import Redis
from GRID.database.redis_database import RedisConnectionManager
import json
import matplotlib.pyplot as plt
import redis
import ssl
from shared.config import OKX_API_KEY, OKX_SECRET_KEY, OKX_PASSPHRASE  # 환경 변수에서 키 가져오기
from shared.config import settings  # settings 추가
from shared.utils import retry_async

#================================================================
# REDIS
#================================================================
redis_manager = RedisConnectionManager()

# Redis 연결 설정
redis_client = redis.Redis(host=settings.REDIS_HOST, port=settings.REDIS_PORT, db=settings.REDIS_DB,
                           password=settings.REDIS_PASSWORD if settings.REDIS_PASSWORD else None)


#================================================================
# Semaphore
#================================================================

global_semaphore = asyncio.Semaphore(50)  # 전체 시스템에서 동시에 50개의 요청만 처리
symbol_semaphores = defaultdict(lambda: asyncio.Semaphore(10))  # 각 심볼당 최대 5개의 동시 요청


#================================================================
# 경로 설정
#================================================================
# Path to the directory where the fast api packaged binary is located
packaged_binary_dir = Path(sys.executable).parent

logs_dir = packaged_binary_dir / 'logs'


#================================================================
# T O O L S
#================================================================

MAX_RETRIES = 5
RETRY_DELAY = 3
# retry_async is now imported from shared.utils

from functools import wraps
import inspect

def profile_cpu_and_time(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        process = psutil.Process()
        start_time = time.time()
        start_cpu_time = process.cpu_times().user

        result = await func(*args, **kwargs)

        end_time = time.time()
        end_cpu_time = process.cpu_times().user

        cpu_usage = end_cpu_time - start_cpu_time
        wall_time = end_time - start_time

        print(f"Function: {func.__name__}")
        print(f"Wall time: {wall_time:.4f} seconds")
        print(f"CPU time: {cpu_usage:.4f} seconds")
        print(f"CPU usage percentage: {(cpu_usage / wall_time) * 100:.2f}%")

        return result

    return wrapper


# 파일 잠금을 위한 함수
def lock_file(file_path, timeout=10):
    start_time = time.time()
    while True:
        try:
            file_handle = open(file_path, 'r+')
            fcntl.flock(file_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return file_handle
        except IOError:
            if time.time() - start_time > timeout:
                raise TimeoutError("Could not acquire lock")
            time.sleep(0.1)

# 캐시 함수 (메모리에 결과를 저장)
@lru_cache(maxsize=200)  # 캐시 크기를 늘림
def get_cached_data(file_path, timestamp):
    """
    파일 경로와 타임스탬프를 기반으로 캐시된 데이터를 반환합니다.
    """
    return pd.read_csv(file_path) if os.path.exists(file_path) else None

@lru_cache(maxsize=50)
def parse_timeframe_to_ms(timeframe):
    """
    타임프레임 문자열을 밀리초 단위로 변환합니다.
    예: '1m' -> 60000, '1h' -> 3600000, '1d' -> 86400000
    """
    if timeframe.endswith('m'):
        return int(timeframe[:-1]) * 60 * 1000
    elif timeframe.endswith('h'):
        return int(timeframe[:-1]) * 60 * 60 * 1000
    elif timeframe.endswith('d'):
        return int(timeframe[:-1]) * 24 * 60 * 60 * 1000
    elif timeframe.endswith('w'):
        return int(timeframe[:-1]) * 7 * 24 * 60 * 60 * 1000
    else:
        raise ValueError(f"지원하지 않는 타임프레임 형식: {timeframe}")



def run_periodic_analysis(exchange):
    # asyncio.run을 사용하여 비동기 함수를 동기 환경에서 실행
    return asyncio.run(periodic_analysis(exchange))

def run_async_in_thread(coro):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)

#================================================================================================
# C A L C U L A T I O N S
#================================================================================================
def convert_timestamp_millis_to_readable(timestamp_millis):
    """
    Converts a timestamp in milliseconds to a readable date-time string.

    Args:
        timestamp_millis (int): The timestamp in milliseconds.

    Returns:
        str: The readable date-time string in the format 'YYYY-MM-DD HH:MM:SS'.
    """
    # 타임스탬프를 초 단위로 변환
    timestamp_seconds = timestamp_millis / 1000
    # datetime 객체로 변환
    date_time = datetime.fromtimestamp(timestamp_seconds)
    # 인간이 읽을 수 있는 형식으로 변환
    readable_date_time = date_time.strftime('%Y-%m-%d %H:%M:%S')
    return readable_date_time


PI = 2 * np.arcsin(1)

def hilbert_transform(src):
    return 0.0962 * src + 0.5769 * np.roll(src, 2) - 0.5769 * np.roll(src, 4) - 0.0962 * np.roll(src, 6)

# Define compute_component function
def compute_component(src, mesa_period_mult):
    return hilbert_transform(src) * mesa_period_mult


# Define compute_alpha function
def compute_alpha(src, er, er_ratio, prev_mesa_period, prev_I2, prev_Q2, prev_Re, prev_Im, prev_phase):
    smooth = (4 * src + 3 * np.roll(src, 1) + 2 * np.roll(src, 2) + np.roll(src, 3)) / 10
    mesa_period_mult = 0.075 * np.roll(prev_mesa_period, 1) + 0.54
    detrender = compute_component(smooth, mesa_period_mult)
    
    I1 = np.roll(detrender, 3)
    Q1 = compute_component(detrender, mesa_period_mult)
    
    jI = compute_component(I1, mesa_period_mult)
    jQ = compute_component(Q1, mesa_period_mult)
    
    I2 = I1 - jQ
    Q2 = Q1 + jI
    
    I2 = 0.2 * I2 + 0.8 * np.roll(I2, 1)
    Q2 = 0.2 * Q2 + 0.8 * np.roll(Q2, 1)
    
    Re = I2 * np.roll(I2, 1) + Q2 * np.roll(Q2, 1)
    Im = I2 * np.roll(Q2, 1) - Q2 * np.roll(I2, 1)
    
    Re = 0.2 * Re + 0.8 * np.roll(Re, 1)
    Im = 0.2 * Im + 0.8 * np.roll(Im, 1)
    
    mesa_period = np.zeros_like(src)
    if np.any(Re != 0) and np.any(Im != 0):
        mesa_period = 2 * PI / np.arctan(Im / Re)
    
    mesa_period = np.where(mesa_period > 1.5 * np.roll(mesa_period, 1), 1.5 * np.roll(mesa_period, 1), mesa_period)
    mesa_period = np.where(mesa_period < 0.67 * np.roll(mesa_period, 1), 0.67 * np.roll(mesa_period, 1), mesa_period)
    mesa_period = np.clip(mesa_period, 6, 50)
    mesa_period = 0.2 * mesa_period + 0.8 * np.roll(mesa_period, 1)
    
    phase = np.zeros_like(src)
    if np.any(I1 != 0):
        phase = 180 / PI * np.arctan(Q1 / I1)
    
    delta_phase = np.roll(phase, 1) - phase
    delta_phase = np.where(delta_phase < 1, 1, delta_phase)
    
    alpha = er / delta_phase
    alpha = np.where(alpha < er_ratio, er_ratio, alpha)
    
    return alpha, alpha / 2.0, mesa_period, I2, Q2, Re, Im, phase


# Define the function to compute MAMA and FAMA
def compute_mama_fama(src, length=20):

    # Initialize variables
    mama = np.zeros_like(src)
    fama = np.zeros_like(src)
    mesa_period = np.zeros_like(src)
    I2 = np.zeros_like(src)
    Q2 = np.zeros_like(src)
    Re = np.zeros_like(src)
    Im = np.zeros_like(src)
    phase = np.zeros_like(src)
    
    # Calculate MAMA and FAMA
    for i in range(len(src)):
        if i < length:
            # Not enough data to compute ER yet
            er = 0
        else:
            diff_sum = np.sum(np.abs(np.diff(src.iloc[i-length:i+1])))
            if diff_sum == 0:  # Prevent division by zero
                er = 0
            else:
                er = np.abs(src.iloc[i] - src.iloc[i - length]) / np.sum(np.abs(np.diff(src.iloc[i-length:i+1])))
        
        alpha, beta, mesa_period, I2, Q2, Re, Im, phase = compute_alpha(
            np.array([src.iloc[i]]), er, er * 0.1, mesa_period, I2, Q2, Re, Im, phase
        )
        mama[i] = alpha[0] * src.iloc[i] + (1 - alpha[0]) * (mama[i-1] if i > 0 else src.iloc[i])
        fama[i] = beta[0] * mama[i] + (1 - beta[0]) * (fama[i-1] if i > 0 else mama[i])
    # Compute EMA for MAMA and FAMA using ewm
    # Convert to pandas Series to use ewm
    mama_series = pd.Series(mama)
    fama_series = pd.Series(fama)
    mama = mama_series.ewm(span=5, adjust=False).mean().values
    fama = fama_series.ewm(span=5, adjust=False).mean().values
    return mama, fama

def compute_ema(series, length):
    ema = np.zeros_like(series)
    alpha = 2 / (length + 1)
    
    for i in range(len(series)):
        if i == 0:
            ema[i] = series[i]
        else:
            ema[i] = alpha * series[i] + (1 - alpha) * ema[i-1]
    
    return ema


def atr(df, length=14):
    """
    Average True Range (ATR)을 계산합니다.
    
    :param high: 고가를 나타내는 pandas Series
    :param low: 저가를 나타내는 pandas Series
    :param close: 종가를 나타내는 pandas Series
    :param length: ATR을 계산하기 위한 기간
    :return: ATR 값을 포함하는 pandas Series
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
    df['atr'] = atr_values  # 여기를 수정하여 열 이름을 'atr'로 명확하게 지정
    return df

def calculate_tr(df):

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

def rma(src, length):

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

def crossover(series1, series2):
    #print(type(series1), type(series2))  # `crossunder` 함수 내부에서 이를 출력
    """시리즈1이 시리즈2를 상향 돌파하는지 확인"""
    return (series1 > series2) & (series1.shift() < series2.shift())

def crossunder(series1, series2):
    #print(type(series1), type(series2))  # `crossunder` 함수 내부에서 이를 출력
    """시리즈1이 시리즈2를 하향 돌파하는지 확인"""
    return (series1 < series2) & (series1.shift() > series2.shift())

def rising(series, periods=2):
    """시리즈가 지정된 기간 동안 상승하는지 확인"""
    return series.diff(periods=periods) > 0

def falling(series, periods=3):
    """시리즈가 지정된 기간 동안 하락하는지 확인"""
    return series.diff(periods=periods) < 0

def calculate_dm_tr(df, length):
    df['plusDM'] = df['high'].diff()
    df['minusDM'] = -df['low'].diff()
    #df['plusDM'] = df.apply(lambda row: row['plusDM'] if row['plusDM'] > row['minusDM'] and row['plusDM'] > 0 else 0, axis=1)
    #df['minusDM'] = df.apply(lambda row: row['minusDM'] if row['minusDM'] > row['plusDM'] and row['minusDM'] > 0 else 0, axis=1)
    df = calculate_tr(df) 
    df['plusDM'] = rma(df['plusDM'], length) / df['tr'] * 100
    df['minusDM'] = rma(df['minusDM'], length) / df['tr'] * 100
    return df

def calculate_adx(df, dilen=28, adxlen=28):
    # True Range 계산
    if not isinstance(df, pd.DataFrame):
        raise TypeError(f"df is expected to be a pandas DataFrame, got {type(df)} instead.")

    df['tr'] = df[['high', 'close']].max(axis=1) - df[['low', 'close']].min(axis=1)
    
    # Directional Movement 계산
    df['plusDM'] = np.where((df['high'] - df['high'].shift(1)) > (df['low'].shift(1) - df['low']), df['high'] - df['high'].shift(1), 0)
    df['plusDM'] = df['plusDM'].where(df['plusDM'] > 0, 0)
    
    df['minusDM'] = np.where((df['low'].shift(1) - df['low']) > (df['high'] - df['high'].shift(1)), df['low'].shift(1) - df['low'], 0)
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
      # 필요없는 임시 열 삭제
    #df.drop(['tr', 'dm_plus', 'dm_minus', 'di_diff', 'di_sum', 'dx'], axis=1, inplace=True)
      
    return df



def compute_adx_state(plus, minus, sig, th):
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


def map_4h_adx_to_15m(df_4h, df):
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




def update_adx_state(df, th=20):
    # 첫 번째 행에 대한 adx_state 초기화를 위한 컬럼 추가
    if 'adx_state' not in df.columns:
        df['adx_state'] = 0
    df['prev_adx_state'] = df['adx_state'].shift(1)
    
    # 30일 롤링 최고/최저가 계산
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

def initialize_orders(df, n_levels=20):
    # 주문 초기화
    data = {f'order_{n}': False for n in range(1, n_levels + 1)}
    data.update({f'order_{n}_quantity': 0.0 for n in range(1, n_levels + 1)})
    data.update({f'order_{n}_entry_price': 0.0 for n in range(1, n_levels + 1)})
    data.update({f'order_{n}_profit': 0.0 for n in range(1, n_levels + 1)})
    data['total_matched_orders'] = 0.0
    data['total_position'] = 0.0
    data['avg_entry_price'] = 0.0   
    data['unrealized_profit'] = 0.0
    data['total_profit'] = 0.0  # 총 수익 열 초기화

    orders_df = pd.DataFrame(data, index=df.index)
    df = pd.concat([df, orders_df], axis=1).copy()  # 조각화 감소를 위해 copy 사용
    return df


def calculate_grid_levels(df, band_mult=0.5, n_levels=20, min_diff=0.004):
    # 그리드 레벨 계산
    grid_levels = {}
    main_plot = df['main_plot']
    atr = np.maximum(df['atr'], main_plot * min_diff)
    
    for n in range(0, n_levels + 1):
        atr_mult = atr * (11 - n) * 1.5
        multiplier = 1 - band_mult * 0.012 * (11 - n)
        grid_level_perc = (main_plot * multiplier).ewm(span=5, adjust=False).mean()
        grid_level_atr = (main_plot - atr_mult).ewm(span=5, adjust=False).mean()
        grid_level = (grid_level_perc + grid_level_atr) / 2
        
        diff = (main_plot - grid_level) / main_plot
        max_gap = min(0.05 * abs(11 - n), 0.5)
        
        # 이전 그리드 레벨과의 차이 확인
        if n > 1:
            prev_level = grid_levels[f'grid_level_{n-1}']
            diff = (grid_level - prev_level) / prev_level
        
            # 차이가 최대 간격(max_gap)을 초과하는 경우 조정
            mask = abs(diff) > max_gap
            grid_level[mask] = np.where(diff[mask] > 0, 
                                        main_plot[mask] * (1 - max_gap), 
                                        main_plot[mask] * (1 + max_gap))
        
            # 차이가 최소 차이(min_diff) 미만인 경우 조정
            mask = abs(diff) < min_diff
            grid_level[mask] = np.where(diff[mask] > 0, prev_level[mask] * (1 + min_diff), prev_level[mask] * (1 - min_diff))
        
        
        
        
        grid_levels[f'grid_level_{n}'] = round(grid_level, 8)

    grid_levels_df = pd.DataFrame(grid_levels)
    grid_level_adjusted = grid_levels_df.ewm(span=5, adjust=False).mean()
    # 데이터프레임 병합을 한 번에 수행
    new_df = pd.concat([df, grid_level_adjusted], axis=1)
    
    return new_df


def execute_trading_logic(df, initial_capital, direction):
    # 거래 로직 실행

    df = df.reset_index(drop=True)
    temp_df = df.copy()  # 임시 데이터프레임 생성
    unrealized_profit = 0.0  # 미실현 수익 변수 초기화
    total_position = 0.0  # 총 포지션 변수 초기화
    total_matched_orders = 0  # 총 매칭된 주문 변수 초기화
    total_quantity = 0.0  # 총 수량 변수 초기화
    total_profit = 0.0  # 누적 수익 변수 초기화
    avg_entry_price = 0.0  # 평균 진입 가격 변수 초기화
    total_weighted_price = 0.0  # 가중 평균 가격 변수 초기화
    for i in range(1, len(df)):
        exceeds_top_grid = df['high'].iloc[i] > df['grid_level_20'].iloc[i]
        exceeds_bottom_grid = df['low'].iloc[i] < df['grid_level_1'].iloc[i]
        adx_state = df['adx_state_4h'].iloc[i]
        last_adx_state = df['adx_state_4h'].iloc[i-1]
        
        #================================================================================================
        # 롱 포지션 거래 로직#
        #================================================================================================    
        if direction == 'long':
            for n in range(1, 21):

                current_zone = df[f'grid_level_{n}'].iloc[i]
                last_current_zone = df[f'grid_level_{n}'].iloc[i-1]
                if n <= 18:
                    if adx_state < 2 :
                        exit_zone = df[f'grid_level_{n+2}'].iloc[i] if f'grid_level_{n+2}' in df.columns else current_zone*1.005
                    if adx_state >= 2 and n < 18:
                        exit_zone = df[f'grid_level_{n+3}'].iloc[i] if f'grid_level_{n+3}' in df.columns else current_zone*1.005
                    elif adx_state >= 2 and n >= 18:
                        exit_zone = df[f'grid_level_{n}'].iloc[i]*1.01 if f'grid_level_{n}' in df.columns else current_zone*1.005
                elif n >= 19:
                    if adx_state < 2:
                        exit_zone = df[f'grid_level_{n}'].iloc[i]*1.005 if f'grid_level_{n}' in df.columns else current_zone*1.005
                    elif adx_state >= 2:
                        exit_zone = df[f'grid_level_{n}'].iloc[i]*1.01 if f'grid_level_{n}' in df.columns else current_zone*1.005
                if exceeds_top_grid :
                    if temp_df.at[df.index[i-1], f'order_{n}'] :
                        temp_df.at[df.index[i], f'order_{n}'] = False
                        temp_df.at[df.index[i], f'order_{n}_profit'] = float(temp_df.at[df.index[i-1], f'order_{n}_quantity'] * df['high'].iloc[i]) - float(temp_df.at[df.index[i-1], f'order_{n}_quantity'] * temp_df.at[df.index[i-1], f'order_{n}_entry_price'])
                        temp_df.at[df.index[i], f'order_{n}_quantity'] = 0
                        temp_df.at[df.index[i], f'order_{n}_entry_price'] = 0
                try:
                    value = temp_df.at[df.index[i-1], f'order_{n}']
                                # 값이 Series인 경우에만 출력
                    if isinstance(value, pd.Series):
                        print(f"Value at index {df.index[i-1]} and column 'order_{n}': {value}")
                        print(f"Type of the value: {type(value)}")

                    if not temp_df.at[df.index[i-1], f'order_{n}'] and adx_state >= -1: #롱포지션이 없을 때, adx_state가 -1보다 같거나 크면 포지션 진입
                        if df['low'].iloc[i] < current_zone and df['low'].iloc[i-1] > last_current_zone:
                            temp_df.at[df.index[i], f'order_{n}'] = True
                            temp_df.at[df.index[i], f'order_{n}_entry_price'] = current_zone
                            if temp_df.at[df.index[i], f'order_{n}_entry_price'] != 0:
                                temp_df.at[df.index[i], f'order_{n}_quantity'] = float((initial_capital / 20) / temp_df.at[df.index[i], f'order_{n}_entry_price'])
                    elif temp_df.at[df.index[i-1], f'order_{n}'] and adx_state < -1: #롱포지션이 있을 때, adx_state가 -1보다 작아지면 포지션 종료
                        temp_df.at[df.index[i], f'order_{n}'] = False
                        temp_df.at[df.index[i], f'order_{n}_profit'] = float(temp_df.at[df.index[i-1], f'order_{n}_quantity'] * df['close'].iloc[i]) - float(temp_df.at[df.index[i-1], f'order_{n}_quantity'] * temp_df.at[df.index[i-1], f'order_{n}_entry_price'])
                        temp_df.at[df.index[i], f'order_{n}_quantity'] = 0
                        temp_df.at[df.index[i], f'order_{n}_entry_price'] = 0
                        temp_df.at[df.index[i], 'total_matched_orders'] += 1
                    elif temp_df.at[df.index[i-1], f'order_{n}'] and df['high'].iloc[i] > exit_zone: # 포지션이 있을 때, 익절. 그리고 adx_state가 2일 때는 익절을 하지 않고, 1 이하일 때만 익절.
                        temp_df.at[df.index[i], f'order_{n}'] = False
                        temp_df.at[df.index[i], f'order_{n}_profit'] = float(temp_df.at[df.index[i-1], f'order_{n}_quantity'] * df['high'].iloc[i]) - float(temp_df.at[df.index[i-1], f'order_{n}_quantity'] * temp_df.at[df.index[i-1], f'order_{n}_entry_price'])
                        temp_df.at[df.index[i], f'order_{n}_quantity'] = 0
                        temp_df.at[df.index[i], f'order_{n}_entry_price'] = 0
                        temp_df.at[df.index[i], 'total_matched_orders'] += 1    
                    else: #어떠한 조건도 만족하지 않을 때는 포지션 유지.
                        temp_df.at[df.index[i], f'order_{n}'] = temp_df.at[df.index[i-1], f'order_{n}']
                        temp_df.at[df.index[i], f'order_{n}_quantity'] = temp_df.at[df.index[i-1], f'order_{n}_quantity']
                        temp_df.at[df.index[i], f'order_{n}_entry_price'] = temp_df.at[df.index[i-1], f'order_{n}_entry_price']
                    if temp_df.at[df.index[i], f'order_{n}']:
                        quantity = temp_df.at[df.index[i], f'order_{n}_quantity']
                        entry_price = temp_df.at[df.index[i], f'order_{n}_entry_price']
                        total_quantity += quantity
                        total_weighted_price += quantity * entry_price
                        total_position += quantity * df['close'].iloc[i]
                except Exception as e:
                    print(e)
                    print('Error in long position logic')
                    traceback.print_exc()
                    
                if total_quantity > 0:
                    avg_entry_price = total_weighted_price / total_quantity
                else:
                    avg_entry_price = 0
                unrealized_profit = total_position - (total_quantity * avg_entry_price)
                temp_df.at[df.index[i], 'avg_entry_price'] = avg_entry_price
                temp_df.at[df.index[i], 'unrealized_profit'] = unrealized_profit
                temp_df.at[df.index[i], 'total_position'] = total_position
                total_profit += temp_df.at[df.index[i], f'order_{n}_profit']
                temp_df.at[df.index[i], 'total_profit'] = (float(total_profit)/10)  # 누적 수익을 현재 행의 'total_profit'에 할당
                #total_profit += temp_df.at[df.index[i], f'order_{n}_profit']  # 각 열의 수익을 누적 수익에 더함
                #temp_df.at[df.index[i], 'total_profit'] = total_profit  # 누적 수익을 현재 행의 'total_profit'에 할당

        #================================================================================================
        # 숏 포지션 거래 로직#
        #================================================================================================
        elif direction == 'short':
            for n in range(1, 21):
                current_zone = df[f'grid_level_{n}'].iloc[i]
                last_current_zone = df[f'grid_level_{n}'].iloc[i-1]
                if n >= 3:
                    if adx_state > -2:
                        exit_zone = df[f'grid_level_{n-2}'].iloc[i] if f'grid_level_{n-2}' in df.columns else current_zone * 0.993
                    if adx_state <= -2 and n > 3:
                        exit_zone = df[f'grid_level_{n-3}'].iloc[i] if f'grid_level_{n-3}' in df.columns else current_zone * 0.993
                    else:
                        exit_zone = df[f'grid_level_{n}'].iloc[i]*0.993 if f'grid_level_{n}' in df.columns else current_zone * 0.993
                elif n <= 2:
                    exit_zone = df[f'grid_level_{n}'].iloc[i]*0.993 if f'grid_level_{n-1}' in df.columns else current_zone * 0.993
                if exceeds_bottom_grid: # 가격이 최하위 그리드를 돌파하면, 포지션 종료
                    if temp_df.at[df.index[i-1], f'order_{n}']:
                        temp_df.at[df.index[i], f'order_{n}'] = False
                        #TODO :quantity는 음수인데, 아래의 order_profit이 어떻게 계산되는지, 직접 데이터프레임을 뽑아본 다음에 확인. <-- 근데, 맞는 것 같다 지금 아래가. 
                        temp_df.at[df.index[i], f'order_{n}_profit'] = float(temp_df.at[df.index[i-1], f'order_{n}_quantity'] * df['low'].iloc[i]) - float(temp_df.at[df.index[i-1], f'order_{n}_quantity'] * temp_df.at[df.index[i-1], f'order_{n}_entry_price'])
                        temp_df.at[df.index[i], f'order_{n}_quantity'] = 0
                        temp_df.at[df.index[i], f'order_{n}_entry_price'] = 0
                        temp_df.at[df.index[i], 'total_matched_orders'] += 1
                elif not temp_df.at[df.index[i-1], f'order_{n}'] and adx_state <= 1: #숏포지션이 없을 때, adx_state가 1보다 같거나 작으면 포지션 진입
                    if df['high'].iloc[i] > current_zone and df['high'].iloc[i-1] < last_current_zone:
                        temp_df.at[df.index[i], f'order_{n}'] = True
                        temp_df.at[df.index[i], f'order_{n}_entry_price'] = current_zone
                        if temp_df.at[df.index[i], f'order_{n}_entry_price'] != 0:
                            temp_df.at[df.index[i], f'order_{n}_quantity'] = -1 * float((initial_capital / 20) / temp_df.at[df.index[i], f'order_{n}_entry_price'])
                elif temp_df.at[df.index[i-1], f'order_{n}'] and adx_state > 1: #숏포지션이 있을 때, adx_state가 1보다 크면 포지션 종료
                    temp_df.at[df.index[i], f'order_{n}'] = False
                    temp_df.at[df.index[i], f'order_{n}_profit'] = float(temp_df.at[df.index[i-1], f'order_{n}_quantity'] * df['close'].iloc[i]) - float(temp_df.at[df.index[i-1], f'order_{n}_quantity'] * temp_df.at[df.index[i-1], f'order_{n}_entry_price'])
                    temp_df.at[df.index[i], f'order_{n}_quantity'] = 0
                    temp_df.at[df.index[i], f'order_{n}_entry_price'] = 0
                    temp_df.at[df.index[i], 'total_matched_orders'] += 1
                elif temp_df.at[df.index[i-1], f'order_{n}'] and df['low'].iloc[i] < exit_zone: #숏포지션이 있을 때, 익절. 그리고 adx_state가 0보다 크면 숏진입을 하지 않는다. 0일 때는 익절을 한다.
                    temp_df.at[df.index[i], f'order_{n}'] = False
                    temp_df.at[df.index[i], f'order_{n}_profit'] = float(temp_df.at[df.index[i-1], f'order_{n}_quantity'] * df['low'].iloc[i]) - float(temp_df.at[df.index[i-1], f'order_{n}_quantity'] * temp_df.at[df.index[i-1], f'order_{n}_entry_price'])
                    temp_df.at[df.index[i], f'order_{n}_quantity'] = 0
                    temp_df.at[df.index[i], f'order_{n}_entry_price'] = 0
                    temp_df.at[df.index[i], 'total_matched_orders'] += 1
                else: #어떠한 조건도 만족하지 않을 때는 포지션 유지.
                    temp_df.at[df.index[i], f'order_{n}'] = temp_df.at[df.index[i-1], f'order_{n}']
                    temp_df.at[df.index[i], f'order_{n}_quantity'] = temp_df.at[df.index[i-1], f'order_{n}_quantity']
                    temp_df.at[df.index[i], f'order_{n}_entry_price'] = temp_df.at[df.index[i-1], f'order_{n}_entry_price']
                #entry_정보
                if temp_df.at[df.index[i], f'order_{n}']:
                    quantity = temp_df.at[df.index[i], f'order_{n}_quantity']
                    entry_price = temp_df.at[df.index[i], f'order_{n}_entry_price']
                    total_quantity += quantity
                    total_weighted_price += quantity * entry_price
                    total_position += quantity * df['close'].iloc[i]                

                unrealized_profit = total_position - (total_quantity * avg_entry_price)
                temp_df.at[df.index[i], 'avg_entry_price'] = avg_entry_price
                temp_df.at[df.index[i], 'unrealized_profit'] = unrealized_profit
                if total_quantity < 0:
                    avg_entry_price = total_weighted_price / total_quantity
                else:
                    avg_entry_price = 0
                total_profit += temp_df.at[df.index[i], f'order_{n}_profit']  # 각 열의 수익을 누적 수익에 더함
                total_position = temp_df.at[df.index[i], f'order_{n}_quantity'] * df['close'].iloc[i]
                temp_df.at[df.index[i], 'total_profit'] = (float(total_profit)/10)  # 누적 수익을 현재 행의 'total_profit'에 할당
                temp_df.at[df.index[i], 'total_position'] = total_position  # 누적 포지션을 현재 행의 'total_position'에 할당
        #================================================================================================
        # 양방향 포지션 거래 로직#
        #TODO : 양방향 포지션 거래 로직이 제대로 작동하는지 확인 필요. 반드시.
        #TODO : 반드시! 
        #================================================================================================   
        else: # direction == 'both'일 때
            for n in range(1, 21):
                current_zone = df[f'grid_level_{n}'].iloc[i]
                last_current_zone = df[f'grid_level_{n}'].iloc[i-1]
                if n == 20:
                    if adx_state == 2:
                        short_exit_zone = df['grid_level_18'].iloc[i] if 'grid_level_18' in df.columns else current_zone * 0.993
                        long_exit_zone = df['grid_level_20'].iloc[i] * 1.007 if 'grid_level_20' in df.columns else current_zone * 1.007
                    elif adx_state == -2:
                        short_exit_zone = df['grid_level_17'].iloc[i] if 'grid_level_17' in df.columns else current_zone * 0.993
                        long_exit_zone = df['grid_level_20'].iloc[i] * 1.007 if 'grid_level_20' in df.columns else current_zone * 1.007
                    else:
                        short_exit_zone = df['grid_level_17'].iloc[i] if 'grid_level_17' in df.columns else current_zone * 0.993
                        long_exit_zone = df['grid_level_20'].iloc[i] * 1.007 if 'grid_level_20' in df.columns else current_zone * 1.007
                elif n == 2:
                    if adx_state == 2:
                        long_exit_zone = df['grid_level_4'].iloc[i] if 'grid_level_4' in df.columns else current_zone * 1.007
                        short_exit_zone = df['grid_level_1'].iloc[i] if 'grid_level_1' in df.columns else current_zone * 0.993
                    elif adx_state == -2:   
                        long_exit_zone = df['grid_level_3'].iloc[i] if 'grid_level_3' in df.columns else current_zone * 1.007
                        short_exit_zone = df['grid_level_1'].iloc[i]*0.995 if 'grid_level_1' in df.columns else current_zone * 0.993
                    else:
                        long_exit_zone = df['grid_level_3'].iloc[i] if 'grid_level_3' in df.columns else current_zone * 1.007
                        short_exit_zone = df['grid_level_1'].iloc[i] if 'grid_level_1' in df.columns else current_zone * 0.993
                elif n == 1:
                    if adx_state == 2:
                        long_exit_zone = df['grid_level_4'].iloc[i] if 'grid_level_3' in df.columns else current_zone * 1.007
                        short_exit_zone = df['grid_level_1'].iloc[i] * 0.993 if 'grid_level_1' in df.columns else current_zone*0.993
                    elif adx_state == -2:
                        long_exit_zone = df['grid_level_3'].iloc[i] if 'grid_level_3' in df.columns else current_zone * 1.007
                        short_exit_zone = df['grid_level_1'].iloc[i] * 0.993 if 'grid_level_1' in df.columns else current_zone * 0.993
                    else:
                        long_exit_zone = df['grid_level_3'].iloc[i] if 'grid_level_3' in df.columns else current_zone * 1.007
                        short_exit_zone = df['grid_level_1'].iloc[i] if 'grid_level_1' in df.columns else current_zone * 0.993
                elif n == 19:
                    if adx_state == 2:
                        long_exit_zone = df['grid_level_20'].iloc[i] if 'grid_level_20' in df.columns else current_zone * 1.007
                        short_exit_zone = df['grid_level_17'].iloc[i] if 'grid_level_17' in df.columns else current_zone * 0.993
                    elif adx_state == -2:
                        long_exit_zone = df['grid_level_20'].iloc[i] if 'grid_level_20' in df.columns else current_zone * 1.014
                        short_exit_zone = df['grid_level_16'].iloc[i] if 'grid_level_16' in df.columns else current_zone * 0.986
                    else:
                        long_exit_zone = df['grid_level_20'].iloc[i] if 'grid_level_20' in df.columns else current_zone * 1.007
                        short_exit_zone = df['grid_level_17'].iloc[i] if 'grid_level_17' in df.columns else current_zone * 0.993
                else:
                    if adx_state >= 2:
                        long_exit_zone = df[f'grid_level_{n+3}'].iloc[i] if f'grid_level_{n+3}' in df.columns else current_zone * 1.007
                        short_exit_zone = df[f'grid_level_{n-2}'].iloc[i] if f'grid_level_{n-2}' in df.columns else current_zone * 0.993
                    elif adx_state <= -2:
                        long_exit_zone = df[f'grid_level_{n+2}'].iloc[i] if f'grid_level_{n+2}' in df.columns else current_zone * 1.007
                        short_exit_zone = df[f'grid_level_{n-3}'].iloc[i] if f'grid_level_{n-3}' in df.columns else current_zone * 0.993
                    else:
                        long_exit_zone = df[f'grid_level_{n+2}'].iloc[i] if f'grid_level_{n+2}' in df.columns else current_zone * 1.007
                        short_exit_zone = df[f'grid_level_{n-2}'].iloc[i] if f'grid_level_{n-2}' in df.columns else current_zone * 0.993

                # 롱 포지션과 숏 포지션의 exit_zone 설정

                # 롱 포지션 진입
                if df['low'].iloc[i] < current_zone and adx_state >= -1 and df['low'].iloc[i-1] > last_current_zone :
                    if not (temp_df.at[df.index[i-1], f'order_{n}']): #<-- 포지션이 없었을 때
                        temp_df.at[df.index[i], f'order_{n}'] = True
                        temp_df.at[df.index[i], f'order_{n}_entry_price'] = current_zone
                        if temp_df.at[df.index[i], f'order_{n}_entry_price'] != 0:
                            temp_df.at[df.index[i], f'order_{n}_quantity'] = float((initial_capital / 20) / temp_df.at[df.index[i], f'order_{n}_entry_price'])
                    if (temp_df.at[df.index[i-1], f'order_{n}']  and temp_df.at[df.index[i-1], f'order_{n}_quantity'] < 0):
                        profit = temp_df.at[df.index[i-1], f'order_{n}_quantity'] * (temp_df.at[df.index[i-1], f'order_{n}_entry_price'] - df['low'].iloc[i])
                        temp_df.at[df.index[i], f'order_{n}_profit'] += profit
                        temp_df.at[df.index[i], f'order_{n}'] = False
                        temp_df.at[df.index[i], f'order_{n}_entry_price'] = 0
                        temp_df.at[df.index[i], f'order_{n}_quantity'] = 0
                        temp_df.at[df.index[i], 'total_matched_orders'] += 1
                # 롱 포지션 청산 또는 익절
                if temp_df.at[df.index[i-1], f'order_{n}_quantity'] > 0 :  # 롱 포지션이 있을 때
                    if long_exit_zone is not None and temp_df.at[df.index[i-1], f'order_{n}']  and df['high'].iloc[i] > long_exit_zone:  # 익절 조건
                        profit = temp_df.at[df.index[i-1], f'order_{n}_quantity'] * (df['high'].iloc[i] - temp_df.at[df.index[i-1], f'order_{n}_entry_price'])
                        temp_df.at[df.index[i], f'order_{n}_profit'] += profit
                        temp_df.at[df.index[i], f'order_{n}'] = False
                        temp_df.at[df.index[i], f'order_{n}_quantity'] = 0
                        temp_df.at[df.index[i], f'order_{n}_entry_price'] = 0
                        temp_df.at[df.index[i], 'total_matched_orders'] += 1
                    if adx_state == -2 and last_adx_state >= -1 and temp_df.at[df.index[i-1], f'order_{n}'] :  #롱 포지션 종료 조건. adx가 0 미만이면 종료
                        temp_df.at[df.index[i], f'order_{n}'] = False
                        profit = temp_df.at[df.index[i-1], f'order_{n}_quantity'] * (df['close'].iloc[i] - temp_df.at[df.index[i-1], f'order_{n}_entry_price'])
                        temp_df.at[df.index[i], f'order_{n}_profit'] += profit
                        temp_df.at[df.index[i], f'order_{n}_quantity'] = 0
                        temp_df.at[df.index[i], 'total_matched_orders'] += 1
                if (not (temp_df.at[df.index[i-1], f'order_{n}']  and adx_state <= 1) or (temp_df.at[df.index[i-1], f'order_{n}']  and temp_df.at[df.index[i-1], f'order_{n}_quantity'] > 0)) :
                    if df['high'].iloc[i] > current_zone and  df['high'].iloc[i-1] < last_current_zone:
                        if (not temp_df.at[df.index[i-1], f'order_{n}'] ): #롱포지션이 없을 때
                            temp_df.at[df.index[i], f'order_{n}'] = True
                            temp_df.at[df.index[i], f'order_{n}_entry_price'] = current_zone
                            if temp_df.at[df.index[i], f'order_{n}_entry_price'] != 0:
                                temp_df.at[df.index[i], f'order_{n}_quantity'] = -1 * float((initial_capital / 20) / temp_df.at[df.index[i], f'order_{n}_entry_price'])
                        if (temp_df.at[df.index[i-1], f'order_{n}']  and temp_df.at[df.index[i-1], f'order_{n}_quantity'] > 0): #롱포지션이 있을 때
                            temp_df.at[df.index[i], f'order_{n}'] = False #롱포지션 청산
                            profit = temp_df.at[df.index[i-1], f'order_{n}_quantity'] * (df['high'].iloc[i] - temp_df.at[df.index[i-1], f'order_{n}_entry_price'])
                            temp_df.at[df.index[i], f'order_{n}_profit'] += profit
                            temp_df.at[df.index[i], f'order_{n}_quantity'] = 0
                            temp_df.at[df.index[i], f'order_{n}_entry_price'] = 0
                            temp_df.at[df.index[i], 'total_matched_orders'] += 1
                            
                            
                # 숏 포지션 청산
                elif temp_df.at[df.index[i-1], f'order_{n}']  :  # 숏 포지션이 있을 때
                    if adx_state == 2 and last_adx_state <= 1 and temp_df.at[df.index[i-1], f'order_{n}_quantity'] < 0: #ADX가 2일 때 숏 포지션 종료 조건
                        temp_df.at[df.index[i], f'order_{n}'] = False
                        profit = temp_df.at[df.index[i-1], f'order_{n}_quantity'] * (temp_df.at[df.index[i-1], f'order_{n}_entry_price'] - df['close'].iloc[i])
                        temp_df.at[df.index[i], f'order_{n}_profit'] += profit
                        temp_df.at[df.index[i], f'order_{n}_quantity'] = 0
                        temp_df.at[df.index[i], f'order_{n}_entry_price'] = 0
                    elif exceeds_bottom_grid:
                        temp_df.at[df.index[i], f'order_{n}'] = False
                        profit = temp_df.at[df.index[i-1], f'order_{n}_quantity'] * (temp_df.at[df.index[i-1], f'order_{n}_entry_price'] - df['low'].iloc[i])
                        temp_df.at[df.index[i], f'order_{n}_profit'] += profit
                        temp_df.at[df.index[i], f'order_{n}_quantity'] = 0 
                        temp_df.at[df.index[i], 'total_matched_orders'] += 1
                        temp_df.at[df.index[i], f'order_{n}_entry_price'] = 0 #숏포지션 종료
                    elif short_exit_zone is not None :  # 숏 포지션이 있고, 청산 지점이 설정된 경우
                        if df['low'].iloc[i] < short_exit_zone :  # 청산 조건
                            temp_df.at[df.index[i], f'order_{n}'] = False
                            profit = temp_df.at[df.index[i-1], f'order_{n}_quantity'] * (temp_df.at[df.index[i-1], f'order_{n}_entry_price'] - df['low'].iloc[i])
                            temp_df.at[df.index[i], f'order_{n}_profit'] += profit
                            temp_df.at[df.index[i], f'order_{n}_entry_price'] = 0
                            temp_df.at[df.index[i], f'order_{n}_quantity'] = 0   
                            temp_df.at[df.index[i], 'total_matched_orders'] += 1 
                # 포지션 유지
                else:
                    temp_df.at[df.index[i], f'order_{n}'] = temp_df.at[df.index[i-1], f'order_{n}']
                    temp_df.at[df.index[i], f'order_{n}_quantity'] = temp_df.at[df.index[i-1], f'order_{n}_quantity']
                    temp_df.at[df.index[i], f'order_{n}_entry_price'] = temp_df.at[df.index[i-1], f'order_{n}_entry_price']

                  #entry_정보
                if temp_df.at[df.index[i], f'order_{n}']:
                    quantity = temp_df.at[df.index[i], f'order_{n}_quantity']
                    entry_price = temp_df.at[df.index[i], f'order_{n}_entry_price']
                    total_quantity += quantity
                    total_weighted_price += quantity * entry_price
                    total_position += quantity * df['close'].iloc[i]    
        # 총 수익 계산    
                if abs(total_quantity) > 0:
                    avg_entry_price = total_weighted_price / total_quantity
                else:
                    avg_entry_price = 0                    
                total_profit += temp_df.at[df.index[i], f'order_{n}_profit']  # 각 열의 수익을 누적 수익에 더함
                total_position = temp_df.at[df.index[i], f'order_{n}_quantity'] * df['close'].iloc[i]
                temp_df.at[df.index[i], 'total_profit'] = (float(total_profit)/10)  # 누적 수익을 현재 행의 'total_profit'에 할당
                temp_df.at[df.index[i], 'total_position'] = total_position  # 누적 포지션을 현재 행의 'total_position'에 할당
    print(f"{direction} total_profit : {total_profit}")
    df = temp_df  # 임시 데이터프레임을 원래 데이터프레임에 할당
    return df

#================================================================================================
# CACHING DATA
#================================================================================================
async def set_cache(exchange_name, symbol, data, timeframe='1d'):
    """
    Redis에 데이터를 저장합니다. DataFrame을 Redis 리스트로 변환하여 저장합니다.
    이를 통해 데이터의 앞부분 제거나 뒷부분 추가와 같은 작업을 더 효율적으로 수행할 수 있습니다.
    """
    try:
        if data is None or data.empty:
            logging.warning(f"저장할 데이터가 없습니다: {exchange_name}:{symbol}:{timeframe}")
            return False
            
        key = f"{exchange_name}:{symbol}:{timeframe}"
        
        # 기존 데이터 삭제 (리스트 초기화)
        redis_client.delete(key)
        
        # DataFrame을 레코드 리스트로 변환
        records = data.to_dict(orient='records')
        
        # 각 레코드를 JSON 문자열로 변환하여 Redis 리스트에 추가
        pipeline = redis_client.pipeline()
        for record in records:
            # timestamp를 정수로 저장 (datetime 객체는 직렬화 불가)
            if 'timestamp' in record and isinstance(record['timestamp'], pd.Timestamp):
                record['timestamp'] = int(record['timestamp'].timestamp() * 1000)
            
            # 레코드를 JSON 문자열로 변환하여 리스트에 추가
            pipeline.rpush(key, json.dumps(record))
        
        # 파이프라인 실행
        pipeline.execute()
        
        # 마지막 업데이트 시간 저장
        redis_client.set(f"{key}:last_update", int(time.time()))
        
        # TTL 설정 (타임프레임에 따라 다른 TTL 적용)
        ttl = get_ttl_for_timeframe(timeframe)
        if ttl > 0:
            redis_client.expire(key, ttl)
            redis_client.expire(f"{key}:last_update", ttl)
        
        logging.info(f"데이터 캐시 설정 완료: {key} (총 {len(records)}개 레코드)")
        return True
    except Exception as e:
        logging.error(f"캐시 설정 중 오류 발생: {str(e)}")
        traceback.print_exc()
        return False

def get_ttl_for_timeframe(timeframe):
    """
    타임프레임에 따른 TTL(Time To Live) 값을 반환합니다.
    """
    # 기본 TTL (초 단위)
    ttl_map = {
        '1m': 60 * 60 * 24,         # 1분 데이터는 1일 보관
        '5m': 60 * 60 * 24 * 3,      # 5분 데이터는 3일 보관
        '15m': 60 * 60 * 24 * 7,     # 15분 데이터는 7일 보관
        '30m': 60 * 60 * 24 * 14,    # 30분 데이터는 14일 보관
        '1h': 60 * 60 * 24 * 30,     # 1시간 데이터는 30일 보관
        '4h': 60 * 60 * 24 * 60,     # 4시간 데이터는 60일 보관
        '1d': 60 * 60 * 24 * 90,     # 일봉 데이터는 90일 보관
        'long': 60 * 60 * 24 * 30,   # 거래 결과는 30일 보관
        'short': 60 * 60 * 24 * 30,  # 거래 결과는 30일 보관
        'long-short': 60 * 60 * 24 * 30  # 거래 결과는 30일 보관
    }
    
    # 기본값 7일
    return ttl_map.get(timeframe, 60 * 60 * 24 * 7)

async def get_cache(exchange_name, symbol, timeframe='1d'):
    """
    Redis에서 데이터를 가져옵니다. Redis 리스트 형식으로 저장된 데이터를 DataFrame으로 변환합니다.
    """
    try:
        key = f"{exchange_name}:{symbol}:{timeframe}"
        
        # Redis 리스트의 길이 확인
        list_length = redis_client.llen(key)
        
        if list_length == 0:
            return None
        
        # 모든 레코드 가져오기
        records_json = redis_client.lrange(key, 0, -1)
        
        if not records_json:
            return None
        
        # JSON 문자열을 파이썬 객체로 변환
        records = []
        for record_json in records_json:
            try:
                record = json.loads(record_json)
                records.append(record)
            except json.JSONDecodeError as e:
                logging.error(f"JSON 파싱 중 오류 발생: {key} - {str(e)}")
                continue
        
        if not records:
            return None
        
        # 레코드 리스트를 DataFrame으로 변환
        df = pd.DataFrame(records)
        
        # timestamp 열이 있으면 datetime 형식으로 변환
        if 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                
        return df
            
    except Exception as e:
        logging.error(f"캐시 가져오기 중 오류 발생: {str(e)}")
        traceback.print_exc()
        return None

async def get_last_timestamp(exchange_name, symbol, timeframe):
    """
    Redis에서 마지막 타임스탬프를 가져옵니다.
    """
    try:
        key = f"{exchange_name}:{symbol}:{timeframe}"
        df = await get_cache(exchange_name, symbol, timeframe)
        if df is not None and not df.empty and 'timestamp' in df.columns:
            # timestamp가 문자열이라면 datetime으로 변환
            if isinstance(df['timestamp'].iloc[0], str):
                df['timestamp'] = pd.to_datetime(df['timestamp'])
            # 밀리초 타임스탬프로 변환
            return int(df['timestamp'].max().timestamp() * 1000)
        return None
    except Exception as e:
        logging.error(f"마지막 타임스탬프 가져오기 중 오류 발생: {str(e)}")
        return None

#================================================================================================
# F E T C H I N G   A N D   S A V I N G   D A T A
#================================================================================================



async def fetching_data(exchange_instance, exchange_name, symbol, user_id, force_refetch=False):
    """
    지정된 거래소와 심볼에 대한 데이터를 가져옵니다.
    데이터를 Redis에 저장하고 필요한 타임프레임의 데이터를 반환합니다.
    """
    timeframes = ['1m', '5m', '15m', '30m', '1h', '4h', '1d']  # 필요한 모든 타임프레임
    results = {}
    
    for timeframe in timeframes:
        # 이미 캐시된 데이터가 있고 강제 재가져오기가 아닐 경우
        if not force_refetch:
            cached_data = await get_cache(exchange_name, symbol, timeframe)
            if cached_data is not None and not cached_data.empty:
                results[timeframe] = cached_data
                logging.info(f"Redis에서 캐시된 데이터 사용: {exchange_name}:{symbol}:{timeframe}")
                continue
        
        # 마지막 타임스탬프 확인
        last_timestamp = None if force_refetch else await get_last_timestamp(exchange_name, symbol, timeframe)
        
        # OHLCV 데이터 가져오기
        ohlcv_data = await fetch_all_ohlcvs(exchange_name, exchange_instance, symbol, timeframe, last_timestamp, user_id)
        
        if ohlcv_data is not None and not ohlcv_data.empty:
            # Redis에 저장
            await save_ohlcv_to_redis(ohlcv_data, exchange_name, symbol, timeframe)
            results[timeframe] = ohlcv_data
    
    # 15m와 4h 데이터가 있으면 지표 계산
    if '15m' in results and '4h' in results:
        ohlcv_data = results['15m']
        ohlcv_data_4h = results['4h'] 
        return await calculate_ohlcv(exchange_name, symbol, ohlcv_data, ohlcv_data_4h)
    elif '15m' in results:
        # 4h 데이터가 없는 경우 15m 데이터만 사용
        logging.warning(f"4시간 데이터가 없습니다. 15분 데이터만 사용: {exchange_name}:{symbol}")
        # 15m 데이터로 4h 데이터 생성 로직 추가 가능
        return await calculate_ohlcv(exchange_name, symbol, results['15m'], None)
    else:
        logging.warning(f"필요한 데이터가 충분하지 않습니다: {exchange_name}:{symbol}")
        return None, None

async def calculate_ohlcv(exchange_name, symbol, ohlcv_data, ohlcv_data_4h):
    """
    OHLCV 데이터를 증분형으로 계산합니다.
    """
    try:
        if ohlcv_data is None:
            logging.warning(f"15분 OHLCV 데이터가 없습니다: {exchange_name}:{symbol}")
            return None, None
            
        if ohlcv_data_4h is None:
            logging.warning(f"4시간 OHLCV 데이터가 없습니다: {exchange_name}:{symbol}")
            # 4시간 데이터가 없어도 15분 데이터는 처리 가능하도록 설정
            ohlcv_data_4h = pd.DataFrame()
        
        # 원본 데이터를 사용하여 메모리 효율화
        df = ohlcv_data
        
        # 타임스탬프 처리 - 모든 타임스탬프를 UTC 기준으로 타임존 정보 없이 통일
        if 'timestamp' in df.columns and df['timestamp'].dt.tz is not None:
            df['timestamp'] = df['timestamp'].dt.tz_localize(None)
        
        # 방향에 따라 다른 계산 상태 관리
        directions = ['long', 'short', 'long-short']
        
        # 거래소가 스팟인 경우 long 방향만 계산
        is_spot_exchange = exchange_name in ['bitget_spot', 'okx_spot', 'binance_spot', 'upbit', 'bybit_spot']
        if is_spot_exchange:
            directions = ['long']
        
        results_by_direction = {}
        
        # 각 방향에 대해 계산
        for direction in directions:
            try:
                # 이전 계산 상태 가져오기
                state = await get_indicator_state(exchange_name, symbol, direction)
                
                # 타임스탬프 기준으로 새 데이터 확인
                latest_timestamp = df['timestamp'].iloc[-1]
                
                # 상태에 마지막 업데이트 시간이 있고, 그 시간이 현재 데이터의 마지막 시간과 동일하면 재계산 불필요
                if (state.last_update_time is not None and 
                    pd.to_datetime(state.last_update_time) >= latest_timestamp):
                    logging.info(f"이미 최신 데이터까지 계산되어 있음: {exchange_name}:{symbol}:{direction}")
                    continue
                
                # 필요한 경우에만 4시간 데이터 처리
                have_4h_data = not ohlcv_data_4h.empty
                if have_4h_data:
                    df_4h = ohlcv_data_4h
                    
                    if 'timestamp' in df_4h.columns and df_4h['timestamp'].dt.tz is not None:
                        df_4h['timestamp'] = df_4h['timestamp'].dt.tz_localize(None)
                    
                    # ADX 상태 계산 (4시간 데이터 기반)
                    if state.adx is None or len(state.adx) == 0:
                        # 전체 데이터를 사용하여 초기 계산
                        df_4h = calculate_adx(df_4h, 28, 28)
                        df_4h = update_adx_state(df_4h)
                        df = map_4h_adx_to_15m(df_4h, df)
                    else:
                        # 증분 계산: 필요한 데이터만 계산
                        adx, plus_di, minus_di = calculate_adx_incremental(df_4h, state, 28, 28)
                        
                        # 데이터프레임에 결과 할당
                        df_4h['adx'] = adx
                        df_4h['plus_di'] = plus_di
                        df_4h['minus_di'] = minus_di
                        
                        # ADX 상태 업데이트
                        df_4h = update_adx_state(df_4h)
                        df = map_4h_adx_to_15m(df_4h, df)
                
                # 데이터 크기 최적화 - 필요한 과거 데이터만 유지
                required_lookback = 200  # 지표 계산에 필요한 충분한 과거 데이터
                
                if len(df) > required_lookback:
                    working_df = df.iloc[-required_lookback:].copy()
                else:
                    working_df = df.copy()
                
                # 증분형 지표 계산
                with ThreadPoolExecutor(max_workers=3) as executor:
                    # 병렬 계산을 위한 작업 생성
                    futures = []
                    
                    # ADX 계산 (필요한 경우)
                    if not have_4h_data:
                        futures.append(executor.submit(
                            calculate_adx_incremental, working_df, state, 28, 28))
                    
                    # MAMA/FAMA 계산
                    futures.append(executor.submit(
                        compute_mama_fama_incremental, working_df['close'].values, state))
                    
                    # ATR 계산
                    futures.append(executor.submit(
                        atr_incremental, working_df, state, 14))
                    
                    # 결과 수집
                    results = [future.result() for future in futures]
                    
                    # 결과 할당
                    result_index = 0
                    
                    if not have_4h_data:
                        adx, plus_di, minus_di = results[result_index]
                        working_df['adx'] = adx
                        working_df['plus_di'] = plus_di
                        working_df['minus_di'] = minus_di
                        result_index += 1
                    
                    mama, fama = results[result_index]
                    working_df['mama'] = mama
                    working_df['fama'] = fama
                    working_df['main_plot'] = fama
                    result_index += 1
                    
                    working_df['atr'] = results[result_index]
                
                # 나머지 지표 계산
                if not have_4h_data:
                    working_df = update_adx_state(working_df)
                
                # 격자 레벨 계산
                working_df = calculate_grid_levels(working_df)
                
                # 거래 로직 실행
                result_df = execute_trading_logic(working_df.copy(), 100, direction)
                results_by_direction[direction] = result_df
                
                # 결과 저장
                await save_grid_results_to_redis(result_df, exchange_name, symbol, f"{direction}")
                
                # 지표 상태 업데이트
                state.adx_last_idx = len(working_df) - 1
                state.adx = working_df['adx'].values if 'adx' in working_df.columns else None
                state.plus_di = working_df['plus_di'].values if 'plus_di' in working_df.columns else None
                state.minus_di = working_df['minus_di'].values if 'minus_di' in working_df.columns else None
                
                state.mama_last_idx = len(working_df) - 1
                state.mama_values = working_df['mama'].values if 'mama' in working_df.columns else None
                state.fama_values = working_df['fama'].values if 'fama' in working_df.columns else None
                
                state.atr_last_idx = len(working_df) - 1
                state.atr_values = working_df['atr'].values if 'atr' in working_df.columns else None
                state.prev_atr = working_df['atr'].iloc[-1] if 'atr' in working_df.columns else None
                
                state.last_update_time = latest_timestamp.isoformat()
                
                # 상태 저장
                await save_indicator_state(state, exchange_name, symbol, direction)
                
            except Exception as e:
                logging.error(f"거래 로직 실행 중 오류 발생: {exchange_name}:{symbol}:{direction}: {e}")
                logging.debug(traceback.format_exc())
        
        return df, results_by_direction
        
    except Exception as e:
        error_message = str(e)
        if "None of" in error_message:
            logging.error(f"{symbol} 분석 중 오류 발생: {e}. 분석을 종료합니다.")
        else:
            logging.error(f"{symbol} 분석 중 오류 발생: {e}")
            logging.debug(traceback.format_exc())
        return None, None

def enter_position(df, i, n, direction, initial_capital):
    if direction == "long":
        entry_condition = df['low'].iloc[i] < df[f'grid_level_{n}'].iloc[i] and df['low'].iloc[i-1] > df[f'grid_level_{n}'].iloc[i-1]
        exit_condition = df['high'].iloc[i] > df[f'grid_level_{n+2}'].iloc[i]
        quantity_sign = 1
    else:
        entry_condition = df['high'].iloc[i] > df[f'grid_level_{n}'].iloc[i] and df['high'].iloc[i-1] < df[f'grid_level_{n}'].iloc[i-1]
        exit_condition = df['low'].iloc[i] < df[f'grid_level_{n-2}'].iloc[i]
        quantity_sign = -1
    
    if entry_condition:
        df.at[df.index[i], f'order_{n}'] = True
        df.at[df.index[i], f'order_{n}_entry_price'] = df[f'grid_level_{n}'].iloc[i]
        if df.at[df.index[i], f'order_{n}_entry_price'] != 0:
            df.at[df.index[i], f'order_{n}_quantity'] = quantity_sign * float((initial_capital / 20) / df.at[df.index[i], f'order_{n}_entry_price'])
    elif exit_condition:
        df.at[df.index[i], f'order_{n}'] = False
        profit = df.at[df.index[i-1], f'order_{n}_quantity'] * (df[f'grid_level_{n+2}'].iloc[i] - df.at[df.index[i-1], f'order_{n}_entry_price'])
        df.at[df.index[i], f'order_{n}_profit'] += profit
        df.at[df.index[i], f'order_{n}_quantity'] = 0
        df.at[df.index[i], f'order_{n}_entry_price'] = 0


def is_data_valid(df):
    if df.empty:
        return False
    if 'timestamp' not in df.columns:
        return False
    if df['timestamp'].isna().any():
        return False
    if not df['timestamp'].is_monotonic_increasing:
        return False
    # 추가적인 유효성 검사 (예: 가격 데이터가 모두 양수인지 등)
    return True


async def refetch_data(exchange_instance, exchange_name, symbol, user_id):
    # fetching_data 함수를 호출하되, 강제로 전체 데이터를 다시 받아오도록 설정
    # 예를 들어, last_timestamp를 None으로 설정하거나, 특정 플래그를 추가하여 전체 데이터를 다시 받도록 함
    return await fetching_data(exchange_instance = exchange_instance, exchange_name = exchange_name, symbol = symbol, user_id = user_id, force_refetch=True)

async def calculate_grid_logic(direction, grid_num, symbol, exchange_name, user_id, exchange_instance=None):
    try:
        #print(f"Calculating grid logic for {symbol}, user_id = {user_id}, exchange_name = {exchange_name}")
        async with symbol_semaphores[symbol]:
            # Redis에서 캐시 확인
            cached_data = await get_cache(exchange_name, symbol)
            if cached_data is not None and is_data_valid(cached_data):
                print(f"{user_id} Using cached data for {symbol}. cache length: {len(cached_data)}")
                return cached_data.tail(5)

            # 캐시가 없거나 유효하지 않은 경우, 새로운 데이터 fetch
            if exchange_instance is None:
                exchange_instance = await get_exchange_instance(exchange_name, user_id)
                new_instance = True
            else:
                new_instance = False
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    ohlcv_data, ohlcv_data_4h = await fetching_data(exchange_instance, exchange_name = exchange_name, symbol = symbol, user_id = user_id)

                    # 데이터 무결성 확인
                    if not is_data_valid(ohlcv_data) or not is_data_valid(ohlcv_data_4h):
                        print(f"Fetched data for {symbol} is invalid. Attempting to refetch.")
                        ohlcv_data, ohlcv_data_4h = await refetch_data(exchange_instance, exchange_name, symbol, user_id)

                    if ohlcv_data.empty or ohlcv_data_4h.empty:
                        print(f"No valid data available for {symbol} after refetching.")
                        return None

                    required_columns = ['high', 'low', 'close', 'timestamp']
                    if not all(col in ohlcv_data.columns for col in required_columns) or \
                       not all(col in ohlcv_data_4h.columns for col in required_columns):
                        print(f"Missing required columns for {symbol}.")
                        return None

                    # 계산 로직 시작
                    dilen = 28
                    adxlen = 28
                    ohlcv_data_4h = calculate_adx(ohlcv_data_4h, dilen, adxlen)
                    ohlcv_data['adx_state'] = 0
                    ohlcv_data_4h['adx_state'] = 0
                    ohlcv_data = atr(ohlcv_data, 14)
                    ohlcv_data_4h = update_adx_state(ohlcv_data_4h)
                    ohlcv_data = map_4h_adx_to_15m(ohlcv_data_4h, ohlcv_data)
                    mama, fama = compute_mama_fama(ohlcv_data['close'], length=20)
                    ohlcv_data['main_plot'] = fama
                    ohlcv_data = initialize_orders(ohlcv_data, n_levels=grid_num)
                    calculated_data = calculate_grid_levels(ohlcv_data, n_levels=grid_num)

                    # 계산된 결과 Redis에 캐시
                    await set_cache(exchange_name, symbol, calculated_data)

                    return calculated_data.tail(5)
                except Exception as e:
                    print(f"Error processing data for {symbol}: {str(e)}")
                    print(traceback.format_exc())
                    if attempt < max_retries - 1:
                        print(f"Retrying data fetch and processing for {symbol}. Attempt {attempt + 2}/{max_retries}")
                        # 데이터 다시 받기
                        timeframes = ['15m', '4h']  # 필요한 타임프레임 지정
                        df_semaphore = asyncio.Semaphore(5)  # 적절한 semaphore 값 설정
                        await fetch_symbol_data(exchange_instance, symbol, timeframes, df_semaphore, exchange_name, user_id, force_refetch=True)
                    else:
                        print(f"Failed to process data for {symbol} after {max_retries} attempts. Skipping this symbol.")
                        return None
                finally:
                    if new_instance and exchange_instance:
                        await exchange_instance.close()

    except Exception as e:
        print(f"Error processing {symbol}: {e}")
        print(traceback.format_exc())
        return None


async def summarize_trading_results(exchange_name, direction):
    """
    거래 결과를 요약합니다. Redis에서 데이터를 가져와 처리합니다.
    """
    try:
        # Redis에서 해당 거래소와 방향의 모든 심볼 키 가져오기
        pattern = f"{exchange_name}:*:{direction}"
        all_keys = redis_client.keys(pattern)
        
        results = []
        
        for key in all_keys:
            try:
                # 키에서 심볼 추출
                parts = key.decode('utf-8').split(':')
                if len(parts) < 2:
                    continue
                symbol = parts[1]
                
                # Redis에서 데이터 가져오기
                df = await get_cache(exchange_name, symbol, direction)
                
                if df is None or df.empty or 'total_profit' not in df.columns:
                    continue
                
                # 마지막 총 수익 계산
                last_total_profit = df['total_profit'].iloc[-1]
                
                # 이상치 처리
                if last_total_profit >= 2000:
                    last_total_profit /= 100
                elif last_total_profit <= -2000:
                    last_total_profit /= 100
                elif last_total_profit >= 900:
                    last_total_profit /= 10
                elif last_total_profit <= -100:
                    last_total_profit /= 100
                
                # 추가 정보 수집
                total_trades = df['order_count'].iloc[-1] if 'order_count' in df.columns else 0
                win_rate = df['win_rate'].iloc[-1] if 'win_rate' in df.columns else 0
                drawdown = df['max_drawdown'].iloc[-1] if 'max_drawdown' in df.columns else 0
                
                # 결과 추가
                results.append({
                    'symbol': symbol,
                    'total_profit': last_total_profit,
                    'total_trades': total_trades,
                    'win_rate': win_rate,
                    'drawdown': drawdown
                })
                
            except Exception as e:
                logging.error(f"심볼 처리 중 오류 발생: {key} - {str(e)}")
                continue
        
        # 결과를 DataFrame으로 변환
        if not results:
            logging.warning(f"{exchange_name}의 {direction} 방향 거래 결과가 없습니다.")
            return []
            
        summary_df = pd.DataFrame(results)
        
        # 수익 기준으로 정렬
        summary_df = summary_df.sort_values('total_profit', ascending=False)
        
        # Redis에 요약 결과 저장
        summary_key = f"{exchange_name}:summary:{direction}"
        await set_cache(exchange_name, "summary", summary_df, direction)
        
        logging.info(f"{exchange_name}의 {direction} 방향 거래 전략 요약이 완료되었습니다.")
        
        # 결과 반환
        return summary_df.to_dict('records')
        
    except Exception as e:
        logging.error(f"거래 결과 요약 중 오류 발생: {str(e)}")
        traceback.print_exc()
        return []


async def get_all_okx_usdt_swap_symbols():
    """OKX 거래소의 모든 USDT 선물 마켓 종목과 거래량을 비동기적으로 가져오는 함수"""
    # OKX 선물 API 엔드포인트
    url = "https://www.okx.com/api/v5/market/tickers?instType=SWAP"

    # SSL 검증 비활성화
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url, ssl=ssl_context) as response:
            data = await response.json()

        # OKX에서의 응답 데이터 구조에 맞게 파싱
        usdt_symbols_data = []
        for item in data['data']:
            # USDT-SWAP 마켓 종목 확인
            if 'USDT-SWAP' in item['instId']:  
                symbol = item['instId']
                volume = float(item['volCcy24h']) * float(item['last'])  # 해당 마켓의 24시간 거래량 (거래된 금액량)
                usdt_symbols_data.append((symbol, volume))

        # 거래량(volume)으로 내림차순 정렬
        sorted_usdt_symbols_data = sorted(usdt_symbols_data, key=lambda x: x[1], reverse=True)
        return [item[0] for item in sorted_usdt_symbols_data]

async def get_all_okx_usdt_spot_symbols():
    """OKX 거래소의 모든 USDT 선물 마켓 종목과 거래량을 비동기적으로 가져오는 함수"""
    # OKX 선물 API 엔드포인트
    url = "https://www.okx.com/api/v5/market/tickers?instType=SPOT"

    # SSL 검증 비활성화
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url, ssl=ssl_context) as response:
            data = await response.json()

        # OKX에서의 응답 데이터 구조에 맞게 파싱
        usdt_symbols_data = []
        for item in data['data']:
            # USDT 스팟 마켓 종목 확인
            if 'USDT' in item['instId']:  
                symbol = item['instId']
                volume = float(item['volCcy24h']) * float(item['last'])  # 해당 마켓의 24시간 거래량 (거래된 코인의 양)
                usdt_symbols_data.append((symbol, volume))


        # 거래량(volume)으로 내림차순 정렬
        sorted_usdt_symbols_data = sorted(usdt_symbols_data, key=lambda x: x[1], reverse=True)[:200]
        return [item[0] for item in sorted_usdt_symbols_data]

async def get_all_binance_usdt_symbols():
    """바이낸스 퓨처스의 모든 USDT 종목과 거래량을 비동기적으로 가져오는 함수"""
    url = "https://fapi.binance.com/fapi/v1/ticker/24hr"
    
    # SSL 검증 비활성화
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url, ssl=ssl_context) as response:
            data = await response.json()

    usdt_volume_data = []
    for item in data:
        if item['symbol'].endswith('USDT'):
            symbol = item['symbol']
            volume = float(item['volume'])
            price = float(item['lastPrice'])
            usdt_volume = volume * price
            usdt_volume_data.append((symbol, usdt_volume))

    sorted_usdt_volume_data = sorted(usdt_volume_data, key=lambda x: x[1], reverse=True)
    return [item[0] for item in sorted_usdt_volume_data]

async def get_all_binance_usdt_spot_symbols():
    """바이낸스 스팟의 모든 USDT 종목과 거래량을 비동기적으로 가져오는 함수"""
    url = "https://api.binance.com/api/v3/ticker/24hr"
    
    # SSL 검증 비활성화
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE

    async with aiohttp.ClientSession() as session:
        async with session.get(url, ssl=ssl_context) as response:
            data = await response.json()

    usdt_volume_data = []
    for item in data:
        if item['symbol'].endswith('USDT'):
            symbol = item['symbol']
            volume = float(item['volume'])
            price = float(item['lastPrice'])
            usdt_volume = volume * price  # 24시간 동안의 USDT 기준 거래량 계산
            usdt_volume_data.append((symbol, usdt_volume))

    sorted_usdt_volume_data = sorted(usdt_volume_data, key=lambda x: x[1], reverse=True)
    return [item[0] for item in sorted_usdt_volume_data]


async def get_all_upbit_krw_symbols():
    try:
        exchange = await get_exchange_instance('upbit', user_id=999999999)
        markets = await exchange.fetch_markets()
        # 수정된 부분: 심볼 포맷 변경
        krw_market_symbols = ['KRW-' + market['symbol'].replace('KRW', '').rstrip('/') for market in markets if market['symbol'].endswith('KRW')]
    except Exception as e:
        print(f"An error occurred22: {e}")
        krw_market_symbols = []
        return krw_market_symbols
    finally:
        await exchange.close()
    return krw_market_symbols
    
async def handle_symbol(exchange_instance, symbol, exchange_name, semaphore, executor):
    # 대기 시간 감소
    await asyncio.sleep(0.5)  # 2초에서 0.5초로 감소

    async with semaphore:
        need_update = False
        
        try:
            symbol_name = symbol.replace("/", "")
            print(f"Analyzing {symbol}...")
            # 불필요한 대기 시간 줄이기
            await asyncio.sleep(random.uniform(0.2, 0.4))  # 0.4-0.7초에서 0.2-0.4초로 감소
            directions = ['long', 'short', 'long-short']
            
            # 스팟 거래소 예외 처리 최적화
            is_spot_exchange = exchange_name in ['bitget_spot', 'okx_spot', 'binance_spot', 'upbit', 'bybit_spot']
            check_directions = ['long'] if is_spot_exchange else directions
            
            # 최신 데이터 확인을 위한 15분 경계 계산
            current_time = datetime.now()
            last_15m_boundary = current_time - timedelta(minutes=current_time.minute % 15, seconds=current_time.second, microseconds=current_time.microsecond)
            last_15m_boundary_ts = int(last_15m_boundary.timestamp() * 1000)
            
            # 각 방향에 대한 지표 상태 확인
            for direction in check_directions:
                # 지표 상태 가져오기
                state = await get_indicator_state(exchange_name, symbol, direction)
                
                # 상태가 없거나 최신이 아닌 경우 업데이트 필요
                if state.last_update_time is None:
                    need_update = True
                    break
                
                # 마지막 업데이트 시간 확인
                try:
                    last_update_dt = pd.to_datetime(state.last_update_time)
                    if last_update_dt.timestamp() * 1000 <= last_15m_boundary_ts:
                        need_update = True
                        break
                except Exception as e:
                    logging.warning(f"마지막 업데이트 시간 파싱 오류: {e}")
                    need_update = True
                    break
            
            if not need_update:
                logging.info(f"이미 최신 데이터로 계산되어 있음: {exchange_name}:{symbol}")
                return
                
        except Exception as e:
            logging.error(f"Error analyzing {symbol}: {e}")
            logging.debug(traceback.format_exc())
            need_update = True  # 에러 발생 시 업데이트 필요
            
        # 업데이트가 필요한 경우
        if need_update:
            try:
                print(f"Updating data for {symbol}...")
                
                # 데이터 가져오기
                try:
                    # 캐시 우선 확인으로 불필요한 데이터 요청 최소화 (force_refetch는 필요한 경우만 True로)
                    ohlcv_data, ohlcv_data_4h = await fetching_data(exchange_instance, exchange_name=exchange_name, symbol=symbol, user_id=999999999, force_refetch=False)
                    # 대기 시간 최적화
                    await asyncio.sleep(0.5)  # 2초에서 0.5초로 감소
                except Exception as e:
                    print(f"Exception occurred on ohlcv data {symbol}: {e}")
                    return
                
                # 데이터 유효성 검사
                if ohlcv_data is None or (not isinstance(ohlcv_data, pd.DataFrame)) or ohlcv_data.empty:
                    print(f"Invalid OHLCV data for {symbol}")
                    return
                
                # 계산 실행
                try:
                    # 비동기로 직접 계산 (로깅 추가)
                    print(f"Starting calculation for {symbol}...")
                    start_time = time.time()
                    
                    # 직접 비동기 계산 호출
                    df, results_by_direction = await calculate_ohlcv(exchange_name, symbol, ohlcv_data, ohlcv_data_4h)
                    
                    elapsed_time = time.time() - start_time
                    print(f"Calculation completed for {symbol} in {elapsed_time:.2f} seconds")
                    
                    # 업데이트 시간 기록 - 파이프라인 사용
                    current_ts = int(time.time() * 1000)
                    pipe = redis_client.pipeline()
                    
                    for direction in directions:
                        # 스팟 거래소는 long 방향만 저장
                        if is_spot_exchange and direction != 'long':
                            continue
                            
                        redis_key = f"{exchange_name}:{symbol}:{direction}:last_update"
                        pipe.set(redis_key, current_ts)
                    
                    # 파이프라인 실행 - 한 번에 모든 Redis 작업 수행
                    pipe.execute()
                except Exception as e:
                    print(f"Error calculating indicators for {symbol}: {e}")
                    print(traceback.format_exc())
            except Exception as e:
                print(f"Error handling {symbol}: {e}")
                print(traceback.format_exc())


    


async def periodic_analysis(exchange_name, interval=14400):
    # 비동기로 실행할 모든 작업을 수행
    exchange_instance = await get_exchange_instance(exchange_name, user_id=999999999)
    # 프로세스 풀 크기 증가
    executor = ProcessPoolExecutor(max_workers=8)  # 4에서 8로 증가
    # 세마포어 값 증가
    semaphore_upbit = asyncio.Semaphore(5)  # 3에서 5로 증가
    semaphore_binance = asyncio.Semaphore(5)  # 3에서 5로 증가 
    semaphore_okx = asyncio.Semaphore(5)  # 3에서 5로 증가
    semaphore_bybit = asyncio.Semaphore(5)  # 3에서 5로 증가
    semaphore_biget = asyncio.Semaphore(5)  # 3에서 5로 증가
    while True:  # running_event가 set 상태인 동안 실행
        start_time = asyncio.get_event_loop().time()
        await asyncio.sleep(1)
        
        if exchange_name == 'okx':
            symbols = await get_all_okx_usdt_swap_symbols()
            semaphore = semaphore_okx
        # 다른 거래소 조건은 주석 처리된 상태로 유지
        
        # 심볼을 청크로 나누어 처리
        chunk_size = 20  # 한 번에 처리할 심볼 수
        for i in range(0, len(symbols), chunk_size):
            chunk = symbols[i:i+chunk_size]
            # 각 청크에 대한 작업 생성
            tasks = [handle_symbol(exchange_instance, symbol, exchange_name, semaphore, executor) for symbol in chunk]
            # 청크 단위로 병렬 처리
            await asyncio.gather(*tasks)
            # 각 청크 사이에 짧은 대기 시간 추가하여 리소스 과부하 방지
            await asyncio.sleep(1)
            
        if exchange_name in ['bitget_spot', 'okx_spot', 'binance_spot', 'upbit', 'bybit_spot']:
            await summarize_trading_results(exchange_name, 'long')
        else : 
            # 병렬로 요약 결과 처리
            summary_tasks = [
                summarize_trading_results(exchange_name, 'long'),
                summarize_trading_results(exchange_name, 'short'),
                summarize_trading_results(exchange_name, 'long-short')
            ]
            await asyncio.gather(*summary_tasks)
            
        finished_time = asyncio.get_event_loop().time()
        elapsed_time = finished_time - start_time
        print(f"==========\nElapsed time: {elapsed_time:.2f} seconds\n==========")
        print("Analyze all symbols complete. Waiting for the next interval.")
        await asyncio.sleep(interval)  # 다음 분석 주기까지 대기



async def fetch_ohlcvs(exchange_instance, symbol, timeframe, since, limit):
    """
    CCXT를 사용하여 OHLCV 데이터를 가져옵니다.
    """
    ohlcv_data = []
    max_retries = 5  # 최대 재시도 횟수 설정
    retries = 0
    
    # since가 pandas Timestamp 객체인 경우 정수로 변환
    if isinstance(since, pd.Timestamp):
        since = int(since.timestamp() * 1000)
    # since가 문자열인 경우 정수로 변환
    elif isinstance(since, str):
        try:
            since = int(pd.Timestamp(since).timestamp() * 1000)
        except:
            # 변환할 수 없는 문자열이면 90일 전으로 설정
            since = int(time.time() * 1000) - (86400 * 1000 * 90)
    # since가 None이면 90일 전으로 설정
    elif since is None:
        since = int(time.time() * 1000) - (86400 * 1000 * 90)
    
    # 이제 since는 확실히 정수(int) 타입입니다
    current_time = int(time.time() * 1000)
    
    while since < current_time:
        try:
            # 레이트 리밋 방지를 위한 짧은 대기
            await asyncio.sleep(exchange_instance.rateLimit / 1000)
            
            # OHLCV 데이터 가져오기
            data = await exchange_instance.fetch_ohlcv(symbol, timeframe, since, limit)
            
            # 더 이상 데이터가 없으면 종료
            if len(data) == 0:
                break
                
            # 데이터 추가 및 다음 타임스탬프 설정
            ohlcv_data.extend(data)
            last_timestamp = data[-1][0]
            
            # since를 마지막 타임스탬프 다음으로 설정
            timeframe_ms = exchange_instance.parse_timeframe(timeframe) * 1000
            since = last_timestamp + timeframe_ms
            
            # 재시도 카운터 초기화
            retries = 0
            
        except (ccxt.NetworkError, ccxt.ExchangeError, ccxt.RequestTimeout) as e:
            retries += 1
            if retries >= max_retries:
                print(f"Max retries exceeded for {symbol}: {e}")
                break
                
            # 재시도 전 대기 시간을 점진적으로 증가 (지수 백오프)
            wait_time = (2 ** retries) * 0.5
            print(f"Error fetching data for {symbol}: {e}. Retrying in {wait_time:.1f} seconds...")
            await asyncio.sleep(wait_time)
            
        except Exception as e:
            print(f"Unexpected error fetching data for {symbol}: {e}")
            traceback.print_exc()
            break
    
    return ohlcv_data

async def fetch_all_ohlcvs(exchange_name, exchange_instance, symbol, timeframe, last_timestamp, user_id, max_retries=3):
    """
    특정 거래소, 심볼, 타임프레임에 대한 모든 OHLCV 데이터를 가져옵니다.
    """
    # 최적화: 병렬 처리와 비동기 요청을 조합
    
    # 시간 간격을 밀리초로 변환
    timeframe_ms = parse_timeframe_to_ms(timeframe)
    
    # 초기 설정
    full_ohlcv_data = []
    retries = 0
    current_timestamp = last_timestamp
    
    # 한 번에 가져올 최대 캔들 수
    batch_size = 1000
    
    # 요청 제한을 고려한 대기 시간 (밀리초)
    wait_time = 50
    
    # 마지막 요청 시간 
    last_request_time = time.time() * 1000
    
    # 최대 병렬 요청 수 제한
    semaphore = asyncio.Semaphore(3)  
    
    while True:
        try:
            # 현재 시간
            now = time.time() * 1000
            
            # 대기 시간 준수
            if now - last_request_time < wait_time:
                await asyncio.sleep((wait_time - (now - last_request_time)) / 1000)
            
            # 병렬로 처리할 요청들
            async def fetch_batch(since_ts):
                async with semaphore:
                    try:
                        return await fetch_ohlcvs(exchange_instance, symbol, timeframe, since_ts, batch_size)
                    except Exception as e:
                        logging.error(f"배치 요청 중 오류: {str(e)}")
                        return []
            
            # 여러 배치를 동시에 요청하지만 최대 병렬 수는 제한됨
            tasks = []
            
            # 최대 3개의 연속 배치 요청 생성
            for i in range(3):
                if current_timestamp is None:
                    # 초기 요청인 경우 (과거 데이터부터)
                    ts = None if i == 0 else (int(time.time() * 1000) - (timeframe_ms * batch_size * (3-i)))
                else:
                    # 증분 업데이트인 경우
                    ts = current_timestamp + (i * timeframe_ms * batch_size)
                
                tasks.append(fetch_batch(ts))
            
            # 모든 배치 요청 실행
            batch_results = await asyncio.gather(*tasks)
            
            # 결과 처리
            all_new_data = []
            for batch_data in batch_results:
                if batch_data and len(batch_data) > 0:
                    all_new_data.extend(batch_data)
            
            # 데이터가 없으면 중단
            if not all_new_data:
                break
                
            # 타임스탬프 기준 정렬 및 중복 제거
            all_new_data = sorted(all_new_data, key=lambda x: x[0])
            unique_data = []
            seen_timestamps = set()
            
            for item in all_new_data:
                ts = item[0]
                if ts not in seen_timestamps:
                    seen_timestamps.add(ts)
                    unique_data.append(item)
            
            # 기존 데이터와 병합
            full_ohlcv_data.extend(unique_data)
            
            # 마지막 타임스탬프 업데이트
            if unique_data:
                current_timestamp = unique_data[-1][0]
                
            # 최신 데이터 확인 (더 이상 가져올 데이터가 없는지)
            if len(unique_data) < batch_size:
                break
                
            # 요청 시간 업데이트
            last_request_time = time.time() * 1000
            
            # 중복 요청 방지를 위한 대기
            await asyncio.sleep(0.1)
            
        except Exception as e:
            retries += 1
            if retries >= max_retries:
                logging.error(f"데이터 가져오기 최대 재시도 횟수 초과: {symbol} {timeframe}: {str(e)}")
                break
            
            logging.warning(f"데이터 가져오기 재시도 {retries}/{max_retries}: {symbol} {timeframe}")
            await asyncio.sleep(1 * retries)  # 지수 백오프
    
    # 최종 처리된 데이터가 없으면 빈 데이터프레임 반환
    if not full_ohlcv_data:
        return pd.DataFrame()
    
    # 데이터프레임 변환 및 중복 제거
    df = pd.DataFrame(full_ohlcv_data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df = df.drop_duplicates(subset=['timestamp']).reset_index(drop=True)
    
    # 타임스탬프를 datetime으로 변환
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
    
    return df

def ensure_kst_timestamp(ts):
    if isinstance(ts, str):
        try:
            ts = pd.to_datetime(ts)
        except ValueError:
            print(f"Error parsing timestamp string: {ts}")
            return pd.NaT
    
    if not isinstance(ts, pd.Timestamp):
        try:
            ts = pd.to_datetime(ts)
        except ValueError:
            print(f"Error converting to timestamp: {ts}")
            return pd.NaT
    
    if ts.tzinfo is None:
        ts = ts.tz_localize('UTC')
    
    return ts.tz_convert(pytz.timezone('Asia/Seoul'))

def parse_exchange_name(exchange_name):
    if '_spot' in exchange_name:
        return exchange_name.replace('_spot', ''), 'spot'
    elif '_future' in exchange_name or '_futures' in exchange_name:
        return exchange_name.replace('_future', '').replace('_futures', ''), 'future'
    else:
        return exchange_name, 'spot'  # Default to spot if not specified

#================================================================================================@
# SAVE OHLCV DATA TO CSV
#================================================================================================@


def parse_timestamp(ts, prev_ts=None, interval=None):
    if pd.isna(ts) or ts == "":
        if prev_ts is not None and interval is not None:
            return prev_ts + interval
        return pd.NaT
    
    if isinstance(ts, (int, float)):
        try:
            return pd.to_datetime(ts, unit='ms', utc=True).tz_convert('Asia/Seoul')
        except Exception as e:
            print(f"Error converting timestamp {ts}: {e}")
            return pd.NaT
    
    if isinstance(ts, str):
        try:
            dt = pd.to_datetime(ts)
            if dt.tzinfo is None:
                dt = dt.tz_localize('UTC')
            return dt.tz_convert('Asia/Seoul')
        except ValueError:
            try:
                dt = parser.parse(ts)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=pytz.UTC)
                return dt.astimezone(pytz.timezone('Asia/Seoul'))
            except Exception as e:
                print(f"Error parsing timestamp {ts}: {e}")
                return pd.NaT

    return pd.NaT

def fill_missing_timestamps(df, file_name):
    # 파일명에서 시간 간격 추론
    if file_name.endswith('_4h'):
        interval = pd.Timedelta(hours=4)
    else:  # 기본값은 15분
        interval = pd.Timedelta(minutes=15)
    
    prev_ts = None
    filled_timestamps = []

    for ts in df['timestamp']:
        parsed_ts = parse_timestamp(ts, prev_ts, interval)
        if pd.notna(parsed_ts):
            prev_ts = parsed_ts
        filled_timestamps.append(parsed_ts)

    df['timestamp'] = filled_timestamps
    return df


async def save_ohlcv_to_redis(ohlcv_df, exchange_name, symbol, timeframe):
    """
    OHLCV 데이터를 Redis에 저장합니다.
    """
    try:
        if ohlcv_df is None or ohlcv_df.empty:
            logging.warning(f"저장할 OHLCV 데이터가 없습니다: {exchange_name}:{symbol}:{timeframe}")
            return False
        
        # 기존 데이터 불러오기
        existing_df = await get_cache(exchange_name, symbol, timeframe)
        
        if existing_df is not None and not existing_df.empty:
            # 기존 데이터와 새 데이터 병합 (중복 제거)
            combined_df = pd.concat([existing_df, ohlcv_df])
            combined_df = combined_df.drop_duplicates(subset=['timestamp'])
            combined_df = combined_df.sort_values('timestamp')
            
            # 기존 키 삭제 후 새로운 리스트로 저장
            key = f"{exchange_name}:{symbol}:{timeframe}"
            redis_client.delete(key)
            
            # 새 데이터를 리스트로 저장
            result = await set_cache(exchange_name, symbol, combined_df, timeframe)
        else:
            # 새 데이터만 저장
            result = await set_cache(exchange_name, symbol, ohlcv_df, timeframe)
        
        logging.info(f"OHLCV 데이터 Redis 저장 완료: {exchange_name}:{symbol}:{timeframe}")
        return result
    except Exception as e:
        logging.error(f"OHLCV Redis 저장 중 오류 발생: {exchange_name}:{symbol}:{timeframe} - {str(e)}")
        traceback.print_exc()
        return False

# ... existing code ...

async def fetch_symbol_data(exchange_instance, symbol, timeframes, semaphore, exchange_name, user_id, force_refetch=False):
    """
    지정된 심볼과 타임프레임에 대한 OHLCV 데이터를 가져옵니다.
    """
    results = {}
    
    async with semaphore:
        try:
            for timeframe in timeframes:
                # 캐시 확인
                if not force_refetch:
                    cached_data = await get_cache(exchange_name, symbol, timeframe)
                    if cached_data is not None and not cached_data.empty:
                        results[timeframe] = cached_data
                        logging.info(f"캐시 데이터 사용: {exchange_name}:{symbol}:{timeframe}")
                        continue
                
                # 마지막 타임스탬프 확인
                last_timestamp = None if force_refetch else await get_last_timestamp(exchange_name, symbol, timeframe)
                
                # OHLCV 데이터 가져오기
                logging.info(f"Fetching {symbol} data...")
                
                fetched_data = await fetch_all_ohlcvs(exchange_name, exchange_instance, symbol, timeframe, last_timestamp, user_id)
                
                if fetched_data is not None and not fetched_data.empty:
                    # 기존 데이터 가져오기
                    cached_data = await get_cache(exchange_name, symbol, timeframe)
                    
                    if cached_data is not None and not cached_data.empty:
                        # 타임스탬프 형식 확인 및 통일 - 모든 타임스탬프를 UTC 기준 타임존 정보 없이 통일
                        if 'timestamp' in cached_data.columns:
                            # 캐시 데이터의 타임스탬프 통일
                            if cached_data['timestamp'].dt.tz is not None:
                                cached_data['timestamp'] = cached_data['timestamp'].dt.tz_localize(None)
                            
                        if 'timestamp' in fetched_data.columns:
                            # 새 데이터의 타임스탬프 통일
                            if fetched_data['timestamp'].dt.tz is not None:
                                fetched_data['timestamp'] = fetched_data['timestamp'].dt.tz_localize(None)
                        
                        # 데이터 병합
                        combined_df = pd.concat([cached_data, fetched_data])
                        # 중복 제거 및 정렬
                        combined_df = combined_df.drop_duplicates(subset=['timestamp']).sort_values('timestamp')
                        
                        # Redis에 저장
                        await save_ohlcv_to_redis(combined_df, exchange_name, symbol, timeframe)
                        results[timeframe] = combined_df
                    else:
                        # 새 데이터만 저장
                        await save_ohlcv_to_redis(fetched_data, exchange_name, symbol, timeframe)
                        results[timeframe] = fetched_data
            
            return results
        except Exception as e:
            logging.error(f"데이터 가져오기 중 오류 발생: {exchange_name}:{symbol} - {str(e)}")
            traceback.print_exc()
            return results

#        
#================================================================================================@
async def fetch_symbols(exchange_name):
    try:
        if exchange_name == 'binance':
            symbols = await get_all_binance_usdt_symbols()
        elif exchange_name == 'upbit':
            symbols = await get_all_upbit_krw_symbols()
        if exchange_name == 'okx':
            symbols = await get_all_okx_usdt_swap_symbols()
        elif exchange_name == 'binance_spot':
            symbols = await get_all_binance_usdt_spot_symbols()
        elif exchange_name == 'okx_spot':
            symbols = await get_all_okx_usdt_spot_symbols()
    except:
        print(f"Error fetching symbols for {exchange_name}")
        symbols = []
    return symbols



# 타임프레임별 업데이트 간격 설정 (초 단위)
UPDATE_INTERVALS = {
    '1m': 60,     # 1분
    '5m': 300,    # 5분
    '15m': 900,   # 15분
    '30m': 1800,  # 30분
    '1h': 3600,   # 1시간
    '4h': 14400,  # 4시간
    '1d': 86400   # 1일
}

async def update_timeframe(exchange_instance, symbols, timeframe, semaphore, exchange_name, user_id):
    while True:
        print(f"Updating data for timeframe: {timeframe}")
        tasks = [
            fetch_symbol_data(exchange_instance, symbol, [timeframe], semaphore, exchange_name, user_id)
            for symbol in symbols
        ]
        results = await asyncio.gather(*tasks)
        
        # 데이터 처리 및 지표 계산
        for symbol, data in zip(symbols, results):
            if timeframe in data:
                ohlcv_data = data[timeframe]
                print(f"Updated {symbol} for {timeframe}: {len(ohlcv_data)} rows")
                
                try:
                    # 4시간 데이터도 필요한 경우 (15분 데이터의 경우)
                    if timeframe == '15m':
                        # 4시간 데이터 가져오기
                        data_4h = await fetch_symbol_data(exchange_instance, symbol, ['4h'], semaphore, exchange_name, user_id)
                        if '4h' in data_4h and not data_4h['4h'].empty:
                            ohlcv_data_4h = data_4h['4h']
                            
                            # 지표 계산
                            print(f"Calculating indicators for {symbol}...")
                            df, df_4h = await calculate_ohlcv(exchange_name, symbol, ohlcv_data, ohlcv_data_4h)
                            
                            if df is not None and df_4h is not None:
                                print(f"Indicators calculated for {symbol}")
                    elif timeframe == '4h':
                        # 4시간 데이터만 있는 경우 ADX와 같은 기본 지표만 계산
                        try:
                            # 기본 지표 계산
                            df_4h = ohlcv_data.copy()
                            dilen = 28
                            adxlen = 28
                            df_4h = calculate_adx(df_4h, dilen, adxlen)
                            df_4h['adx_state'] = 0
                            df_4h = update_adx_state(df_4h)
                            
                            # Redis에 지표 저장
                            await save_indicators_to_redis(df_4h, exchange_name, symbol, '4h')
                            print(f"4h indicators saved for {symbol}")
                        except Exception as e:
                            print(f"Error calculating 4h indicators for {symbol}: {e}")
                            traceback.print_exc()
                except Exception as e:
                    print(f"Error processing indicators for {symbol}: {e}")
                    traceback.print_exc()
        
        # 다음 업데이트까지 대기
        await asyncio.sleep(UPDATE_INTERVALS[timeframe])

async def main():
    try:
        exchange_name = 'okx'
        user_id = '1234'  # 적절한 사용자 ID를 입력하세요
        #timeframes = ['1m', '5m', '15m', '30m', '1h', '4h', '1d']  # 원하는 시간프레임을 설정하세요
        timeframes = ['15m']  # 원하는 시간프레임을 설정하세요

        # exchange 인스턴스 생성
        exchange_instance = await get_exchange_instance(exchange_name, user_id)
        
        if not exchange_instance:
            print(f"거래소 인스턴스 생성 실패: {exchange_name}")
            return
        
        try:
            symbols = await get_all_okx_usdt_swap_symbols()
            semaphore = asyncio.Semaphore(8)  # 동시 요청 수를 8로 제한

            # 각 타임프레임별로 업데이트 태스크 생성
            update_tasks = [
                update_timeframe(exchange_instance, symbols, timeframe, semaphore, exchange_name, user_id)
                for timeframe in timeframes
            ]

            # 모든 업데이트 태스크 동시 실행
            await asyncio.gather(*update_tasks)
        finally:
            # 항상 거래소 인스턴스를 종료하여 리소스 확보
            if hasattr(exchange_instance, 'close') and callable(exchange_instance.close):
                await exchange_instance.close()
                print(f"거래소 연결 종료 완료: {exchange_name}")
    except Exception as e:
        print(f"메인 함수 실행 중 오류 발생: {e}")
        traceback.print_exc()
    finally:
        # 모든 비동기 리소스 정리
        for task in asyncio.all_tasks():
            if task is not asyncio.current_task():
                task.cancel()
        
        # 남은 연결 정리
        pending = asyncio.all_tasks()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

# Redis 유틸리티 함수들
async def list_redis_keys(pattern="*"):
    """
    Redis에 저장된 키 목록을 조회합니다.
    
    Args:
        pattern: 검색할 키 패턴 (예: "okx:*:1d")
        
    Returns:
        list: 키 목록
    """
    try:
        keys = redis_client.keys(pattern)
        return [key.decode('utf-8') for key in keys]
    except Exception as e:
        logging.error(f"Redis 키 조회 중 오류 발생: {str(e)}")
        return []

async def delete_redis_keys(pattern):
    """
    특정 패턴의 Redis 키를 삭제합니다.
    
    Args:
        pattern: 삭제할 키 패턴 (예: "okx:BTC/USDT:*")
        
    Returns:
        int: 삭제된 키 개수
    """
    try:
        keys = redis_client.keys(pattern)
        if not keys:
            return 0
        return redis_client.delete(*keys)
    except Exception as e:
        logging.error(f"Redis 키 삭제 중 오류 발생: {str(e)}")
        return 0

async def backup_redis_data(exchange_name=None, timeframe=None, output_dir=None):
    """
    Redis의 OHLCV 데이터 및 지표 데이터를 CSV 파일로 백업합니다.
    
    Args:
        exchange_name: 특정 거래소만 백업하려면 지정 (옵션)
        timeframe: 특정 타임프레임만 백업하려면 지정 (옵션)
        output_dir: 백업 디렉토리 경로 (옵션)
        
    Returns:
        int: 백업된 파일 개수
    """
    try:
        # 백업 디렉토리가 없으면 생성
        if output_dir is None:
            now = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_dir = f"backup/redis_backup_{now}"
        
        os.makedirs(output_dir, exist_ok=True)
        
        # Redis 키 패턴 결정
        if exchange_name and timeframe:
            pattern = f"{exchange_name}:*:{timeframe}"
        elif exchange_name:
            pattern = f"{exchange_name}:*"
        elif timeframe:
            pattern = f"*:{timeframe}"
        else:
            pattern = "*"
            
        # Redis 키 목록 가져오기
        keys = await list_redis_keys(pattern)
        count = 0
        
        for key in keys:
            parts = key.split(":")
            if len(parts) < 3:
                continue
                
            # 키 형식 파악 (일반 OHLCV, 지표 데이터, 거래 결과)
            if len(parts) == 3:  # 기본 OHLCV 데이터
                exchange, symbol, tf = parts
                key_type = "ohlcv"
            elif len(parts) == 4 and parts[3] == "indicators":  # 지표 데이터
                exchange, symbol, tf, _ = parts
                key_type = "indicators"
            else:  # 거래 결과 또는 기타 데이터
                exchange, symbol, tf = parts[:3]
                key_type = "other"
                
            symbol_safe = symbol.replace("/", "_")
            
            # 데이터 가져오기
            if key_type == "indicators":
                df = await get_indicators_from_redis(exchange, symbol, tf)
            else:
                df = await get_cache(exchange, symbol, tf)
                
            if df is None or df.empty:
                continue
                
            # CSV 저장
            file_path = os.path.join(output_dir, f"{exchange}_{symbol_safe}_{tf}_{key_type}.csv")
            df.to_csv(file_path, index=False)
            count += 1
            logging.info(f"데이터 백업 완료: {file_path}")
        
        logging.info(f"총 {count}개 파일 백업 완료: {output_dir}")
        return count
        
    except Exception as e:
        logging.error(f"Redis 데이터 백업 중 오류 발생: {str(e)}")
        traceback.print_exc()
        return 0

async def fill_missing_data(exchange_name, symbol, timeframe):
    """
    Redis에서 가져온 데이터의 누락된 타임스탬프를 채웁니다.
    """
    try:
        # Redis에서 데이터 가져오기
        df = await get_cache(exchange_name, symbol, timeframe)
        if df is None or df.empty:
            logging.warning(f"Redis에서 데이터를 찾을 수 없습니다: {exchange_name}:{symbol}:{timeframe}")
            return None
            
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df.set_index('timestamp', inplace=True)
        
        # 시간 간격 설정
        if timeframe.endswith('m'):
            freq = f"{timeframe[:-1]}min"
        elif timeframe.endswith('h'):
            freq = f"{timeframe[:-1]}h"
        else:
            freq = timeframe
        
        # 예상되는 전체 타임스탬프 생성
        full_range = pd.date_range(start=df.index.min(), end=df.index.max(), freq=freq)
        
        # 누락된 타임스탬프 찾기
        if len(full_range) == len(df):
            return df  # 누락된 데이터 없음
            
        # 누락된 타임스탬프에 대한 데이터 채우기
        df = df.reindex(full_range)
        df.reset_index(inplace=True)
        df.rename(columns={'index': 'timestamp'}, inplace=True)
        
        # 전후 값으로 채우기
        for col in df.columns:
            if col != 'timestamp':
                df[col].fillna(method='ffill', inplace=True)
                df[col].fillna(method='bfill', inplace=True)
        
        # Redis에 업데이트된 데이터 저장
        await save_ohlcv_to_redis(df, exchange_name, symbol, timeframe)
        
        return df
            
    except Exception as e:
        logging.error(f"데이터 채우기 중 오류 발생: {exchange_name}:{symbol}:{timeframe} - {str(e)}")
        traceback.print_exc()
        return None

async def save_indicators_to_redis(df, exchange_name, symbol, timeframe):
    """
    계산된 지표 데이터를 Redis에 리스트 형식으로 저장합니다.
    
    Args:
        df: 지표가 계산된 DataFrame
        exchange_name: 거래소 이름
        symbol: 심볼
        timeframe: 타임프레임 (예: '15m', '4h')
    """
    try:
        if df is None or df.empty:
            logging.warning(f"저장할 지표 데이터가 없습니다: {exchange_name}:{symbol}:{timeframe}")
            return False
            
        # 지표 데이터만 추출
        indicators_df = df[['timestamp', 'open', 'high', 'low', 'close', 'volume']].copy()
        
        # DataFrame에 존재하는 지표 컬럼들만 추가
        indicator_columns = ['atr', 'adx', 'plus_di', 'minus_di', 'adx_state', 'main_plot']
        for col in indicator_columns:
            if col in df.columns:
                indicators_df[col] = df[col]
                
        # Redis 키 생성 (지표 데이터용)
        key = f"{exchange_name}:{symbol}:{timeframe}:indicators"
        
        # 기존 데이터 삭제
        redis_client.delete(key)
        
        # DataFrame을 레코드 리스트로 변환
        records = indicators_df.to_dict(orient='records')
        
        # 각 레코드를 JSON 문자열로 변환하여 Redis 리스트에 추가
        pipeline = redis_client.pipeline()
        for record in records:
            # timestamp를 정수로 저장 (datetime 객체는 직렬화 불가)
            if 'timestamp' in record and isinstance(record['timestamp'], pd.Timestamp):
                record['timestamp'] = int(record['timestamp'].timestamp() * 1000)
            
            # 레코드를 JSON 문자열로 변환하여 리스트에 추가
            pipeline.rpush(key, json.dumps(record))
        
        # 파이프라인 실행
        pipeline.execute()
        
        # 마지막 업데이트 시간 저장
        redis_client.set(f"{key}:last_update", int(time.time()))
        
        # TTL 설정 (타임프레임에 따라 다른 TTL 적용)
        ttl = get_ttl_for_timeframe(timeframe)
        if ttl > 0:
            redis_client.expire(key, ttl)
            redis_client.expire(f"{key}:last_update", ttl)
        
        logging.info(f"지표 데이터 Redis 저장 완료: {key} (총 {len(records)}개 레코드)")
        return True
    except Exception as e:
        logging.error(f"지표 데이터 저장 중 오류 발생: {str(e)}")
        traceback.print_exc()
        return False

async def save_grid_results_to_redis(df, exchange_name, symbol, timeframe):
    """
    그리드 거래 결과를 Redis에 저장합니다.
    
    Args:
        df: 그리드 계산이 완료된 DataFrame
        exchange_name: 거래소 이름
        symbol: 심볼
        timeframe: 타임프레임 (예: '15m')
    """
    try:
        if df is None or df.empty:
            logging.warning(f"저장할 그리드 결과가 없습니다: {exchange_name}:{symbol}:{timeframe}")
            return False
            
        # 거래소 유형에 따라 다른 처리
        initial_capital = 10000
        
        if exchange_name in ['bitget_spot', 'okx_spot', 'binance_spot', 'upbit', 'bybit_spot']:
            # 스팟 거래소는 롱 포지션만 계산
            df_long = execute_trading_logic(df, initial_capital, 'long')
            
            # Redis에 저장
            await set_cache(exchange_name, symbol, df_long, 'long')
            
            logging.info(f"그리드 롱 결과 Redis 저장 완료: {exchange_name}:{symbol}:long")
        else:
            # 선물 거래소는 롱/숏/롱숏 모두 계산
            df_long = execute_trading_logic(df, initial_capital, 'long')
            df_short = execute_trading_logic(df, initial_capital, 'short')
            df_longshort = execute_trading_logic(df, initial_capital, 'long-short')
            
            # Redis에 저장
            await set_cache(exchange_name, symbol, df_long, 'long')
            await set_cache(exchange_name, symbol, df_short, 'short')
            await set_cache(exchange_name, symbol, df_longshort, 'long-short')
            
            logging.info(f"그리드 롱/숏/롱숏 결과 Redis 저장 완료: {exchange_name}:{symbol}")
            
        return True
    except Exception as e:
        logging.error(f"그리드 결과 Redis 저장 중 오류 발생: {exchange_name}:{symbol}:{timeframe} - {str(e)}")
        traceback.print_exc()
        return False

async def get_indicators_from_redis(exchange_name, symbol, timeframe):
    """
    Redis에서 지표 데이터를 가져옵니다. Redis 리스트 형식으로 저장된 데이터를 DataFrame으로 변환합니다.
    
    Args:
        exchange_name: 거래소 이름
        symbol: 심볼
        timeframe: 타임프레임 (예: '15m', '4h')
        
    Returns:
        DataFrame: 지표 데이터가 포함된 DataFrame 또는 None
    """
    try:
        # Redis 키 생성 (지표 데이터용)
        key = f"{exchange_name}:{symbol}:{timeframe}:indicators"
        
        # Redis 리스트의 길이 확인
        list_length = redis_client.llen(key)
        
        if list_length == 0:
            logging.warning(f"Redis에서 지표 데이터를 찾을 수 없습니다: {key}")
            return None
        
        # 모든 레코드 가져오기
        records_json = redis_client.lrange(key, 0, -1)
        
        if not records_json:
            logging.warning(f"Redis에서 지표 데이터를 찾을 수 없습니다: {key}")
            return None
        
        # JSON 문자열을 파이썬 객체로 변환
        records = []
        for record_json in records_json:
            try:
                record = json.loads(record_json)
                records.append(record)
            except json.JSONDecodeError as e:
                logging.error(f"JSON 파싱 중 오류 발생: {key} - {str(e)}")
                continue
        
        if not records:
            logging.warning(f"지표 데이터를 파싱할 수 없습니다: {key}")
            return None
        
        # 레코드 리스트를 DataFrame으로 변환
        df = pd.DataFrame(records)
        
        # timestamp 열이 있으면 datetime 형식으로 변환
        if 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                
        return df
            
    except Exception as e:
        logging.error(f"지표 데이터 가져오기 중 오류 발생: {str(e)}")
        traceback.print_exc()
        return None

async def analyze_cached_indicators(exchange_name, symbol, timeframe='15m'):
    """
    Redis에 저장된 지표 데이터를 분석합니다.
    이 함수는 이미 계산되어 Redis에 저장된 지표를 사용하여 추가 분석을 수행합니다.
    
    Args:
        exchange_name: 거래소 이름
        symbol: 심볼
        timeframe: 타임프레임 (기본값: '15m')
        
    Returns:
        dict: 분석 결과
    """
    try:
        # Redis에서 지표 데이터 가져오기
        indicators_df = await get_indicators_from_redis(exchange_name, symbol, timeframe)
        if indicators_df is None or indicators_df.empty:
            logging.warning(f"Redis에 저장된 지표 데이터가 없습니다: {exchange_name}:{symbol}:{timeframe}")
            return None
            
        # 필요한 지표가 있는지 확인
        required_columns = ['timestamp', 'open', 'high', 'low', 'close', 'volume', 'adx', 'plus_di', 'minus_di', 'adx_state']
        missing_columns = [col for col in required_columns if col not in indicators_df.columns]
        if missing_columns:
            logging.warning(f"지표 데이터에 필요한 컬럼이 없습니다: {missing_columns}")
            # 필요한 경우 여기서 누락된 지표 계산 가능
        
        # 여기서 추가 분석 로직 구현
        # 예: 최근 데이터의 ADX 상태 확인
        recent_adx_state = None
        if 'adx_state' in indicators_df.columns and not indicators_df.empty:
            recent_adx_state = indicators_df['adx_state'].iloc[-1]
            
        # 예: MAMA/FAMA 크로스오버 확인
        crossover_signal = None
        if 'main_plot' in indicators_df.columns and len(indicators_df) >= 2:
            # 간단한 이동평균 계산
            indicators_df['sma'] = indicators_df['close'].rolling(window=20).mean()
            # 크로스오버 확인
            if crossover(indicators_df['main_plot'].iloc[-2:], indicators_df['sma'].iloc[-2:]):
                crossover_signal = 'bullish'
            elif crossunder(indicators_df['main_plot'].iloc[-2:], indicators_df['sma'].iloc[-2:]):
                crossover_signal = 'bearish'
                
        # 결과 반환
        result = {
            'symbol': symbol,
            'exchange': exchange_name,
            'timeframe': timeframe,
            'last_update': indicators_df['timestamp'].iloc[-1] if 'timestamp' in indicators_df.columns else None,
            'current_price': indicators_df['close'].iloc[-1] if 'close' in indicators_df.columns else None,
            'adx_state': recent_adx_state,
            'crossover_signal': crossover_signal,
            'indicators_available': [col for col in indicators_df.columns if col not in ['timestamp', 'open', 'high', 'low', 'close', 'volume']]
        }
        
        return result
    except Exception as e:
        logging.error(f"지표 데이터 분석 중 오류 발생: {exchange_name}:{symbol}:{timeframe} - {str(e)}")
        traceback.print_exc()
        return None

async def get_all_symbols_analysis(exchange_name, timeframe='15m', limit=None):
    """
    특정 거래소의 모든 심볼(또는 제한된 수의 심볼)에 대한 지표 분석 결과를 가져옵니다.
    
    Args:
        exchange_name: 거래소 이름
        timeframe: 타임프레임 (기본값: '15m')
        limit: 분석할 최대 심볼 수 (None이면 제한 없음)
        
    Returns:
        list: 각 심볼의 분석 결과 목록
    """
    try:
        # Redis 키 패턴으로 사용 가능한 모든 심볼 찾기
        pattern = f"{exchange_name}:*:{timeframe}:indicators"
        keys = await list_redis_keys(pattern)
        
        if not keys:
            logging.warning(f"분석할 지표 데이터가 없습니다: {exchange_name}:{timeframe}")
            return []
            
        # 심볼 목록 추출
        symbols = []
        for key in keys:
            parts = key.split(":")
            if len(parts) >= 3:
                symbols.append(parts[1])  # 두 번째 부분이 심볼
                
        # 제한이 있으면 적용
        if limit is not None and limit > 0:
            symbols = symbols[:limit]
            
        # 모든 심볼의 분석 결과 수집
        results = []
        for symbol in symbols:
            result = await analyze_cached_indicators(exchange_name, symbol, timeframe)
            if result is not None:
                results.append(result)
                
        # 최근 업데이트 시간 기준으로 정렬
        results.sort(key=lambda x: x.get('last_update', 0) if x.get('last_update') else 0, reverse=True)
        
        return results
    except Exception as e:
        logging.error(f"모든 심볼 분석 중 오류 발생: {exchange_name}:{timeframe} - {str(e)}")
        traceback.print_exc()
        return []

async def trim_front_data(exchange_name, symbol, timeframe='1d', count=100):
    """
    Redis 리스트의 앞부분 데이터를 지정된 개수만큼 제거합니다.
    너무 오래된 데이터를 제거하여 리스트 크기를 관리하는 데 유용합니다.
    
    Args:
        exchange_name (str): 거래소 이름
        symbol (str): 심볼
        timeframe (str): 타임프레임
        count (int): 제거할 데이터 개수
    
    Returns:
        bool: 성공 여부
    """
    try:
        key = f"{exchange_name}:{symbol}:{timeframe}"
        
        # 리스트 길이 확인
        list_length = redis_client.llen(key)
        
        if list_length == 0:
            logging.warning(f"제거할 데이터가 없습니다: {key}")
            return False
        
        # 제거할 개수가 리스트 길이보다 크면 조정
        if count >= list_length:
            count = list_length - 1  # 최소 1개는 남겨둠
            if count <= 0:
                return True
        
        # 앞부분 데이터 제거 (LTRIM은 인덱스 범위를 유지하고 나머지를 제거)
        redis_client.ltrim(key, count, -1)
        
        logging.info(f"데이터 앞부분 {count}개 제거 완료: {key}")
        return True
    except Exception as e:
        logging.error(f"데이터 앞부분 제거 중 오류 발생: {str(e)}")
        traceback.print_exc()
        return False

async def append_new_data(exchange_name, symbol, new_data, timeframe='1d', max_length=10000):
    """
    Redis 리스트의 뒷부분에 새 데이터를 추가합니다.
    이 함수는 새 데이터만 추가하고 기존 데이터는 유지합니다.
    
    Args:
        exchange_name (str): 거래소 이름
        symbol (str): 심볼
        new_data (pd.DataFrame): 추가할 새 데이터
        timeframe (str): 타임프레임
        max_length (int): 리스트의 최대 길이 (초과 시 앞부분 데이터 제거)
    
    Returns:
        bool: 성공 여부
    """
    try:
        if new_data is None or new_data.empty:
            logging.warning(f"추가할 데이터가 없습니다: {exchange_name}:{symbol}:{timeframe}")
            return False
            
        key = f"{exchange_name}:{symbol}:{timeframe}"
        
        # 레코드로 변환
        records = new_data.to_dict(orient='records')
        
        # 각 레코드를 JSON 문자열로 변환하여 Redis 리스트에 추가
        pipeline = redis_client.pipeline()
        for record in records:
            # timestamp를 정수로 저장
            if 'timestamp' in record and isinstance(record['timestamp'], pd.Timestamp):
                record['timestamp'] = int(record['timestamp'].timestamp() * 1000)
            
            # 레코드를 리스트 뒤에 추가
            pipeline.rpush(key, json.dumps(record))
        
        # 파이프라인 실행
        pipeline.execute()
        
        # 리스트 길이 확인 및 조정
        list_length = redis_client.llen(key)
        if list_length > max_length:
            # 앞부분 데이터 제거
            trim_count = list_length - max_length
            await trim_front_data(exchange_name, symbol, timeframe, trim_count)
        
        # 마지막 업데이트 시간 갱신
        redis_client.set(f"{key}:last_update", int(time.time()))
        
        logging.info(f"새 데이터 {len(records)}개 추가 완료: {key}")
        return True
    except Exception as e:
        logging.error(f"새 데이터 추가 중 오류 발생: {str(e)}")
        traceback.print_exc()
        return False

async def get_cache_range(exchange_name, symbol, timeframe='1d', start=0, end=-1):
    """
    Redis 리스트에서 특정 범위의 데이터만 가져옵니다.
    대용량 데이터를 처리할 때 전체 데이터를 가져오지 않고 일부만 가져와 효율성을 높입니다.
    
    Args:
        exchange_name (str): 거래소 이름
        symbol (str): 심볼
        timeframe (str): 타임프레임
        start (int): 시작 인덱스 (0부터 시작)
        end (int): 끝 인덱스 (-1은 마지막 요소를 의미)
    
    Returns:
        pd.DataFrame: 가져온 데이터
    """
    try:
        key = f"{exchange_name}:{symbol}:{timeframe}"
        
        # Redis 리스트의 특정 범위만 가져오기
        records_json = redis_client.lrange(key, start, end)
        
        if not records_json:
            return None
        
        # JSON 문자열을 파이썬 객체로 변환
        records = []
        for record_json in records_json:
            try:
                record = json.loads(record_json)
                records.append(record)
            except json.JSONDecodeError as e:
                logging.error(f"JSON 파싱 중 오류 발생: {key} - {str(e)}")
                continue
        
        if not records:
            return None
        
        # 레코드 리스트를 DataFrame으로 변환
        df = pd.DataFrame(records)
        
        # timestamp 열이 있으면 datetime 형식으로 변환
        if 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                
        return df
            
    except Exception as e:
        logging.error(f"캐시 범위 가져오기 중 오류 발생: {str(e)}")
        traceback.print_exc()
        return None

# ... existing code ...


async def get_okx_instance(user_id):
    # OKX API 키 설정 (읽기 전용 키 사용)
    OKX_API_KEY = OKX_API_KEY
    OKX_SECRET_KEY = OKX_SECRET_KEY
    OKX_PASSPHRASE = OKX_PASSPHRASE
    
    exchange = ccxt.okx({
        'apiKey': OKX_API_KEY,
        'secret': OKX_SECRET_KEY,
        'password': OKX_PASSPHRASE,
        'enableRateLimit': True,
        'options': {
            'defaultType': 'swap',  # 선물 거래 설정
        }
    })
    
    # 비동기 작업 활성화
    if user_id:  # 실제 사용자 요청인 경우
        await exchange.load_markets()
    
    return exchange

async def get_okx_spot_instance(user_id):
    # OKX API 키 설정 (읽기 전용 키 사용)
    OKX_API_KEY = OKX_API_KEY
    OKX_SECRET_KEY = OKX_SECRET_KEY
    OKX_PASSPHRASE = OKX_PASSPHRASE
    
    exchange = ccxt.okx({
        'apiKey': OKX_API_KEY,
        'secret': OKX_SECRET_KEY,
        'password': OKX_PASSPHRASE,
        'enableRateLimit': True,
        'options': {
            'defaultType': 'spot',  # 현물 거래 설정
        }
    })
    
    # 비동기 작업 활성화
    if user_id:  # 실제 사용자 요청인 경우
        await exchange.load_markets()
    
    return exchange

#================================================================================================
# INCREMENTAL CALCULATION OPTIMIZATION
#================================================================================================

class IndicatorState:
    """
    기술 지표의 상태를 저장하고 증분 계산을 가능하게 하는 클래스
    """
    def __init__(self):
        # ADX 관련 상태
        self.adx_last_idx = -1
        self.adx_state = None
        self.plus_di = None
        self.minus_di = None
        self.adx = None
        
        # MAMA/FAMA 관련 상태
        self.mama_last_idx = -1
        self.mama_values = None
        self.fama_values = None
        self.prev_phase = 0
        self.prev_I2 = 0
        self.prev_Q2 = 0
        self.prev_Re = 0
        self.prev_Im = 0
        self.prev_period = 0
        
        # ATR 관련 상태
        self.atr_last_idx = -1
        self.atr_values = None
        self.prev_atr = None
        
        # 그리드 레벨 관련 상태
        self.grid_last_idx = -1
        self.grid_levels = None
        
        # 마지막 저장 시간
        self.last_update_time = None
    
    def to_dict(self):
        """상태를 딕셔너리로 변환하여 Redis에 저장할 수 있게 합니다"""
        return {
            'adx_last_idx': self.adx_last_idx,
            'adx_state': self.adx_state,
            'plus_di': self.plus_di.tolist() if isinstance(self.plus_di, np.ndarray) else self.plus_di,
            'minus_di': self.minus_di.tolist() if isinstance(self.minus_di, np.ndarray) else self.minus_di,
            'adx': self.adx.tolist() if isinstance(self.adx, np.ndarray) else self.adx,
            'mama_last_idx': self.mama_last_idx,
            'mama_values': self.mama_values.tolist() if isinstance(self.mama_values, np.ndarray) else self.mama_values,
            'fama_values': self.fama_values.tolist() if isinstance(self.fama_values, np.ndarray) else self.fama_values,
            'prev_phase': self.prev_phase,
            'prev_I2': self.prev_I2,
            'prev_Q2': self.prev_Q2,
            'prev_Re': self.prev_Re,
            'prev_Im': self.prev_Im,
            'prev_period': self.prev_period,
            'atr_last_idx': self.atr_last_idx,
            'atr_values': self.atr_values.tolist() if isinstance(self.atr_values, np.ndarray) else self.atr_values,
            'prev_atr': self.prev_atr,
            'grid_last_idx': self.grid_last_idx,
            'grid_levels': self.grid_levels.tolist() if isinstance(self.grid_levels, np.ndarray) else self.grid_levels,
            'last_update_time': self.last_update_time
        }
    
    @classmethod
    def from_dict(cls, data):
        """딕셔너리에서 상태를 복원합니다"""
        if not data:
            return cls()
        
        state = cls()
        state.adx_last_idx = data.get('adx_last_idx', -1)
        state.adx_state = data.get('adx_state')
        
        # 숫자 배열 데이터 변환
        for attr in ['plus_di', 'minus_di', 'adx', 'mama_values', 'fama_values', 'atr_values', 'grid_levels']:
            value = data.get(attr)
            if value is not None:
                setattr(state, attr, np.array(value))
        
        # 스칼라 값 복원
        state.prev_phase = data.get('prev_phase', 0)
        state.prev_I2 = data.get('prev_I2', 0)
        state.prev_Q2 = data.get('prev_Q2', 0)
        state.prev_Re = data.get('prev_Re', 0)
        state.prev_Im = data.get('prev_Im', 0)
        state.prev_period = data.get('prev_period', 0)
        state.mama_last_idx = data.get('mama_last_idx', -1)
        state.atr_last_idx = data.get('atr_last_idx', -1)
        state.prev_atr = data.get('prev_atr')
        state.grid_last_idx = data.get('grid_last_idx', -1)
        state.last_update_time = data.get('last_update_time')
        
        return state

async def get_indicator_state(exchange_name, symbol, direction='long'):
    """Redis에서 지표 상태를 가져옵니다"""
    key = f"{exchange_name}:{symbol}:{direction}:indicator_state"
    state_json = redis_client.get(key)
    
    if state_json:
        try:
            state_dict = json.loads(state_json)
            return IndicatorState.from_dict(state_dict)
        except Exception as e:
            logging.error(f"지표 상태 복원 중 오류: {e}")
    
    return IndicatorState()

async def save_indicator_state(state, exchange_name, symbol, direction='long'):
    """지표 상태를 Redis에 저장합니다"""
    key = f"{exchange_name}:{symbol}:{direction}:indicator_state"
    state_dict = state.to_dict()
    state_json = json.dumps(state_dict)
    redis_client.set(key, state_json)
    
    # TTL 설정 (3일)
    redis_client.expire(key, 60 * 60 * 24 * 3)

def calculate_adx_incremental(df, state, dilen=28, adxlen=28):
    """
    증분형 ADX 계산 함수입니다.
    이전 계산 상태를 사용하여 새 데이터에 대해서만 ADX를 계산합니다.
    
    Parameters:
    -----------
    df : pandas.DataFrame
        계산할 OHLCV 데이터프레임
    state : IndicatorState
        이전 계산 상태
    dilen : int
        Directional Index의 기간
    adxlen : int
        ADX의 기간
        
    Returns:
    --------
    tuple
        (adx, plus_di, minus_di) - 계산된 ADX, +DI, -DI 값 배열
    """
    # 데이터프레임이 비어있으면 초기 상태 반환
    if df.empty:
        return np.array([]), np.array([]), np.array([])
    
    start_idx = 0
    
    # 이전 계산 결과가 있는 경우
    if state.adx_last_idx >= 0 and state.adx is not None and state.plus_di is not None and state.minus_di is not None:
        # 마지막으로 계산된 인덱스 다음부터 계산
        start_idx = state.adx_last_idx + 1
        
        # 이미 모든 데이터가 계산되었으면 현재 상태 반환
        if start_idx >= len(df):
            return state.adx, state.plus_di, state.minus_di
            
        # lookback 기간만큼 이전 데이터가 필요
        lookback = max(dilen, adxlen) + 10  # 여유를 두고 충분히 가져옴
        
        # 시작 인덱스 조정 (필요한 과거 데이터 포함)
        calc_start_idx = max(0, start_idx - lookback)
        
        # 계산에 필요한 데이터만 잘라내기
        calc_df = df.iloc[calc_start_idx:].copy()
        
        # DM과 TR 계산
        dm_tr = calculate_dm_tr(calc_df, dilen)
        
        # 기존 상태와 병합하기 위한 오프셋 계산
        offset = len(df) - len(calc_df)
        
        # 이전 결과와 새 결과를 합침
        adx_full = np.concatenate([state.adx[:offset], dm_tr['adx'].values])
        plus_di_full = np.concatenate([state.plus_di[:offset], dm_tr['plus_di'].values])
        minus_di_full = np.concatenate([state.minus_di[:offset], dm_tr['minus_di'].values])
        
        return adx_full, plus_di_full, minus_di_full
    else:
        # 첫 계산 또는 상태가 없는 경우 전체 계산
        dm_tr = calculate_dm_tr(df, dilen)
        
        # ADX 및 DI 값 추출
        adx = dm_tr['adx'].values
        plus_di = dm_tr['plus_di'].values
        minus_di = dm_tr['minus_di'].values
        
        return adx, plus_di, minus_di

def atr_incremental(df, state, length=14):
    """
    증분형 ATR 계산 함수입니다.
    이전 계산 상태를 사용하여 새 데이터에 대해서만 ATR을 계산합니다.
    
    Parameters:
    -----------
    df : pandas.DataFrame
        계산할 OHLCV 데이터프레임
    state : IndicatorState
        이전 계산 상태
    length : int
        ATR 계산 기간
        
    Returns:
    --------
    numpy.ndarray
        계산된 ATR 값 배열
    """
    # 데이터프레임이 비어있으면 초기 상태 반환
    if df.empty:
        return np.array([])
    
    # TR 계산
    df_work = df.copy()
    df_work['tr'] = calculate_tr(df_work)
    
    start_idx = 0
    
    # 이전 계산 결과가 있는 경우
    if state.atr_last_idx >= 0 and state.atr_values is not None and state.prev_atr is not None:
        # 마지막으로 계산된 인덱스 다음부터 계산
        start_idx = state.atr_last_idx + 1
        
        # 이미 모든 데이터가 계산되었으면 현재 상태 반환
        if start_idx >= len(df):
            return state.atr_values
            
        # 충분한 이전 데이터가 필요
        lookback = length + 10  # 여유를 두고 충분히 가져옴
        
        # 시작 인덱스 조정 (필요한 과거 데이터 포함)
        calc_start_idx = max(0, start_idx - lookback)
        
        # 이전 ATR 값 가져오기
        prev_atr = state.prev_atr
        
        # 계산 결과를 저장할 배열
        atr_values = np.zeros(len(df))
        
        # 이전 결과 복사
        atr_values[:start_idx] = state.atr_values[:start_idx]
        
        # 새 데이터에 대해 증분 계산
        for i in range(start_idx, len(df)):
            tr = df_work['tr'].iloc[i]
            if i == 0:
                atr_values[i] = tr
            else:
                atr_values[i] = (prev_atr * (length - 1) + tr) / length
            prev_atr = atr_values[i]
        
        return atr_values
    else:
        # 첫 계산 또는 상태가 없는 경우
        atr_values = np.zeros(len(df))
        
        for i in range(len(df)):
            tr = df_work['tr'].iloc[i]
            if i == 0:
                atr_values[i] = tr
            else:
                atr_values[i] = (atr_values[i-1] * (length - 1) + tr) / length
        
        return atr_values

def compute_mama_fama_incremental(src, state, length=20, fast_limit=0.5, slow_limit=0.05):
    """
    증분형 MAMA/FAMA 계산 함수입니다.
    이전 계산 상태를 사용하여 새 데이터에 대해서만 MAMA/FAMA를 계산합니다.
    
    Parameters:
    -----------
    src : numpy.ndarray or pandas.Series
        가격 데이터 배열
    state : IndicatorState
        이전 계산 상태
    length : int
        계산 기간
    fast_limit : float
        빠른 적응 속도 제한
    slow_limit : float
        느린 적응 속도 제한
        
    Returns:
    --------
    tuple
        (mama, fama) - 계산된 MAMA, FAMA 값 배열
    """
    # 데이터가 비어있으면 초기 상태 반환
    if len(src) == 0:
        return np.array([]), np.array([])
    
    # pandas Series일 경우 값만 추출
    if hasattr(src, 'values'):
        src_values = src.values
    else:
        src_values = np.array(src)
    
    # 이전 계산 결과가 있는 경우
    if (state.mama_last_idx >= 0 and 
            state.mama_values is not None and 
            state.fama_values is not None):
        
        # 마지막으로 계산된 인덱스 다음부터 계산
        start_idx = state.mama_last_idx + 1
        
        # 이미 모든 데이터가 계산되었으면 현재 상태 반환
        if start_idx >= len(src_values):
            return state.mama_values, state.fama_values
        
        # 결과를 저장할 배열 초기화
        mama = np.zeros(len(src_values))
        fama = np.zeros(len(src_values))
        
        # 이전 결과 복사
        if len(state.mama_values) > 0 and start_idx > 0:
            # 배열 크기 체크하여 범위 내에서만 복사
            copy_length = min(start_idx, len(state.mama_values))
            mama[:copy_length] = state.mama_values[:copy_length]
            fama[:copy_length] = state.fama_values[:copy_length]
        
        # 이전 상태 불러오기
        prev_mama = mama[start_idx-1] if start_idx > 0 and len(mama) > start_idx-1 else src_values[0]
        prev_fama = fama[start_idx-1] if start_idx > 0 and len(fama) > start_idx-1 else src_values[0]
        
        # MESA 상태 변수 초기화
        prev_period = state.prev_period if state.prev_period != 0 else 0
        prev_I2 = state.prev_I2 if state.prev_I2 != 0 else 0
        prev_Q2 = state.prev_Q2 if state.prev_Q2 != 0 else 0
        prev_Re = state.prev_Re if state.prev_Re != 0 else 0
        prev_Im = state.prev_Im if state.prev_Im != 0 else 0
        prev_phase = state.prev_phase if state.prev_phase != 0 else 0
        
        # 새 데이터에 대해 계산
        for i in range(start_idx, len(src_values)):
            price = src_values[i]
            
            # 이동 평균 효율성 비율(ER) 계산
            if i < length:
                er = 0
            else:
                price_diff = np.abs(price - src_values[i-length])
                sum_price_changes = np.sum(np.abs(np.diff(src_values[i-length:i+1])))
                er = price_diff / sum_price_changes if sum_price_changes > 0 else 0
            
            # 초기화
            smooth = price
            detrender = 0
            I1 = 0
            Q1 = 0
            
            # MESA 계산
            if i >= 3:
                smooth = (4 * price + 3 * src_values[i-1] + 2 * src_values[i-2] + src_values[i-3]) / 10.0
            
            # 디트렌더 계산
            if i >= 6:
                detrender = (0.0962 * smooth + 0.5769 * src_values[i-2] - 
                            0.5769 * src_values[i-4] - 0.0962 * src_values[i-6])
            
            # 인페이즈 및 쿼드라튜어 컴포넌트 계산
            if i >= 3:
                # 사이클 주기 계산을 위한 MESA 알고리즘 부분
                mesa_period_mult = 0.075 * prev_period + 0.54
                
                I1 = detrender
                Q1 = detrender
                
                # 힐버트 변환 계산
                jI = detrender
                jQ = detrender
                
                I2 = I1 - jQ
                Q2 = Q1 + jI
                
                # 스무딩
                I2 = 0.2 * I2 + 0.8 * prev_I2
                Q2 = 0.2 * Q2 + 0.8 * prev_Q2
                
                # 주기 추정
                Re = I2 * prev_I2 + Q2 * prev_Q2
                Im = I2 * prev_Q2 - Q2 * prev_I2
                
                # 스무딩
                Re = 0.2 * Re + 0.8 * prev_Re
                Im = 0.2 * Im + 0.8 * prev_Im
                
                # 주기 계산
                period = prev_period
                if Re != 0 and Im != 0:
                    try:
                        period = 2 * np.pi / np.arctan(Im / Re)
                    except:
                        # 에러 발생 시 이전 주기 유지
                        period = prev_period
                
                # 주기 제한
                if period > 1.5 * prev_period and prev_period > 0:
                    period = 1.5 * prev_period
                elif period < 0.67 * prev_period and prev_period > 0:
                    period = 0.67 * prev_period
                period = max(min(period, 50), 6)
                
                # 스무딩
                period = 0.2 * period + 0.8 * prev_period
                
                # 위상 계산
                phase = prev_phase
                if I1 != 0:
                    try:
                        phase = 180 / np.pi * np.arctan(Q1 / I1)
                    except:
                        # 에러 발생 시 이전 위상 유지
                        phase = prev_phase
                
                # 위상 변화율 계산
                delta_phase = abs(prev_phase - phase)
                delta_phase = max(delta_phase, 1)
                
                # 적응 계수 계산
                alpha = er / delta_phase
                alpha = max(alpha, er * 0.1)
                
                # MAMA/FAMA 계산에 사용할 적응 계수 제한
                phase_rate = (fast_limit - slow_limit) * alpha + slow_limit
                phase_rate = max(min(phase_rate, fast_limit), slow_limit)
                
                # MAMA/FAMA 업데이트
                mama[i] = phase_rate * price + (1 - phase_rate) * prev_mama
                fama[i] = 0.5 * phase_rate * mama[i] + (1 - 0.5 * phase_rate) * prev_fama
                
                # 다음 반복을 위한 값 업데이트
                prev_mama = mama[i]
                prev_fama = fama[i]
                prev_period = period
                prev_I2 = I2
                prev_Q2 = Q2
                prev_Re = Re
                prev_Im = Im
                prev_phase = phase
            else:
                # 초기 값 설정
                mama[i] = price
                fama[i] = price
                prev_mama = price
                prev_fama = price
        
        # 상태 업데이트
        state.prev_phase = prev_phase
        state.prev_I2 = prev_I2
        state.prev_Q2 = prev_Q2
        state.prev_Re = prev_Re
        state.prev_Im = prev_Im
        state.prev_period = prev_period
        
        # 마지막 계산 인덱스 업데이트
        state.mama_last_idx = len(src_values) - 1
        
        # 필터링 (선택적)
        try:
            mama_series = pd.Series(mama)
            fama_series = pd.Series(fama)
            mama = mama_series.ewm(span=5, adjust=False).mean().values
            fama = fama_series.ewm(span=5, adjust=False).mean().values
        except Exception as e:
            logging.warning(f"MAMA/FAMA 필터링 오류: {e}")
        
        return mama, fama
    else:
        # 첫 계산 또는 상태가 없는 경우, 기존 함수 호출
        return compute_mama_fama(src, length)

if __name__ == "__main__":
    asyncio.run(main())