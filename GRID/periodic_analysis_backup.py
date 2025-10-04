# -*- coding: utf-8 -*-

from math import e
import os
import sys
from datetime import datetime, timedelta, timezone, date
import datetime as dt
import pandas as pd
import asyncio
import pytz
import ccxt.async_support as ccxt  # noqa: E402
import instance
import ccxt.pro as ccxtpro
import random
import traceback
import numpy as np
from pathlib import Path
from regex import B, E
from scipy.signal import hilbert
import glob
import aiohttp
from shared.utils import path_helper
import time
import logging
import psutil
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
import functools
from instance_manager import get_exchange_instance, start_cleanup_task
import fcntl
from io import StringIO
from dateutil import parser
from functools import lru_cache
from collections import defaultdict
from redis.asyncio import Redis
from redis_connection_manager import RedisConnectionManager
import json
#================================================================
# REDIS
#================================================================
redis_manager = RedisConnectionManager()


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
async def retry_async(func, *args, **kwargs):
    func_name = func.__name__  # 함수 이름 가져오기
    #print(f"Retrying {func_name}")
    for attempt in range(MAX_RETRIES):
        try:
            #print(f"Attempting {func_name}: try {attempt + 1}/{MAX_RETRIES}")
            return await func(*args, **kwargs)
        except Exception as e:
            print(f"{func_name} failed on attempt {attempt + 1}/{MAX_RETRIES}. Error: {str(e)}")
            if attempt == MAX_RETRIES - 1:
                print(f"Maximum retries reached for {func_name}. Exiting.")
                raise e
            await asyncio.sleep(random.random())
            await asyncio.sleep(RETRY_DELAY)

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
@lru_cache(maxsize=100)
def get_cached_data(file_path, timestamp):
    return pd.read_csv(file_path)



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
async def set_cache(exchange_name, symbol, data):
    redis_key = f"grid_level:{exchange_name}:{symbol}"
    
    # 현재 시간을 기준으로 다음 15분봉 마감 시간 계산
    now = datetime.now()
    minutes_until_next_15 = 15 - (now.minute % 15)
    seconds_until_next_15 = minutes_until_next_15 * 60 - now.second
    next_15_min_close = now + timedelta(seconds=seconds_until_next_15)
    
    # DataFrame을 JSON으로 변환
    json_data = data.tail(200).to_json(orient='split', date_format='iso')
    
    # 데이터와 만료 시간을 함께 저장
    cache_data = {
        'data': json_data,
        'expiration': next_15_min_close.isoformat()
    }
    
    redis_conn = await redis_manager.get_connection_async()
    await redis_conn.set(redis_key, json.dumps(cache_data))
    print(f"Cache set for {exchange_name} {symbol}")
    
    # 만료 시간을 다음 15분봉 마감 시간으로 설정
    await redis_conn.expireat(redis_key, int(next_15_min_close.timestamp()))

async def get_cache(exchange_name, symbol):
    key = f"grid_level:{exchange_name}:{symbol}"
    redis_conn = await redis_manager.get_connection_async()
    cached = await redis_conn.get(key)
    if cached:
        cache_data = json.loads(cached)
        expiration = datetime.fromisoformat(cache_data['expiration'])
        if datetime.now() < expiration:
            # JSON을 DataFrame으로 변환
            return pd.read_json(StringIO(cache_data['data']), orient='split')
    return None


#================================================================================================
# F E T C H I N G   A N D   S A V I N G   D A T A
#================================================================================================



async def fetching_data(exchange_instance, exchange_name, symbol, user_id, force_refetch=False):
    timeframes = ['15m', '4h']
    semaphore = asyncio.Semaphore(4)
    
    results = await fetch_symbol_data(exchange_instance, symbol, timeframes, semaphore, exchange_name, user_id, force_refetch = False)
    
    ohlcv_data = results.get('15m', pd.DataFrame())
    ohlcv_data_4h = results.get('4h', pd.DataFrame())
    
    return ohlcv_data, ohlcv_data_4h

def calculate_csv(exchange_name, symbol, ohlcv_data, ohlcv_data_4h):
    symbol_name = symbol.replace("/", "")
    folder_path_long = path_helper.grid_dir / exchange_name/ 'long'
    folder_path_short = path_helper.grid_dir / exchange_name/ 'short'
    folder_path_longshort = path_helper.grid_dir / exchange_name/ 'long-short'
    file_path = folder_path_long / f'trading_strategy_results_{symbol_name}.csv'
    if ohlcv_data is not None:
        try:
            if file_path.exists():
                existing_data = pd.read_csv(file_path)
                if not existing_data.empty and len(existing_data) > 1:
                    last_timestamp = existing_data['timestamp'].iloc[-1]
                    ohlcv_data = ohlcv_data
                    ohlcv_data_4h = ohlcv_data_4h
                    
                    #ohlcv_data = ohlcv_data[ohlcv_data.index > last_timestamp]
                    #ohlcv_data_4h = ohlcv_data_4h[ohlcv_data_4h.index > last_timestamp]
                else:
                    ohlcv_data = ohlcv_data
                    ohlcv_data_4h = ohlcv_data_4h
                    
                
            else:
                ohlcv_data = ohlcv_data
                ohlcv_data_4h = ohlcv_data_4h
            dilen = 28
            adxlen = 28
            # Perform calculations only on new data
            #start_time = datetime.now()
            try:
                ohlcv_data_4h = calculate_adx(ohlcv_data_4h, dilen, adxlen)
                ohlcv_data['adx_state'] = 0

                ohlcv_data_4h['adx_state'] = 0
                ohlcv_data = atr(ohlcv_data, 14)
                ohlcv_data_4h = update_adx_state(ohlcv_data_4h)  # 상태 업데이트 함수 호출
                ohlcv_data = map_4h_adx_to_15m(ohlcv_data_4h, ohlcv_data)
                mama, fama = compute_mama_fama(ohlcv_data['close'], length = 20)
                ohlcv_data['main_plot'] = fama
                ohlcv_data = initialize_orders(ohlcv_data)
                ohlcv_data = calculate_grid_levels(ohlcv_data)
                initial_capital = 10000
            except Exception as e:
                if "None of" in str(e):
                    print(f"Missing DF calculating data for {symbol}: {e}. Exiting analysis.")
                    return None
                print(f"Missing DF calculating data for {symbol}: {e}")
                print(traceback.format_exc())
                return None
            #=======================================
            #start_time = datetime.now()
            if exchange_name in ['bitget_spot', 'okx_spot', 'binance_spot', 'upbit', 'bybit_spot']:
                df_long = execute_trading_logic(ohlcv_data, initial_capital, 'long')
                os.makedirs(folder_path_long, exist_ok=True)
                df_long.to_csv(f'{folder_path_long}/trading_strategy_results_{symbol_name}.csv', index=True)
                df_long.reset_index(inplace=True)
                return df_long, None, None
            else:
                with ThreadPoolExecutor(max_workers=3) as executor:
                    futures = [
                        executor.submit(execute_trading_logic, ohlcv_data, initial_capital, 'long'),
                        executor.submit(execute_trading_logic, ohlcv_data, initial_capital, 'short'),
                        executor.submit(execute_trading_logic, ohlcv_data, initial_capital, 'long-short')
                    ]
                    df_long, df_short, df_longshort = [future.result() for future in futures]
    
                #end_time = datetime.now()
                #print(f"Time taken to execute trading logic: {end_time - start_time}")
            #=======================================
            os.makedirs(folder_path_long, exist_ok=True)
            df_long.to_csv(f'{folder_path_long}/trading_strategy_results_{symbol_name}.csv', index=True)
            df_long.reset_index(inplace=True)
            os.makedirs(folder_path_short, exist_ok=True)
            df_short.to_csv(f'{folder_path_short}/trading_strategy_results_{symbol_name}.csv', index=True)
            df_short.reset_index(inplace=True)
            os.makedirs(folder_path_longshort, exist_ok=True)
            df_longshort.to_csv(f'{folder_path_longshort}/trading_strategy_results_{symbol_name}.csv', index=True)
            df_longshort.reset_index(inplace=True)
            #start_time = datetime.now()
            #import grid
            #asyncio.run(grid.plot_trading_signals(df_longshort, symbol_name))
            ##end_time = datetime.now()
            ##print(f"Time taken to plot trading signals: {end_time - start_time}")
            print(f'{symbol} Trading strategy results saved to CSV')

            return df_long, df_short, df_longshort
        except Exception as e:
            error_message = str(e)
            if "None of" in error_message:
                print(f"Error analyzing {symbol}: {e}. Exiting analysis.")
                return None
            else:
                print(f"Error analyzing {symbol}: {e}")
                print(traceback.format_exc())
    else:
        print("Analysis stopped. Exiting.")
        return None
 
 
    
    
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
    # 경로 패턴을 사용하여 해당 거래소 폴더 내의 모든 CSV 파일을 찾습니다.
    exchange_name = str(exchange_name)
    # 폴더 경로 설정
    summary_dir = path_helper.grid_dir / exchange_name / direction

    # 폴더가 없으면 생성
    os.makedirs(summary_dir, exist_ok=True)
    
    print(f"{exchange_name}의 거래 전략 요약을 시작합니다.")
    pattern = os.path.join(summary_dir, "trading_strategy_results_*.csv")
    files = glob.glob(pattern)
    
    results = []
    for file_path in files: 
        df = pd.read_csv(file_path)
        if not df.empty and 'total_profit' in df.columns:
            last_total_profit = df['total_profit'].iloc[-1]
            # total_profit이 2,000 이상인 경우에만 100으로 나누어 저장합니다.
            if last_total_profit >= 2000:
                last_total_profit /= 100
            elif last_total_profit <= -2000:
                last_total_profit /= 100
            elif last_total_profit >= 900:
                last_total_profit /= 10
            elif last_total_profit <= -100:
                last_total_profit /= 100
            
            
            # 파일명에서 심볼 이름을 추출합니다.
            symbol = os.path.basename(file_path).replace('trading_strategy_results_', '').replace('.csv', '')
            results.append({'symbol': symbol, 'total_profit': last_total_profit})


    # 결과를 하나의 데이터프레임으로 합치고 CSV 파일로 저장합니다.
    summary_df = pd.DataFrame(results)
    summary_file_path = path_helper.grid_dir / exchange_name / direction  / f"{exchange_name}_summary_trading_results.csv"
    summary_df.to_csv(summary_file_path, index=False)
    print(f"{exchange_name}의 거래 전략 요약이 완료되었습니다. 파일 경로: {summary_file_path}")


async def get_all_okx_usdt_swap_symbols():
    """OKX 거래소의 모든 USDT 선물 마켓 종목과 거래량을 비동기적으로 가져오는 함수"""
    # OKX 선물 API 엔드포인트
    url = "https://www.okx.com/api/v5/market/tickers?instType=SWAP"

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
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

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
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

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
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

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
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
#def get_white_list_from_file(file_name: str):
#    file_path = file_name
#    try:
#        with open(file_path, 'r') as file:
#            white_list = json.load(file)
#            #print('[ LIST]', white_list)
#            return white_list
#    except FileNotFoundError:
#        print(f"No such file: {file_name}")
#        return []  # 파일이 없는 경우 빈 리스트 반환
    
async def handle_symbol(exchange_instance, symbol, exchange_name, semaphore, executor):
    await asyncio.sleep(2)

    async with semaphore:
        try:
            symbol_name = symbol.replace("/", "")
            print(f"Analyzing {symbol}...")
            await asyncio.sleep(random.uniform(0.4, 0.7))
            directions = ['long', 'short', 'long-short']
            folder_paths = [path_helper.grid_dir / exchange_name / direction for direction in directions]
            print(folder_paths)
            csv_paths = [folder_path / f'trading_strategy_results_{symbol_name}.csv' for folder_path in folder_paths]
            current_time = datetime.now()
            last_15m_boundary = current_time - timedelta(minutes=current_time.minute % 15, seconds=current_time.second, microseconds=current_time.microsecond)
            # Check if any results file doesn't exist or is out of date
            need_update = False
            for path in csv_paths:
                if not Path(path).exists():
                    need_update = True
                    break
                file_mod_time = datetime.fromtimestamp(os.path.getmtime(path))
                if file_mod_time <= last_15m_boundary:
                    need_update = True
                    break
        except Exception as e:
            logging.error(f"Error analyzing {symbol}: {e}")
            logging.debug(traceback.format_exc())
        try:
            if need_update:
                print("Updating data for all directions...")
                try:
                    ohlcv_data, ohlcv_data_4h = await fetching_data(exchange_instance, exchange_name = exchange_name, symbol = symbol, user_id = 999999999, force_refetch=False)
                    await asyncio.sleep(2)
                except Exception as e:
                    print(f"exception occured on ohlcv data {symbol}")
                try:
                    loop = asyncio.get_running_loop()
                    result = await loop.run_in_executor(
                        executor, 
                        calculate_csv, 
                        exchange_name, symbol, ohlcv_data, ohlcv_data_4h
                    )
                except Exception as e:
                    print(f"Error analyzing {symbol}: {e}")
                    print(traceback.format_exc())
                return 
        except Exception as e:
            print(f"Error analyzing {symbol}: {e}")
            print(traceback.format_exc())


    


async def periodic_analysis(exchange_name, interval=14400):
    # 비동기로 실행할 모든 작업을 수행
    exchange_instance = await get_exchange_instance(exchange_name, user_id=999999999)
    executor = ProcessPoolExecutor(max_workers=4)
    semaphore_upbit = asyncio.Semaphore(3) 
    semaphore_binance = asyncio.Semaphore(3) 
    semaphore_okx = asyncio.Semaphore(3) 
    semaphore_bybit = asyncio.Semaphore(3) 
    semaphore_biget = asyncio.Semaphore(3) 
    while True:  # running_event가 set 상태인 동안 실행
        start_time = asyncio.get_event_loop().time()
        # 거래소별로 심볼 리스트를 가져오는 로직
        await asyncio.sleep(1)
        if exchange_name == 'binance':
            symbols = await get_all_binance_usdt_symbols()
            semaphore = semaphore_binance
        elif exchange_name == 'upbit':
            symbols = await get_all_upbit_krw_symbols()
            semaphore = semaphore_upbit
        if exchange_name == 'okx':
            symbols = await get_all_okx_usdt_swap_symbols()
            semaphore = semaphore_okx
        elif exchange_name == 'binance_spot':
            symbols = await get_all_binance_usdt_spot_symbols()
            semaphore = semaphore_binance
        elif exchange_name == 'okx_spot':
            symbols = await get_all_okx_usdt_spot_symbols()
            semaphore = semaphore_okx
        #elif exchange_name == 'bybit_spot':
        #    symbols = await get_all_bybit_usdt_spot_symbols()
        #    semaphore = semaphore_bybit
        #elif exchange_name == 'bitget_spot':
        #    symbols = await get_all_bitget_usdt_spot_symbols()
        #    semaphore = semaphore_biget
        #elif exchange_name == 'bybit':
        #    symbols = await get_all_bybit_usdt_symbols()
        #    semaphore = semaphore_bybit
        #elif exchange_name == 'bitget':
        #    symbols = await get_all_bitget_usdt_symbols()
        #    semaphore = semaphore_biget
        tasks = [handle_symbol(exchange_instance, symbol, exchange_name, semaphore, executor) for symbol in symbols]
        await asyncio.gather(*tasks)
        if exchange_name in ['bitget_spot', 'okx_spot', 'binance_spot', 'upbit', 'bybit_spot']:
            await summarize_trading_results(exchange_name, 'long')
        else : 
            await summarize_trading_results(exchange_name, 'long')
            await summarize_trading_results(exchange_name, 'short')
            await summarize_trading_results(exchange_name, 'long-short')
        finished_time = asyncio.get_event_loop().time()
        elapsed_time = finished_time - start_time
        print(f"==========\nElapsed time: {elapsed_time:.2f} seconds\n==========")
        print("Analyze all symbols complete. Waiting for the next interval.")
        await asyncio.sleep(interval)  # 다음 분석 주기까지 대기



async def fetch_ohlcvs(exchange_instance, symbol, timeframe, since, limit):
    ohlcv_data = []
    print(f"Fetching {symbol} data...")
    max_retries = 4  # 최대 재시도 횟수 설정
    retries = 0
    while since < exchange_instance.milliseconds():
        try:
            await asyncio.sleep(random.random())
            await asyncio.sleep(0.3)  # Rate limit sleep
            data = await retry_async(exchange_instance.fetch_ohlcv, symbol, timeframe, since, limit)
            if len(data) == 0:
                break
            since = data[-1][0] + (exchange_instance.parse_timeframe(timeframe) * 1000)  # Increment by timeframe in milliseconds
            ohlcv_data.extend(data)
            await asyncio.sleep(exchange_instance.rateLimit / 500)  # Rate limit sleep
            retries = 0  # 성공 시 재시도 횟수 초기화
        except ccxt.NetworkError as e:
            print(f"Network error: {e}, retrying...")
            retries += 1
            if retries >= max_retries:
                print("Max retries reached, stopping...")
                break
            await asyncio.sleep(2)
        except ccxt.ExchangeError as e:
            print(f"Exchange error: {e}, stopping...")
            break
        except Exception as e:
            print(f"Error fetching data: {e}, retrying...")
            retries += 1
            if retries >= max_retries:
                print("Max retries reached, stopping...")
                break
            await asyncio.sleep(4)
    print(f"Fetched {len(ohlcv_data)} data points for {symbol}")
    return ohlcv_data

async def fetch_all_ohlcvs(exchange_name,exchange_instance, symbol, timeframe, last_timestamp, user_id, max_retries=3):
    try:

        # Set limit based on exchange
        limit = 1000 if exchange_name == 'binance' or 'binance_spot' in exchange_name else 100
        
        # Calculate the start time (from last timestamp)
        if last_timestamp and pd.notna(last_timestamp):
            try:
                since = int(last_timestamp.timestamp() * 1000) + (exchange_instance.parse_timeframe(timeframe) * 1000)
            except AttributeError:
                logging.warning(f"Invalid last_timestamp for {symbol}: {last_timestamp}. Using default time range.")
                since = exchange_instance.milliseconds() - (30 * 24 * 60 * 60 * 1000)  # 60 days ago
        else:
            since = exchange_instance.milliseconds() - (30 * 24 * 60 * 60 * 1000)  # 60 days ago
        
        end_time = exchange_instance.milliseconds()

        all_ohlcvs = []
        while since < end_time:
            for attempt in range(max_retries):
                try:
                    ohlcvs = await retry_async(fetch_ohlcvs, exchange_instance, symbol, timeframe, since, limit)
                    all_ohlcvs.extend(ohlcvs)
                    if len(ohlcvs) < limit:
                        since = end_time  # Break the outer loop
                    else:
                        since = ohlcvs[-1][0] + (exchange_instance.parse_timeframe(timeframe) * 1000)
                    break
                except Exception as e:
                    print(f"Attempt {attempt+1} failed: {e}")
                    backoff = (2 ** attempt) + (time.time() % 1)  # Exponential backoff
                    await asyncio.sleep(backoff)

            if attempt == max_retries - 1:
                print(f"Max retries reached for {symbol} at {since}")
                break
    except Exception as e:
        print(f"Error fetching data for {symbol}2: {e}")
        print(traceback.format_exc())   
        return None
        
        
    # Remove any duplicate timestamps
    unique_ohlcvs = []
    seen = set()
    for ohlcv in all_ohlcvs:
        if ohlcv[0] not in seen:
            unique_ohlcvs.append(ohlcv)
            seen.add(ohlcv[0])
    
    # Convert to DataFrame
    ohlcv_df = pd.DataFrame(unique_ohlcvs, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    ohlcv_df['timestamp'] = pd.to_datetime(ohlcv_df['timestamp'], unit='ms')
    
    # Convert to KST
    kst = pytz.timezone('Asia/Seoul')
    ohlcv_df['timestamp'] = ohlcv_df['timestamp'].dt.tz_localize('UTC').dt.tz_convert(kst)
    
    return ohlcv_df


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

def get_last_timestamp_from_csv(path, timestamp_column='timestamp'):
    try:
        if not os.path.exists(path):
            logging.warning(f"File not found: {path}")
            return None
        
        df = pd.read_csv(path)
        
        if df.empty:
            logging.warning(f"CSV file is empty: {path}")
            return None
        
        if timestamp_column not in df.columns:
            logging.error(f"Column '{timestamp_column}' not found in the CSV file")
            return None
        
        last_timestamp = pd.to_datetime(df[timestamp_column].iloc[-1])
        return last_timestamp

    except PermissionError:
        logging.error(f"Permission denied: Unable to access file {path}")
    except pd.errors.EmptyDataError:
        logging.warning(f"CSV file is empty: {path}")
    except Exception as e:
        logging.error(f"An unexpected error occurred: {str(e)}")
    
    return None

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
def fill_missing_data(csv_path, timeframe):
    try:
        df = pd.read_csv(csv_path)
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
        missing_timestamps = full_range.difference(df.index)
        
        if not missing_timestamps.empty:
            print(f"Found {len(missing_timestamps)} missing timestamps.")
            # 누락된 타임스탬프에 대해 NaN 값을 가진 행 추가
            for ts in missing_timestamps:
                df.loc[ts] = [np.nan] * len(df.columns)
        
        # 인덱스 재정렬 및 NaN 값 보간
        df = df.sort_index().interpolate()
        
        # timestamp를 다시 열로 만들기
        df.reset_index(inplace=True)
        df.rename(columns={'index': 'timestamp'}, inplace=True)
        
        # CSV 파일 업데이트
        df.to_csv(csv_path, index=False)
        print(f"Updated CSV file with filled data: {csv_path}")
        
        # 디버그: 누락된 데이터가 어떻게 채워졌는지 확인
        #if not missing_timestamps.empty:
        #    print("Sample of filled data:")
        #    #print(df[df['timestamp'].isin(missing_timestamps)].head())
    except pd.errors.EmptyDataError:
        print(f"Error: The CSV file is empty or invalid: {csv_path}")
    except Exception as e:
        print(f"An unexpected error occurred while processing {csv_path}: {str(e)}")
        
def parse_timestamp(ts, prev_ts=None, interval=None):
    if pd.isna(ts) or ts == "":
        if prev_ts is not None and interval is not None:
            return prev_ts + interval
        return pd.NaT
    
    if isinstance(ts, (int, float)):
        return pd.to_datetime(ts, unit='ms', utc=True).tz_convert('Asia/Seoul')
    
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


async def save_ohlcv_to_csv(ohlcv_df, exchange_name, symbol, timeframe):
    folder_path = path_helper.grid_dir / exchange_name
    os.makedirs(folder_path, exist_ok=True)

    symbol_name = symbol.replace("/", "")
    if timeframe == '15m':
        path_15m = folder_path / f'{symbol_name}_15m.csv'
        if os.path.exists(path_15m):
            df_existing = pd.read_csv(path_15m)
            if not df_existing.empty:
                if not ohlcv_df.empty:
                    ohlcv_df = pd.concat([df_existing, ohlcv_df]).drop_duplicates(subset='timestamp').reset_index(drop=True)
                else:
                    ohlcv_df = df_existing
        else:
            df_existing = pd.DataFrame()
        if not ohlcv_df.empty or not df_existing.empty:
            ohlcv_df.to_csv(path_15m, index=False)
    elif timeframe == '4h':
        path_4h = folder_path / f'{symbol_name}_4h.csv'
        if os.path.exists(path_4h):
            df_existing = pd.read_csv(path_4h)
            if not df_existing.empty:
                if not ohlcv_df.empty:
                    ohlcv_df = pd.concat([df_existing, ohlcv_df]).drop_duplicates(subset='timestamp').reset_index(drop=True)
                else:
                    ohlcv_df = df_existing
        else:
            df_existing = pd.DataFrame()
        if not ohlcv_df.empty or not df_existing.empty:
            ohlcv_df.to_csv(path_4h, index=False)
    
    
#================================================================================================@
async def fetch_symbol_data(exchange_instance, symbol, timeframes, semaphore, exchange_name, user_id, force_refetch=False):
    results = {}
    async with semaphore:
        for timeframe in timeframes:
            folder_path = path_helper.grid_dir / exchange_name
            symbol_name = symbol.replace("/", "")
            file_path = folder_path / f'{symbol_name}_{timeframe}.csv'
            
            if not force_refetch:
                last_timestamp = get_last_timestamp_from_csv(file_path)
            else:
                last_timestamp = None
                
            new_data = await retry_async(fetch_all_ohlcvs, exchange_name, exchange_instance, symbol, timeframe, last_timestamp, user_id)
            if new_data is not None and not new_data.empty:
                if os.path.exists(file_path) and not force_refetch:
                    existing_df = pd.read_csv(file_path, dtype={'timestamp': str})
                    existing_df = fill_missing_timestamps(existing_df, symbol)
                    existing_df = existing_df.dropna(subset=['timestamp'])
                    existing_df = existing_df.sort_values('timestamp')
                    combined_df = pd.concat([existing_df, new_data]).drop_duplicates(subset=['timestamp']).sort_values('timestamp')
                else:
                    combined_df = new_data
                combined_df.to_csv(file_path, index=False)
                ##print(f"Saved and updated {timeframe} data for {symbol} to CSV.")
                
                # 누락된 데이터 채우기
                fill_missing_data(file_path, timeframe)
                
                # 결과 저장
                results[timeframe] = combined_df
            else:
                print(f"No new data for {symbol} {timeframe}")
                # 기존 데이터 로드
                if os.path.exists(file_path):
                    results[timeframe] = pd.read_csv(file_path)
                    results[timeframe]['timestamp'] = pd.to_datetime(results[timeframe]['timestamp'])
                else:
                    results[timeframe] = pd.DataFrame()  # 빈 DataFrame 반환
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
        
        for symbol, data in zip(symbols, results):
            if timeframe in data:
                print(f"Updated {symbol} for {timeframe}: {len(data[timeframe])} rows")
        
        # 다음 업데이트까지 대기
        await asyncio.sleep(UPDATE_INTERVALS[timeframe])

async def main():
    exchange_name = 'okx'
    user_id = '1234'  # 적절한 사용자 ID를 입력하세요
    #timeframes = ['1m', '5m', '15m', '30m', '1h', '4h', '1d']  # 원하는 시간프레임을 설정하세요
    timeframes = ['1m']  # 원하는 시간프레임을 설정하세요

    exchange_class = getattr(ccxt, exchange_name)
    exchange_instance = exchange_class()
    
    symbols = await get_all_okx_usdt_swap_symbols()
    semaphore = asyncio.Semaphore(4)  # 동시 요청 수를 5로 제한

    # 각 타임프레임별로 업데이트 태스크 생성
    update_tasks = [
        update_timeframe(exchange_instance, symbols, timeframe, semaphore, exchange_name, user_id)
        for timeframe in timeframes
    ]

    # 모든 업데이트 태스크 동시 실행
    await asyncio.gather(*update_tasks)

if __name__ == "__main__":
    asyncio.run(main())