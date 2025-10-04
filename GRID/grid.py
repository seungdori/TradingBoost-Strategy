from calendar import c
from datetime import datetime, timedelta, timezone, date

import time

from typing import List, Optional, Dict, Any, Union
import aioschedule as schedule
import random

from fastapi import params
from regex import E
import websockets
import ccxt.pro
from matplotlib.pyplot import grid
import numpy as np
import pandas as pd
from scipy.signal import hilbert
import ccxt
import plotly.graph_objects as go
from plotly.offline import plot
from plotly.subplots import make_subplots
import plotly.io as pio

import central_schedule
import redis_database
import strategy
import os
import math
import requests
import asyncio

import aiohttp
from HYPERRSI import telegram_message
from get_minimum_qty import round_to_qty, get_lot_sizes,get_perpetual_instruments
from routes.connection_manager import ConnectionManager
from routes.logs_route import add_log_endpoint as add_user_log
import logging
import aiosqlite
from functools import wraps
import glob
from pathlib import Path

import json
from redis_database import get_user, update_take_profit_orders_info, update_active_grid, initialize_active_grid
import instance
import matplotlib.pyplot as plt
import pytz
from decimal import Decimal, ROUND_HALF_UP
from queue import Queue
import hmac
import base64
import hashlib
import os
import logging
import traceback
import ccxt.pro as ccxtpro
from ccxt.async_support import NetworkError, ExchangeError
from shared.constants.error import TradingErrorName
from shared.dtos.bot_state import BotStateDto, BotStateKeyDto, BotStateError
from shared.dtos.trading import WinrateDto
from shared.utils import path_helper
import periodic_analysis
from shared_state import cancel_state, user_keys
import concurrent.futures
from functools import partial
from instance_manager import get_exchange_instance

from price_subscriber import global_price_subscriber

from shared.config import OKX_API_KEY, OKX_SECRET_KEY, OKX_PASSPHRASE  # 환경 변수에서 키 가져오기

completed_tasks = set()
#from redis_connection_manager import RedisConnectionManager
import redis.asyncio as aioredis
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

from shared.config import settings

REDIS_PASSWORD = settings.REDIS_PASSWORD
if REDIS_PASSWORD:
    pool = aioredis.ConnectionPool.from_url(
        'redis://localhost', 
        max_connections=200,
        encoding='utf-8', 
        decode_responses=True,
        password=REDIS_PASSWORD
    )
    redis_client = aioredis.Redis(connection_pool=pool)
else:
    pool = aioredis.ConnectionPool.from_url(
        'redis://localhost', 
        max_connections=200,
        encoding='utf-8', 
        decode_responses=True
    )
    redis_client = aioredis.Redis(connection_pool=pool)

async def get_redis_connection():
    return redis_client




completed_tasks = set()
running_symbols = set()
completed_symbols = set()
manager = ConnectionManager()
import redis.asyncio as aioredis

logging.basicConfig(filename='app.log', filemode='w', format='%(name)s - %(levelname)s - %(message)s', level=logging.DEBUG)


async def set_redis_data(redis, key, data, expiry=144000):  # 기본 만료 시간 144000초(40시간)
    await redis.set(key, json.dumps(data), ex=expiry)

async def get_redis_data(redis, key):
    data = await redis.get(key)
    return json.loads(data) if data else None


class QuitException(Exception):
    pass

class AddAnotherException(Exception):
    pass
###################
#======TOOLS======#
###################

def parse_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.lower() in ('true', '1', 'yes', 'on')
    return False

async def set_running_symbols(redis, user_key, symbols):
    current_symbols = await redis.hget(user_key, 'running_symbols')
    current_symbols = json.loads(current_symbols.decode('utf-8') if isinstance(current_symbols, bytes) else current_symbols or '[]')
    current_symbols.extend([s for s in symbols if s not in current_symbols])
    await redis.hset(user_key, 'running_symbols', json.dumps(current_symbols))
    print(f"Updated running_symbols: {current_symbols}")  # 디버그 출력
    
async def check_running_symbols(redis, user_key, symbol):
    running_symbols = await redis.hget(user_key, 'running_symbols')
    running_symbols = json.loads(running_symbols.decode('utf-8') if isinstance(running_symbols, bytes) else running_symbols or '[]')
    running_symbol = symbol in running_symbols
    print(f"Debug: running_symbols = {running_symbols}, symbol {symbol} in running_symbols: {running_symbol}")  # 디버그 출력
    return running_symbol


#####TODO : 테스트 for exchange_instance재활용
#async def get_exchange_instance(exchange_name, user_id):
#    exchange_name = str(exchange_name).lower()
#    try:
#        if exchange_name == 'binance':
#            exchange_instance = await instance.get_binance_instance(user_id)
#        elif exchange_name == 'binance_spot':
#            exchange_instance = await instance.get_binance_spot_instance(user_id)
#            direction = 'long'
#        elif exchange_name == 'upbit':
#            exchange_instance = await instance.get_upbit_instance(user_id)
#            direction = 'long'
#        elif exchange_name == 'bitget':
#            exchange_instance = await instance.get_bitget_instance(user_id)
#        elif exchange_name == 'bitget_spot':
#            exchange_instance = await instance.get_bitget_spot_instance(user_id)
#            direction = 'long'
#        elif exchange_name == 'okx':
#            exchange_instance = await instance.get_okx_instance(user_id)
#        elif exchange_name == 'okx_spot':
#            exchange_instance = await instance.get_okx_spot_instance(user_id)
#        return exchange_instance
#    except Exception as e:
#        if "API" in e:
#            print("API key issue detected. Terminating process.")
#            from grid_process import stop_grid_main_process
#            
#            await stop_grid_main_process(exchange_name, user_id)
#            return
#        print(f"Error getting exchange instance for{user_id}13,  {exchange_name}: {e}")
#        return None
    #finally:
    #    if exchange_instance:
    #        await exchange_instance.close()
    #
def round_to_upbit_tick_size(amount):
    # 입력된 값이 문자열이고, 비어 있지 않은 경우 float로 변환
    if isinstance(amount, str) and amount.strip():
        try:
            amount = float(amount)
        except ValueError:
            # 변환 실패 시, 오류 메시지를 반환하거나 None을 반환할 수 있습니다.
            return None
    elif isinstance(amount, str):
        # 빈 문자열이거나 공백만 있는 경우
        return None

    # 이하 로직은 동일하게 유지
    if amount >= 1000:
        tick_size = Decimal('0.1')
    elif amount >= 100:
        tick_size = Decimal('0.01')
    elif amount >= 1:
        tick_size = Decimal('0.01')
    elif amount >= 0.01:
        tick_size = Decimal('0.0001')
    elif amount >= 0.0001:
        tick_size = Decimal('0.0001')
    else:
        tick_size = Decimal('0.0001')

    # Adjust the rounding to round half away from zero using Decimal
    amount_decimal = Decimal(str(amount))
    rounded_amount = amount_decimal.quantize(tick_size, rounding=ROUND_HALF_UP)

    return float(rounded_amount)


def get_order_price_unit_upbit(price):
    """
    Returns the order price unit based on the given price according to the provided criteria.

    :param price: The price for which the order price unit is to be determined.
    :return: The order price unit.
    """
    if price >= 2000000:
        return 2000
    elif 1000000 <= price < 2000000:
        return 1000
    elif 500000 <= price < 1000000:
        return 500
    elif 100000 <= price < 500000:
        return 100
    elif 10000 <= price < 100000:
        return 50
    elif 1000 <= price < 10000:
        return 10
    elif 100 <= price < 1000:
        return 1
    elif 10 <= price < 100:
        return 0.1
    elif 1 <= price < 10:
        return 0.01
    elif 0.1 <= price < 1:
        return 0.001
    elif 0.01 <= price < 0.1:
        return 0.0001
    elif 0.001 <= price < 0.01:
        return 0.00001
    elif 0.0001 <= price < 0.001:
        return 0.000001
    else:
        return 0.1
    
async def log_exception(e):
    print(f"An error occurred125: {e}")
    if hasattr(e, 'response') and e.response is not None:
        print(f"HTTP Status: {e.response.status}")
        try:
            print(f"Response Content: {await e.response.text()}")
        except Exception as resp_e:
            print(f"Failed to read response content: {resp_e}")

async def send_heartbeat(websocket, interval=30):
    while True:
        try:
            await websocket.ping()
            await asyncio.sleep(interval)
        except websockets.ConnectionClosed:
            break

async def ws_client(exchange_name, symbol, symbol_queue, user_id, max_retries=6):
    redis = await get_redis_connection()
    exchange = None
    try:
        exchange = await get_exchange_instance(exchange_name, user_id)
        retries = 0
        user_key = f'{exchange_name}:user:{user_id}'
        if exchange_name == 'okx':
            parts = symbol.replace('-SWAP', '').split('-')
            symbol = f"{parts[0]}/{parts[1]}:{parts[1]}"
        elif exchange_name == 'okx_spot':
            parts = symbol.split('-')
            symbol = f"{parts[0]}/{parts[1]}"
        last_check_time = 0
        check_interval = 7  # 5초마다 is_running 상태 확인
        print(f"Connecting to {exchange} websocket for {symbol}.")
        reconnected = False
        last_ping_time = time.time()
        ping_interval = 30  # 30초마다 핑 전송
        while True:
            current_time = time.time()
            if current_time - last_check_time > check_interval:
                is_running_value = await redis.hget(user_key, 'is_running')
                if isinstance(is_running_value, bytes):
                    is_running_str = is_running_value.decode('utf-8')
                else:
                    is_running_str = is_running_value
                is_running = bool(int(is_running_str or '0'))
                last_check_time = current_time
                #print(f"Debug: is_running for {user_id} is {is_running}") # 디버그 로그 추가
            if is_running and (retries < max_retries):
                try:
                    ticker = await exchange.watch_ticker(symbol)
                    if reconnected:
                        print(f"Successfully reconnected to {exchange} websocket for {symbol} after {retries} retries.")
                        reconnected = False
                    retries = 0  # 성공 시 재시도 카운트 리셋
                    last_price = ticker['last']
                    server_time = ticker.get('timestamp', None)
                    utc_time = datetime.fromtimestamp(server_time / 1000, timezone.utc)
                    kst_time = utc_time + timedelta(hours=9)  # UTC에서 KST (UTC+9)로 변환
                    await symbol_queue.put((last_price, kst_time))
                    await asyncio.sleep(random.random()+0.4)
                except Exception as e:
                    print(f"Error in ws_client for {symbol} on {exchange_name}: {str(e)}")
                    retries += 1
                    print(f"Attempting to reconnect... ({retries}/{max_retries})")
                    reconnected = True
                    await asyncio.sleep(min(2 * retries, 5))
            else:
                if retries >= max_retries:
                    print(f"Max retries reached for {symbol}. Stopping...")
                    break
                else:
                    print(f"Stopping websocket client for {symbol}... cause of is_running is {is_running}")
                    break
    except Exception as e:
        print(f"Unexpected error in ws_client for {symbol}: {str(e)}")
    
    ####TODO : 인스턴스 재활용에서는 필요없어서 확인.
    #finally:
    #    print(f"Stopping websocket client for {symbol}...")
    #    if exchange:
    #        await exchange.close()
        #ping_task.cancel()
    
##INDICATORS##






async def plot_trading_signals(df, coin_name):
    # 롱 진입 신호를 찾기
    df.columns = [col.lower() for col in df.columns]
    long_entry_signals = (df[[f'order_{n}' for n in range(1, 21)]] == True) & (df[[f'order_{n}' for n in range(1, 21)]].shift(1) == False)

    # 롱 종료 신호를 찾기
    long_exit_signals = (df[[f'order_{n}' for n in range(1, 21)]] == False) & (df[[f'order_{n}' for n in range(1, 21)]].shift(1) == True)

    # 캔들스틱 차트 생성
    fig = go.Figure(data=[go.Candlestick(x=df['timestamp'],
                                         open=df['open'],
                                         high=df['high'],
                                         low=df['low'],
                                         close=df['close'], name='OHLC')])
     #배경 추가 로직
    start = df['timestamp'].iloc[0]
    for i, row in df.iterrows():
        if i > 0:  # 첫 번째 행을 제외한 모든 행에 대해 실행
            if row['adx_state_4h'] == 2 and df.iloc[i - 1]['adx_state_4h'] != 2:
                # adx_state_4h가 2로 시작하는 지점 찾기
                start = row['timestamp']
            elif row['adx_state_4h'] != 2 and df.iloc[i - 1]['adx_state_4h'] == 2:
                # adx_state_4h가 2에서 다른 값으로 바뀌는 지점 찾기
                end = row['timestamp']
                fig.add_vrect(x0=start, x1=end, fillcolor="green", opacity=0.2, line_width=0)

            
            if row['adx_state_4h'] == -2 and df.iloc[i - 1]['adx_state_4h'] != -2:
                start = row['timestamp']
            elif row['adx_state_4h'] != -2 and df.iloc[i - 1]['adx_state_4h'] == -2:
                end = row['timestamp']
                fig.add_vrect(x0=start, x1=end, fillcolor="red", opacity=0.2, line_width=0)
    for n in range(1, 21):
        entry_x = df['timestamp'][long_entry_signals[f'order_{n}']]
        exit_x = df['timestamp'][long_exit_signals[f'order_{n}']]
        # 진입 시의 y값을 'low'로 설정
        entry_y = df['low'][long_entry_signals[f'order_{n}']]
        if n <= 18:
            exit_y = df['high'][long_exit_signals[f'order_{n}']]
        else:
            exit_y = None  # n이 19 또는 20인 경우, exit_y에 None 할당
        
        # 롱 진입 신호 추가
        fig.add_trace(go.Scatter(x=entry_x, y=entry_y,
                                 mode='markers', name=f'Long Entry {n}',
                                 marker=dict(color='green', size=8, symbol='triangle-up')))
        
        # 롱 종료 신호 추가 (종료 신호가 유효한 경우에만 추가)
        if exit_y is not None:
            fig.add_trace(go.Scatter(x=exit_x, y=exit_y,
                                     mode='markers', name=f'Long Exit {n}',
                                     marker=dict(color='red', size=8, symbol='triangle-down')))

    # grid_levels 추가
    for n in range(1, 21):
        fig.add_trace(go.Scatter(x=df['timestamp'], y=df[f'grid_level_{n}'], name=f'Grid Level {n}',
                                 line=dict(width=1, dash='dot')))
    fig.add_trace(go.Scatter(x=df['timestamp'], y=df['main_plot'], name='MAIN PLOT', line=dict(color='black')))

    # 차트 레이아웃 설정
    fig.update_layout(title=f'GRID Chart : {coin_name}', xaxis_title='Date', yaxis_title='Price', xaxis_rangeslider_visible=False, showlegend=False)
    # 차트 표시
    #await asyncio.to_thread(pio.write_image, fig, 'chart.png', width=1900, height=1080, scale=2)
    await asyncio.to_thread(pio.write_image, fig, f'{coin_name}_chart.png', width=1900, height=1080, scale=2)
    #fig.show()
    

async def get_min_notional(symbol, exchange_instance, redis = None, default_value=10):
    new_redis_flag = False
    if redis is None:
        redis = await get_redis_connection()
        new_redis_flag = True
    try:
        # Redis 키 생성
        redis_key = f"min_notional:{exchange_instance.id}:{symbol}"
        
        # Redis에서 데이터 확인
        cached_min_notional = await get_redis_data(redis, redis_key)
        if cached_min_notional is not None:
            return cached_min_notional

        # 캐시된 데이터가 없으면 기존 로직 실행
        try:
            markets = await exchange_instance.load_markets()
            market = None
            if exchange_instance.name.lower() == 'upbit':
                symbol_parts = symbol.split('-')
                converted_symbol = f"{symbol_parts[1]}/{symbol_parts[0]}"
                market = markets.get(converted_symbol, None)
            else:
                market = markets.get(symbol.replace("/", ""))
            
            if market is not None:
                if str(exchange_instance).lower() == 'upbit':
                    print(market['precision']['amount'])
                    min_notional = float(market['precision']['amount'])
                elif exchange_instance.id == 'bitget':
                    min_notional = float(market['limits']['amount']['min'] * market['limits']['price']['min'])
                elif exchange_instance.id == 'okx':
                    print(market)
                    min_notional = float(market['limits']['amount']['min'])
                else:  # 바이낸스 등 다른 거래소
                    min_notional = float(market['limits']['cost']['min'])
            else:
                min_notional = default_value
        except Exception as e:
            print(f"An error occurred1: {e}")
            min_notional = default_value

        # 결과를 Redis에 저장
        await set_redis_data(redis, redis_key, min_notional)
        return min_notional
    finally:
        if new_redis_flag:
            await redis.aclose

def get_upbit_precision(price):
    # 업비트 호가 구조에 맞춰 가격의 단위를 결정합니다.
    if price < 10:
        precision = 2  # 소수점 아래 2자리까지
    elif price < 100:
        precision = 1  # 소수점 아래 1자리까지
    elif price < 1000:
        precision = 0  # 소수점 없음
    elif price < 10000:
        precision = -1  # 5의 단위 (10^1)
    elif price < 50000:
        precision = -1  # 10의 단위 (10^1)
    elif price < 100000:
        precision = -2  # 50의 단위 (10^2)
    elif price < 500000:
        precision = -2  # 100의 단위 (10^2)
    elif price < 1000000:
        precision = -3  # 500의 단위 (10^3)
    else:
        precision = -3  # 1000의 단위 (10^3)

    return precision


def get_corrected_rounded_price(price):
    # 호가 구조에 맞춰 가격을 내림 처리합니다.
    if price < 1:
        unit = Decimal('0.001')
    elif price < 10:
        unit = Decimal('0.01')
    elif price < 100:
        unit = Decimal('0.1')
    elif price < 1000:
        unit = Decimal('1')
    elif price < 10000:
        unit = Decimal('5')
    elif price < 50000:
        unit = Decimal('10')
    elif price < 100000:
        unit = Decimal('50')
    elif price < 500000:
        unit = Decimal('100')
    elif price < 1000000:
        unit = Decimal('500')
    else:
        unit = Decimal('1000')

    # Decimal을 사용하여 내림 처리된 가격을 반환합니다.
    price = Decimal(str(round(price,5)))
    adjusted_price = price // unit * unit
    return float(adjusted_price)

async def calculate_order_quantity(symbol, initial_capital_list, current_price, redis = None):
    try:
        perpetual_instruments = await get_perpetual_instruments()
        lot_sizes = get_lot_sizes(perpetual_instruments)

        order_quantities = []
        if symbol in lot_sizes:
            lot_size, contract_value, base_currency = lot_sizes[symbol]
            for initial_capital in initial_capital_list:
                # 계약 수 계산
                order_quantity = initial_capital / (current_price * contract_value)
                order_quantities.append(order_quantity)
        else:
            order_quantities = [1.0] * len(initial_capital_list)
    except Exception as e:
        print(f"An error occurred6: {e}")
        order_quantities = [1.0] * len(initial_capital_list)
    return order_quantities


async def get_price_precision(symbol, exchange_instance,redis = None):
    new_redis_flag = False
    if redis is None:
        redis = await get_redis_connection()
    try:
        # Redis 키 생성
        redis_key = f"price_precision:{exchange_instance.id}:{symbol}"
        
        # Redis에서 데이터 확인
        cached_precision = await get_redis_data(redis, redis_key)
        if cached_precision is not None:
            return cached_precision

        # 캐시된 데이터가 없으면 기존 로직 실행
        markets = await exchange_instance.load_markets()
        market = None
        try:
            if str(exchange_instance).lower() == 'upbit':
                symbol_parts = symbol.split('-')
                converted_symbol = f"{symbol_parts[1]}/{symbol_parts[0]}"
                print(converted_symbol)
                market = markets.get(converted_symbol, None)
                precision = market['precision']['price']
                if precision < 1:
                    precision = -int(math.log10(precision))
                else:
                    precision = 0
            else:
                try:
                    market = exchange_instance.market(symbol)
                    if market is not None:
                        if exchange_instance.id == 'bitget':
                            print(market)
                            precision = int(market['info']['pricePrecision'])
                            if precision < 1:
                                precision = -int(math.log10(precision))
                            else:
                                precision = 0
                        else:  # 바이낸스 등 다른 거래소
                            precision = market['precision']['price']
                            if precision is not None and (precision >= 1):
                                precision = int(precision)
                            elif precision is not None and (precision < 1):
                                precision = -int(math.log10(precision))
                            else:
                                print('precision: is none')
                                precision = 0
                    else:
                        precision = 0
                except Exception as e:
                    print(f"An error occurred7: {e}")
                    precision = 0
        except Exception as e:
            print(f"An error occurred8: {e}")
            precision = 0

        # 결과를 Redis에 저장
        await set_redis_data(redis, redis_key, precision)
        return precision
    finally:
        if new_redis_flag:
            await redis.aclose()

# 가격 정밀도 조정 함수
def adjust_price_precision(price, precision):
    precision = int(precision)
    #if precision > 6:
    #    print(f"precision : {precision}, price : {price}.")
    if precision is None:
        return price  # precision이 None이면 원래 가격을 그대로 반환
    try:
        return round(price, int(precision))
    except (ValueError, TypeError):
        print(f"Invalid precision value: {precision}. Using original price.({price})")
        return price

#================================================================================================
# FETCH PRICE
#================================================================================================




#================================================================================================
# BALANCE
#================================================================================================

def process_okx_position_data(positions_data, symbol):
    # Redis에서 가져온 데이터 처리
    if isinstance(positions_data, list):
        for position in positions_data:
            if position.get('instId') == symbol:
                quantity = float(position.get('pos', '0'))
                #print(f"{symbol}의 position : {quantity} Quantity type : {type(quantity)}")
                return quantity
    
    # 웹소켓에서 받은 데이터 처리
    elif isinstance(positions_data, dict) and 'data' in positions_data:
        for position in positions_data['data']:
            if position.get('instId') == symbol:
                quantity = float(position.get('pos', '0'))
                #print(f"{symbol}의 position : {quantity} Quantity type : {type(quantity)}")
                return quantity
    
    # 예상치 못한 데이터 구조
    else:
        print(f"Unexpected data structure: {type(positions_data)}")
        print(f"Data: {positions_data}")
    
    return 0.0

def process_upbit_balance(balance, symbol):
    base_currency = symbol.split('-')[1]  # 'KRW-ETC'에서 'ETC'를 추출
    free_balance = balance['free'].get(base_currency, 0.0)  # 사용 가능 잔고 추출
    print(f'{symbol}의 balance: {free_balance}')
    return free_balance

async def handle_upbit(exchange, symbol, user_id, redis, cache_key):
    max_retries = 3
    retry_delay = 2  # seconds

    try:
        # Try to get cached balance data
        cached_data = await redis.get(cache_key)
        if cached_data:
            balance = json.loads(cached_data)
            print("Using cached balance data for Upbit")
            return process_upbit_balance(balance, symbol)

        # If no valid cache, proceed with API call
        for attempt in range(max_retries):
            try:
                await asyncio.sleep(random.random())
                balance = await exchange.fetch_balance()
                
                # Cache the balance data with TTL
                await redis.set(cache_key, json.dumps(balance), ex=300)  # 300 seconds = 5 minutes
                
                return process_upbit_balance(balance, symbol)
            except Exception as e:
                print(f"An error occurred in handle_upbit: {e}")
                print(traceback.format_exc())
                if 'too many requests' in str(e).lower() and attempt < max_retries - 1:
                    print(f"Retrying in {retry_delay} seconds...")
                    await asyncio.sleep(retry_delay)
                else:
                    return 0.0

    except Exception as e:
        print(f"Unexpected error in handle_upbit: {e}")
        print(traceback.format_exc())
        return 0.0

#async def handle_okx(exchange, symbol, user_id, redis, cache_key):
#    market_type = exchange.options.get('defaultType', 'No market type set')
#    quantity = 0.0
#    max_retries = 3
#    retry_delay = 2  # seconds
#
#    try:
#        # Try to get cached position data
#        await asyncio.sleep(random.random())
#        cached_data = await redis.get(cache_key)
#        if cached_data:
#            positions_data = json.loads(cached_data)
#            print("Using cached position data for OKX")
#            return process_okx_position_data(positions_data, symbol)
#        # If no valid cache, proceed with API call
#        for attempt in range(max_retries):
#            try:
#                if market_type == 'spot':
#                    await asyncio.sleep(random.random())
#                    balance_data = await exchange.fetch_balance()
#                    base_currency = symbol.split('-')[0]
#                    if base_currency in balance_data:
#                        quantity = float(balance_data[base_currency]['free'])
#                        print(f"{symbol}의 type : {type(quantity)}, {symbol}position value : {quantity}")
#                else:
#                    positions_data = await exchange.private_get_account_positions()
#                    
#                    # Cache the position data with TTL
#                    await redis.set(cache_key, json.dumps(positions_data), ex=300)  # 300 seconds = 5 minutes
#                    
#                    quantity = process_okx_position_data(positions_data, symbol)
#                    await asyncio.sleep(random.random()+0.4)
#                
#                break  # Exit the loop if no exception occurs
#            except Exception as e:
#                print(f"An error occurred in handle_okx: {e}")
#                print(traceback.format_exc())
#                if 'too many requests' in str(e).lower() and attempt < max_retries - 1:
#                    print(f"Retrying in {retry_delay} seconds...")
#                    await asyncio.sleep(retry_delay)
#                else:
#                    return 0.0
#
#    except Exception as e:
#        print(f"Unexpected error in handle_okx: {e}")
#        print(traceback.format_exc())
#        return 0.0
#    return quantity

def ensure_symbol_initialized_old_struc(user_id, symbol, grid_num):
    global user_keys
    if symbol not in user_keys[user_id]["symbols"]:
        user_keys[user_id]["symbols"][symbol] = {
            "take_profit_orders_info": {n: {"order_id": None, "quantity": 0.0, "target_price": 0.0, "active": False, "side": None} for n in range(1, grid_num + 1)},
            "last_entry_time": None,  
            "last_entry_size": 0.0,
            "previous_new_position_size": 0.0,
            "order_placed": {n: False for n in range(1, grid_num + 1)},
            "last_placed_prices": {n: 0.0 for n in range(0, grid_num + 1)},
            "initial_balance_of_symbol": 0.0,
            "order_ids": {n: None for n in range(1, grid_num + 1)},
            "level_quantities": {n: 0.0 for n in range(1, grid_num + 1)},
            
        }
        


async def handle_okx(exchange, symbol, user_id, redis, cache_key):
    market_type = exchange.options.get('defaultType', 'No market type set')
    quantity = 0.0
    max_retries = 3
    retry_delay = 2  # seconds
    user_key = f'okx:user:{user_id}'
    user_data = await redis.hgetall(user_key)

    # WebSocket connection details
    uri = "wss://ws.okx.com:8443/ws/v5/private"
    API_KEY = OKX_API_KEY
    SECRET_KEY = OKX_SECRET_KEY
    PASSPHRASE = OKX_PASSPHRASE

    async def get_position_from_websocket():
        async with websockets.connect(uri) as websocket:
            # Perform authentication
            timestamp = str(int(time.time()))
            message = timestamp + 'GET' + '/users/self/verify'
            signature = base64.b64encode(hmac.new(SECRET_KEY.encode('utf-8'), message.encode('utf-8'), hashlib.sha256).digest()).decode('utf-8')
            
            login_data = {
                "op": "login",
                "args": [{
                    "apiKey": API_KEY,
                    "passphrase": PASSPHRASE,
                    "timestamp": timestamp,
                    "sign": signature
                }]
            }
            await websocket.send(json.dumps(login_data))
            
            # Subscribe to position channel
            subscribe_data = {
                "op": "subscribe",
                "args": [{
                    "channel": "positions",
                    "instType": "SWAP"
                }]
            }
            await websocket.send(json.dumps(subscribe_data))
            
            while True:
                response = await websocket.recv()
                data = json.loads(response)
                
                if 'data' in data:
                    positions_data = data['data']
                    quantity = process_okx_position_data(positions_data, symbol)
                    if quantity != 0.0:
                        await redis.set(cache_key, json.dumps(positions_data), ex=300)
                        return quantity
    
    try:
        # Try to get cached position data
        await asyncio.sleep(random.random())
        cached_data = await redis.get(cache_key)
        if cached_data:
            positions_data = json.loads(cached_data)
            print("Using cached position data for OKX")
            return process_okx_position_data(positions_data, symbol)

        # If no valid cache, try WebSocket
        try:
            quantity = await asyncio.wait_for(get_position_from_websocket(), timeout=10.0)
            if quantity != 0.0:
                return quantity
        except asyncio.TimeoutError:
            print("WebSocket connection timed out, falling back to API")

        # If WebSocket fails or returns 0, proceed with API call
        for attempt in range(max_retries):
            try:
                if market_type == 'spot':
                    await asyncio.sleep(random.random())
                    balance_data = await exchange.fetch_balance()
                    base_currency = symbol.split('-')[0]
                    if base_currency in balance_data:
                        quantity = float(balance_data[base_currency]['free'])
                        print(f"{symbol}의 type : {type(quantity)}, {symbol}position value : {quantity}")
                else:
                    positions_data = await exchange.private_get_account_positions()
                    # Cache the position data with TTL
                    await redis.set(cache_key, json.dumps(positions_data), ex=300)  # 300 seconds = 5 minutes
                    quantity = process_okx_position_data(positions_data, symbol)
                await asyncio.sleep(random.random()+0.4)
                break  # Exit the loop if no exception occurs
            except Exception as e:
                print(f"An error occurred in handle_okx: {e}")
                print(traceback.format_exc())
                if 'too many requests' in str(e).lower() and attempt < max_retries - 1:
                    print(f"Retrying in {retry_delay} seconds...")
                    await asyncio.sleep(retry_delay)
                else:
                    return 0.0
    
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        print(traceback.format_exc())
        return 0.0

    return quantity


def process_other_exchange_position(positions, symbol):
    if positions and len(positions) > 0:
        position = positions[0]  # 첫 번째 포지션 정보 사용
        quantity = float(position['info']['positionAmt'])  # 포지션 양 추출
        print(f"{symbol}의 position : {quantity}")
        return quantity
    else:
        print(f"포지션 없음: {symbol}")
        return 0.0

            
async def handle_other_exchanges(exchange, symbol, user_id, redis, cache_key):
    max_retries = 3
    retry_delay = 2  # seconds

    try:
        # Try to get cached position data
        cached_data = await redis.get(cache_key)
        if cached_data:
            positions = json.loads(cached_data)
            print("Using cached position data for other exchanges")
            return process_other_exchange_position(positions, symbol)

        # If no valid cache, proceed with API call
        for attempt in range(max_retries):
            try:
                positions = await exchange.fetch_positions([symbol])
                
                # Cache the position data with TTL
                await redis.set(cache_key, json.dumps(positions), ex=300)  # 300 seconds = 5 minutes
                
                return process_other_exchange_position(positions, symbol)
            except Exception as e:
                print(f"An error occurred in handle_other_exchanges: {e}")
                print(traceback.format_exc())
                if 'too many requests' in str(e).lower() and attempt < max_retries - 1:
                    print(f"Retrying in {retry_delay} seconds...")
                    await asyncio.sleep(retry_delay)
                else:
                    return 0.0

    except Exception as e:
        print(f"Unexpected error in handle_other_exchanges: {e}")
        print(traceback.format_exc())
        return 0.0
    
    


async def get_balance_of_symbol(exchange, symbol, user_id):
    redis = await get_redis_connection()
    try:
        if exchange.id.lower() == 'upbit':
            cache_key = f"upbit:balance:{user_id}:{symbol}"
            return await handle_upbit(exchange, symbol, user_id, redis, cache_key)
        elif exchange.id.lower() == 'okx':
            cache_key = f"okx:positions:{user_id}"
            return await handle_okx(exchange, symbol, user_id, redis, cache_key)
        else:
            cache_key = f"{exchange.id.lower()}:positions:{user_id}:{symbol}"
            return await handle_other_exchanges(exchange, symbol, user_id, redis, cache_key)
    except Exception as e:
        print(f"An error occurred9: {e}")
        return 0.0
#================================================================================================
# ORDERS
#================================================================================================
async def get_placed_prices(exchange_name: str, user_id: int, symbol_name: str) -> List[float]:
    key = f"orders:{exchange_name}:user:{user_id}:symbol:{symbol_name}:orders"
    cached_data = await redis_client.get(key)
    if cached_data:
        try:
            data = json.loads(cached_data)
            return [float(price) for price in data if price is not None]  # None 값 필터링 및 float 변환
        except (json.JSONDecodeError, ValueError) as e:
            logging.error(f"Error decoding cached data: {e}")
            return []
    return []

async def add_placed_price(exchange_name: str, user_id: int, symbol_name: str, price: float) -> None:
    key = f"orders:{exchange_name}:user:{user_id}:symbol:{symbol_name}:orders"
    prices = await  get_placed_prices(exchange_name, user_id, symbol_name)
    if price not in prices:
        prices.append(price)
        #print(prices)
        await redis_client.setex(key, 45, json.dumps(prices))  # 30초 동안 캐시 유지
        #print(f"Added price {price} to {key}")
        
async def is_order_placed(exchange_name: str, user_id: int, symbol_name: str, grid_level: int) -> bool:
    key = f'orders:{exchange_name}:user:{user_id}:symbol:{symbol_name}:order_placed_index'
    
    cached_data = parse_bool(await redis_client.hget(key, str(grid_level)))
    if cached_data == True :
        #print(f"Order already placed for {symbol_name} at grid level {grid_level}")
        await asyncio.sleep(0.1)
        True
    return False

async def is_price_placed(exchange_name: str, user_id: int, symbol_name: str, price: float, grid_level: int = None, grid_num : int = 20) -> bool:
    prices = await get_placed_prices(exchange_name, user_id, symbol_name)
    logging.debug(f"Received prices: {prices}")
    try:
        placed = any(abs(float(p) - price) / price < 0.0003 for p in prices)  # 명시적 float 변환
        if placed is True:
            logging.info(f"{user_id} : Price {price} already placed for {symbol_name} on {grid_level}")
            await asyncio.sleep(0.3)
            return True
        if grid_level is not None:
            placed_index = await get_order_placed(exchange_name, user_id, symbol_name, grid_num)
            #print(f"{user_id} | {symbol_name} : {grid_level} 의 order_placed = {placed_index[grid_level]}")
            if placed_index[grid_level] == True:
                logging.info(f"🍋{user_id} : Price {price} already placed for {symbol_name} on {grid_level}")
                await asyncio.sleep(0.3)
                return True
        return False
    except (ValueError, TypeError) as e:
        logging.error(f"Error in price comparison: {e}")
        return False

async def set_order_placed(exchange_name, user_id, symbol, grid_level, level_index = None):
    #start_time = time.time()
    redis = await get_redis_connection()
    order_placed_key = f'orders:{exchange_name}:user:{user_id}:symbol:{symbol}:order_placed'
    if level_index is not None :
        order_placed_index = f'orders:{exchange_name}:user:{user_id}:symbol:{symbol}:order_placed_index'
        await redis.hset(order_placed_index, str(level_index), str("true").lower())
        stored_level_index = parse_bool(await redis.hget(order_placed_index, str(level_index)))
        #print(f"🍋{user_id} | {symbol} : {level_index} 의 order_placed = is true ? ->  {stored_level_index}")
        await redis.expire(order_placed_index, 120) 
    await redis.hset(order_placed_key, str(grid_level), str("true").lower())
    #await redis.hset(order_placed_index, str(grid_level), str("true").lower())
    stored_value = parse_bool(await redis.hget(order_placed_key, str(grid_level)))
    #    await redis.hset(order_placed_key_og, str(grid_level), str("true").lower())
    await redis.expire(order_placed_key, 120)  # 만료 시간 갱신
    end_time = time.time()
    #print(f"{user_id} | {symbol} : {grid_level} 의 order_placed = is true ? ->  {stored_value}")
    
    #print(f"elapsed_time : {elapsed_time}")
    
async def get_order_placed(exchange_name, user_id, symbol, grid_num):
    redis = await get_redis_connection()
    order_placed_key = f'orders:{exchange_name}:user:{user_id}:symbol:{symbol}:order_placed_index'
    
    # Redis에서 해시 전체를 가져옵니다
    order_placed_data = await redis.hgetall(order_placed_key)
    #if order_placed_data is not None:
    #    print(f"{symbol}의 Raw Redis data: {order_placed_data}")  # 디버깅 출력
    
    # 결과를 적절한 형식으로 변환합니다
    order_placed = {}
    for n in range(0, grid_num + 1):
        value = order_placed_data.get(str(n), '') or order_placed_data.get(str(float(n)), '')
        order_placed[n] = value.lower() == 'true'
        #if order_placed[n] == True:
        #    print(f"Grid {n}: Redis value = '{value}', Parsed = {order_placed[n]}")  # 디버깅 출력
    
    return order_placed

async def reset_order_placed(exchange_name, user_id, symbol, grid_num):
    redis = await get_redis_connection()
    order_placed_key = f'orders:{exchange_name}:user:{user_id}:symbol:{symbol}:order_placed'
    order_placed_index = f'orders:{exchange_name}:user:{user_id}:symbol:{symbol}:order_placed_index'

    # Reset order_placed
    for level in range(grid_num):
        await redis.hset(order_placed_key, str(level), str(False).lower())
    
    # Reset order_placed_index
    await redis.delete(order_placed_index)

    # Set expiration time
    await redis.expire(order_placed_key, 600)

    print(f"🔄 Reset order_placed for {user_id} | {symbol}")

    # Optionally, verify the reset
    for level in range(grid_num):
        stored_value = parse_bool(await redis.hget(order_placed_key, str(level)))
        #print(f"✅ {user_id} | {symbol} : Level {level} order_placed = {stored_value}")

    return True

async def get_all_positions(exchange_name, user_id):
    redis = await get_redis_connection()
    position_key = f'{exchange_name}:positions:{user_id}'
    position_data = await redis.get(position_key)
    
    if position_data is None:
        return {}  # 포지션 정보가 없으면 빈 딕셔너리 반환
    
    try:
        positions = json.loads(position_data)
        result = {}
        excluded_symbols = ['BTC-USDT-SWAP', 'ETH-USDT-SWAP', 'SOL-USDT-SWAP']
        
        if isinstance(positions, list):
            for position in positions:
                if isinstance(position, dict):
                    symbol = position.get('instId')
                    pos = float(position.get('pos', 0))
                    notional_usd = float(position.get('notionalUsd', 0))
                    if pos != 0 and notional_usd < 10000 and symbol not in excluded_symbols:
                        result[symbol] = pos
        elif isinstance(positions, dict):
            for symbol, position in positions.items():
                if isinstance(position, dict):
                    pos = float(position.get('pos', 0))
                    notional_usd = float(position.get('notionalUsd', 0))
                    if pos != 0 and notional_usd < 10000 and symbol not in excluded_symbols:
                        result[symbol] = pos
        
        return result  # 0이 아닌 포지션만 포함된 딕셔너리 반환
    
    except (json.JSONDecodeError, ValueError, AttributeError) as e:
        print(f"Error processing position data: {e}")
        return {}  # 데이터 파싱 오류 시 빈 딕셔너리 반환

async def get_position_size(exchange_name, user_id, symbol):
    redis = await get_redis_connection()
    
    # 포지션 정보 확인
    position_key = f'{exchange_name}:positions:{user_id}'
    position_data = await redis.get(position_key)
    
    if position_data is None:
        return 0.0  # 포지션 정보가 없으면 0 반환
    
    try:
        positions = json.loads(position_data)
        if isinstance(positions, list):
            for position in positions:
                if isinstance(position, dict) and position.get('instId') == symbol:
                    return float(position.get('pos', 0))
        elif isinstance(positions, dict):
            position = positions.get(symbol)
            if position:
                return float(position.get('pos', 0))
        return 0.0  # 해당 심볼에 대한 포지션이 없으면 0 반환
    except (json.JSONDecodeError, ValueError, AttributeError) as e:
        print(f"Error processing position data: {e}")
        return 0.0  # 데이터 파싱 오류 시 0 반환


async def check_existing_order_at_price(
    redis: Any,
    exchange_name: str,
    user_id: str,
    symbol: str,
    price: Decimal,
    side: Optional[str] = None,
    tolerance: Decimal = Decimal('0.0001')
) -> List[Dict[str, Any]]:
    """
    Check if there's an existing order at the given price for a specific symbol.
    
    :param redis: Redis connection
    :param exchange_name: Name of the exchange
    :param user_id: User ID
    :param symbol: Trading symbol (e.g., 'BTC/USDT')
    :param price: Price to check
    :param side: Optional. 'buy' or 'sell'. If not provided, checks both sides.
    :param tolerance: Price tolerance for matching (default is 0.01%)
    :return: List of matching orders
    """
    redis_key = f"{exchange_name}:user:{user_id}:{symbol}"
    matching_orders = []

    try:
        # Fetch all orders for the symbol
        all_orders = await redis.hgetall(redis_key)
        
        for order_id, order_json in all_orders.items():
            order = json.loads(order_json)
            order_price = Decimal(str(order['price']))
            order_side = order['side'].lower()

            # Check if the order price is within the tolerance of the given price
            price_diff = abs(order_price - price) / price
            if price_diff <= tolerance:
                # If side is specified, check if it matches
                if side is None or order_side == side.lower():
                    matching_orders.append(order)

        return matching_orders

    except Exception as e:
        print(f"Error checking existing orders: {e}")
        return []


async def okay_to_place_order(exchange_name, user_id, symbol, check_price, max_notional_value, order_direction):
    redis = await get_redis_connection()
    
    # 기존 주문 확인 로직
    order_placed_key = f'orders:{exchange_name}:user:{user_id}:symbol:{symbol}:order_placed'
    all_prices = await redis.hgetall(order_placed_key)
    for stored_price, value in all_prices.items():
        stored_price = float(stored_price)
        if abs(stored_price - check_price) / stored_price <= 0.001:
            return False # 이미 해당 가격에 주문이 있음 <-- 이게 맞을텐데, 왜 원래는 주문가능으로 되어있었지??? True/False를 거꾸로 바꾸면서 생긴 문제인가? 그래서 10 08 기준 일단 False로 다시 바꿔놓음
            ###return True  # 주문 가능 
    
    # 포지션 정보 확인
    position_key = f'{exchange_name}:positions:{user_id}'
    position_data = await redis.get(position_key)
    
    if position_data is None:
        return True  # 포지션 정보가 없으므로, 주문 가능 
    
    try:
        positions = json.loads(position_data)
        if isinstance(positions, list):
            for position in positions:
                if isinstance(position, dict) and position.get('instId') == symbol:
                    notional_usd = float(position.get('notionalUsd', 0))
                    pos = float(position.get('pos', 0))
                    able_to_order = check_order_validity(notional_usd, pos, max_notional_value, order_direction)
                    #print(f"unable_to_order : {unalbe_to_order}")
                    return able_to_order
        elif isinstance(positions, dict):
            position = positions.get(symbol)
            if position:
                notional_usd = float(position.get('notionalUsd', 0))
                pos = float(position.get('pos', 0))
                able_to_order = check_order_validity(notional_usd, pos, max_notional_value, order_direction)
                #print(f"unable_to_order : {unalbe_to_order}")
                return able_to_order
        return True  # 주문 가능 (해당 심볼에 대한 포지션이 없음)
    except (json.JSONDecodeError, ValueError, AttributeError) as e:
        print(f"Error processing position data: {e}")
        return True  # 데이터 파싱 오류 시 주문 허용
    
    
def check_order_validity(notional_usd, pos, max_notional_value, order_direction):
    #print(f"max_notional_value : {max_notional_value}, notional_usd : {notional_usd}")
    if pos > 0:  # 현재 롱 포지션
        if order_direction == 'long' and notional_usd >= max_notional_value:
            return False  # 주문 불가 (이미 최대 notional 값에 도달)
        elif order_direction == 'short':
            return True  # 주문 가능 (반대 방향으로 주문)
    elif pos < 0:  # 현재 숏 포지션
        if order_direction == 'short' and abs(notional_usd) >= max_notional_value:
            return False  # 주문 불가 (이미 최대 notional 값에 도달)
        elif order_direction == 'long':
            return True  # 주문 가능 (반대 방향으로 주문)
    else:  # pos == 0, 현재 포지션 없음
        return True  # 주문 가능
    
    return True  # 기본적으로 주문 가능

#================================================================================================
# CREATE SHORT ORDER
#================================================================================================

async def create_short_order(exchange_instance, exchange_name, symbol, amount, price, **kwargs):
    order_params = {
        'symbol': symbol,
        'type': 'limit',
        'side': 'sell',
        'amount': amount,
        'price': price
    }

    if exchange_name in ['binance', 'binance_spot', 'okx_spot']:
        return await exchange_instance.create_order(**order_params)
    
    elif exchange_name == 'okx':
        if kwargs.get('direction') == 'long':
            order_params['params'] = {'reduceOnly': True}
        return await exchange_instance.create_order(**order_params)
    
    elif exchange_name == 'bitget':
        order_params['symbol'] = kwargs.get('symbol_name', symbol)  # bitget uses symbol_name
        order_params['params'] = {
            'contract_type': 'swap',
            'position_mode': 'single',
            'marginCoin': 'USDT',
        }
        return await exchange_instance.create_order(**order_params)
    
    elif exchange_name == 'bitget_spot':
        order_params['symbol'] = kwargs.get('symbol_name', symbol)  # bitget uses symbol_name
        return await exchange_instance.create_order(**order_params)
    
    else:
        raise ValueError(f"Unsupported exchange: {exchange_name}")

async def get_take_profit_orders_info(redis, exchange_name ,user_id, symbol_name, grid_num, force_restart=False):
    symbol_key = f"{exchange_name}:user:{user_id}:symbol:{symbol_name}"
    
    # Redis에서 기존 정보 불러오기
    stored_info = await redis.hget(symbol_key, 'take_profit_orders_info')
    if stored_info :
        take_profit_orders_info = json.loads(stored_info)
        #print(f"Loaded take_profit_orders_info for{symbol_name}: {take_profit_orders_info}")
    else:
        # 저장된 정보가 없으면 새로 생성
        take_profit_orders_info = {
            str(n): {
                "order_id": None,
                "quantity": 0.0,
                "target_price": 0.0,
                "active": False,
                "side": None
            } for n in range(0, grid_num + 1)
        }
    
    # 변경된 정보를 Redis에 저장
    await redis.hset(symbol_key, 'take_profit_orders_info', json.dumps(take_profit_orders_info))
    
    return take_profit_orders_info
    
async def place_grid_orders(symbol, initial_investment, direction, grid_levels, symbol_queue, grid_num,leverage, exchange_name, user_id, force_restart = False):
    global user_keys    
    max_retries = 3
    retry_delay = 5  # seconds
    circulation_count = 0
    print("place grid order로직에 들어감. ", symbol)

    try:
        for attempt in range(max_retries):
            try:
                order_placed = {}
                adx_4h = 0
                redis = await get_redis_connection()
                user_key = f'{exchange_name}:user:{user_id}'
                symbol_key = f'{user_key}:symbol:{symbol}'
                max_notional_value = initial_investment[1]*20
                user_data = await redis.hgetall(user_key)
                symbol_data = await redis.hgetall(symbol_key)
                numbers_to_entry = int(user_data.get(b'numbers_to_entry', b'5').decode())
                position_size = 0.0
                running_symbols = set(json.loads(user_data.get('running_symbols', '[]')))
                completed_symbols = set(json.loads(user_data.get('completed_trading_symbols', '[]')))
                #print(f"Debug: Before update - running_symbols = {running_symbols}")  # 디버그 출력
                await ensure_symbol_initialized(exchange_name, user_id, symbol, grid_num)
                ensure_symbol_initialized_old_struc(user_id, symbol, grid_num)
                await initialize_active_grid(redis, exchange_name, user_id, symbol)
                order_buffer = float((numbers_to_entry / 25))
                temporally_waiting_long_order = False
                temporally_waiting_short_order = False
                symbol_name = symbol
                short_order = None
                price_precision = 0.0
                min_notional = 0.0
                if symbol not in running_symbols:
                    running_symbols.add(symbol)
                    print(f"Debug: Symbol {symbol} added to running_symbols")  # 디버그 출력
                print(f"Debug: After update - running_symbols = {running_symbols}")  # 디버그 출력
                running_symbol = symbol in running_symbols
                await redis.hset(user_key, 'running_symbols', json.dumps(list(running_symbols)))
                print(f"{user_id} : {symbol} Debug: running_symbol = {running_symbol}")  # 디버그 출력
                print(running_symbol)
                long_order = None
                exchange_instance = None
                possible_order_id_keys = ['order_id', 'uuid', 'orderId', 'ordId']
                trading_message = (f"== Grid Trading Strategy Start == \n 심볼 : {symbol_name} 거래소 : {exchange_name}")
                print(trading_message)
                order_id = None
                await add_user_log(user_id, trading_message)
                ws_data = await symbol_queue.get()
                current_price, server_time = ws_data
                current_price = float(current_price)
                over_20_grid = False
                under_1_grid = False
                message_only_at_time = False
                minimum_volatility = True
                message_time_count = 0
                last_execution_time = 0
                order_quantity = initial_investment[0]
                order_quantities = initial_investment
            except Exception as e:
                print(f"An error occurred10000: {e}")
                print(traceback.format_exc())
            try:
                if exchange_name == 'binance':
                    exchange_instance = await instance.get_binance_instance(user_id)
                elif exchange_name == 'binance_spot':
                    exchange_instance = await instance.get_binance_spot_instance(user_id)
                elif exchange_name == 'upbit':
                    exchange_instance = await instance.get_upbit_instance(user_id)
                    direction = 'long'
                elif exchange_name == 'bitget':
                    exchange_instance = await instance.get_bitget_instance(user_id)
                    symbol_name = symbol.replace('USDT', '') + '/USDT:USDT'
                elif exchange_name == 'bitget_spot':
                    exchange_instance = await instance.get_bitget_spot_instance(user_id)
                    symbol_name = symbol.replace('USDT', '') + '/USDT:USDT'
                elif exchange_name == 'okx':
                    #print(f"exchange_name check! : {exchange_name}")
                    try:
                        exchange_instance = await instance.get_okx_instance(user_id)
                        order_quantities = await retry_async(calculate_order_quantity, symbol, initial_investment, current_price, redis)
                        try:
                            await redis.hset(symbol_key, 'order_quantities', json.dumps(order_quantities))
                        except Exception as e:
                            error = str(e)
                            print(f"An error on making redis list: {error}")
                    except Exception as e:
                        print(f"An error occurred17!: {e}")
                        raise "remove"
                elif exchange_name == 'okx_spot':
                    try:
                        exchange_instance = await instance.get_okx_spot_instance(user_id)
                    except Exception as e:
                        print(f"An error occurred16: {e}")
                        raise e
                try:
                    price_precision = await retry_async(get_price_precision, symbol, exchange_instance, redis)
                    min_notional = await retry_async(get_min_notional, symbol_name, exchange_instance, redis)
                except Exception as e:
                    print(f"An error occurred18: {e}")
                    price_precision = 0.0
                    min_notional = 10.0
                try:
                    spot_exchange = False
                    if exchange_name == 'upbit' or exchange_name == 'binance_spot' or exchange_name == 'bitget_spot' or exchange_name == 'okx_spot':
                        spot_exchange = True
                    else:
                        spot_exchange = False
                    grid_level = None
                    upper_levels = []
                    lower_levels = []
                    pnl_percent = 0.0
                    temporally_waiting_long_order = False
                    temporally_waiting_short_order = False
                    current_pnl = 0.0
                    try:
                        order_placed = await get_order_placed(exchange_name, user_id, symbol_name, grid_num)
                        #order_placed = user_keys.get(user_id, {}).get("symbol", {}).get(symbol_name, {}).get("order_placed", {n: False for n in range(0, grid_num + 1)})
                    except Exception as e:
                        print(f"An error occurred1001: {e}")
                        order_placed = {n: False for n in range(0, grid_num + 1)}
                    try:
                        order_ids_key = f'{exchange_name}:user:{user_id}:symbol:{symbol_name}:order_ids'
                        stored_data = await redis_client.hgetall(order_ids_key)
                        if stored_data:
                            
                            order_ids = {k: decode_value(v) for k, v in stored_data.items()}
                        else:
                            order_ids = {str(n): None for n in range(0, grid_num + 1)}
                    except Exception as e:
                        print(f"An error occurred1002: {e}")
                        order_ids = {str(n): None for n in range(0, grid_num + 1)}
                    level_quantities = user_keys[user_id]["symbols"][symbol_name]["level_quantities"]
                    initial_balance_of_symbol = await retry_async(get_balance_of_symbol,exchange_instance, symbol_name, user_id)
                    last_position_size = 0.0
                    new_position_size = 0.0
                    take_profit_orders_info = await get_take_profit_orders_info(redis, exchange_name, user_id, symbol_name, grid_num, force_restart)
                    quantity_list = []
                    update_flag = True
                    overbought = False
                    oversold = False
                    last_execution_time = 0  # 마지막 실행 시간을 저장할 변수 추가
                    adx_4h = 0
                    try:
                        if not grid_levels.empty and 'adx_state_4h' in grid_levels.columns:
                            adx_4h_series = grid_levels.get('adx_state_4h', pd.DataFrame())
                            adx_4h = adx_4h_series.iloc[-1] if not adx_4h_series.empty else 0
                    except Exception as e:
                        adx_4h = 0
                    is_running = await redis.hset(user_key, 'is_running', '1')
                    #running = user_data.get(b'is_running', b'0').decode() == '1'
                    print(f"Trading started for user {user_id} : {symbol} on {exchange_name}")
                    try:
                        sum_of_initial_capital = sum(initial_investment)
                        max_notional_value = sum_of_initial_capital * 1.05
                    except Exception as e:
                        print(f"An error occurred11: {e}")
                        initial_investment_str = await redis.hget(user_key, 'initial_capital')
                        initial_investment = json.loads(initial_investment_str)
                        sum_of_initial_capital = sum(initial_investment)
                        max_notional_value = sum_of_initial_capital * 1.05 
                    for i in range(grid_num):
                        initial_capital = initial_investment[i]
                        order_quantity = order_quantities[i]
                    active_grid = await redis_database.get_active_grid(redis, exchange_name, user_id, symbol_name)
                    if 'grid_level_20' in grid_levels:
                        grid_levels['grid_level_21'] = grid_levels['grid_level_20'] * (1 + 0.008)
                    if grid_num > 20:
                        for i in range(21, grid_num + 1):
                            grid_levels[f'grid_level_{i}'] = grid_levels['grid_level_20'] * (1 + 0.008 * (i - 20))
                    
                    if 'grid_level_1' in grid_levels:
                        grid_levels['grid_level_0'] = grid_levels['grid_level_1'] * (1 - 0.008)
                    else:
                        await redis_database.remove_running_symbol(user_id, symbol, exchange_name, redis)
                        return False
                except Exception as e:
                    print(f"An error occurred1001: {e}")
                    print(traceback.format_exc())
                running_symbol = symbol in running_symbols

                print(f"running symbol : {running_symbol}")
                print(running_symbols)
                break

            except Exception as e:
                print(f"An error occurred (attempt {attempt + 1}/{max_retries}): {e}")
                print(traceback.format_exc())
                
                if attempt < max_retries - 1:
                    wait_time = retry_delay + random.uniform(0, 2)  # Add some randomness to avoid thundering herd
                    print(f"Retrying in {wait_time:.2f} seconds...")
                    await asyncio.sleep(wait_time)
                else:
                    print("Max retries reached. Failing...")
                    await redis_database.remove_running_symbol(user_id, symbol, exchange_name, redis)
                    return False
        while True:
            try:
                await asyncio.sleep(0.1)
                #is_running = await redis.hget(user_key, 'is_running')
                #is_running = is_running.decode('utf-8') if isinstance(is_running, bytes) else is_running
                #is_running = bool(int(is_running or '0'))
                running_symbols = set(json.loads(await redis.hget(user_key, 'running_symbols') or '[]'))
                running_symbol = symbol in running_symbols

                user_data = await redis.hgetall(user_key)
                is_running = parse_bool(user_data.get('is_running', '0'))
                #print("CHECK CHECK ! ! ",running_symbol)
                if not is_running or not running_symbol:
                    print(f"Stopping loop. is_running: {is_running}, symbol {symbol} in running_symbols: {running_symbol}")
                    break
                ws_data = await symbol_queue.get()
                current_price, server_time = ws_data
                current_price = float(current_price)
                #current_price = await global_price_subscriber.get_current_price(exchange_name, symbol)
                if current_price is None:
                    print(f"Error: 🔴current_price is None. Skipping this iteration.")
                    continue
                current_time = int(time.time())
                current_minute = current_time // 60 % 60  # 현재 분 계산
                current_second = current_time % 60  # 현재 초 계산
                
                # Redis에서 symbol 관련 데이터 가져오기
                key = f"{exchange_name}:user:{user_id}:symbol:{symbol_name}"

                # 'grid_count'가 없는 경우 0으로 처리하여 합산
                total_grid_count = await redis_database.get_total_grid_count(redis, exchange_name, user_id, symbol_name)
                position_size = await get_position_size('okx', user_id, symbol_name)
                #================================================================================================
                # PERIODIC LOGIC
                #================================================================================================
                if current_minute % 15 == 0 and update_flag:  # 15분마다 한 번씩 실행되도록 수정
                    if current_time - last_execution_time >= 60:  # 마지막 실행 시간과 현재 시간의 차이가 60초 이상인 경우에만 실행
                        try:
                            #order_placed = user_keys.get(user_id, {}).get("symbol", {}).get(symbol_name, {}).get("order_placed", {n: False for n in range(0, grid_num + 1)})
                            order_placed_key = f'orders:{exchange_name}:user:{user_id}:symbol:{symbol}:order_placed'
                            order_placed_data = await redis.hgetall(order_placed_key)
                            order_placed = {}
                        except Exception as e:
                            print(f"An error occurred1001: {e}")
                        order_placed = {n: False for n in range(0, grid_num + 1)}
                        start_time = time.time()
                        await periodic_15m_logic(exchange_name, user_id, symbol_name, symbol, grid_num, price_precision, max_notional_value, initial_investment, order_quantities, direction, take_profit_orders_info, level_quantities, min_notional, adx_4h, overbought, oversold, order_buffer, exchange_instance, redis, possible_order_id_keys, order_ids, total_grid_count,current_price, current_time, position_size, sum_of_initial_capital)
                        end_time = time.time()
                        elapsed_time = end_time - start_time
                        if elapsed_time > 1:
                            print(f"{user_id} : {symbol} 15분 주기 로직 소요 시간: {round(elapsed_time,4)}")
                        update_flag = False
                else:
                    update_flag = True  # 15분이 되면 update_flag를 다시 True로 설정
                #================================================================================================
                # PERIODIC LOGIC END
                #================================================================================================
                try:
                    if grid_levels is None:
                        grid_levels = await periodic_analysis.calculate_grid_logic(direction = direction, grid_num = grid_num, symbol = symbol_name,exchange_name = exchange_name,  user_id = user_id , exchange_instance=exchange_instance)
                    quantity_list = []  # quantity_list 초기화
                    for i in range(grid_num):
                        initial_capital = initial_investment[i]
                        order_quantity = order_quantities[i]
                        if exchange_name == 'upbit':
                            order_price_unit = get_order_price_unit_upbit(current_price)
                            quantity_former = initial_capital / current_price
                            processing_qty = round_to_upbit_tick_size(quantity_former)
                            quantity = processing_qty
                        elif exchange_name == 'okx':
                            quantity = order_quantity
                        else:
                            quantity = (initial_capital / current_price)

                        quantity_list.append(quantity)  # 리스트에 quantity 값 추가

                except Exception as e:
                    print(f"An error occurred on {symbol} calculating order quantity: {e}")
                
                # 가장 가까운 4개의 그리드 레벨 찾기
                # 가장 가까운 4개의 그리드 레벨 찾기
                try:
                    closest_levels = []
                    if grid_num > 20:
                        for i in range(21, grid_num + 1):
                            grid_levels[f'grid_level_{i}'] = grid_levels['grid_level_20'] * (1 + 0.008 * (i - 20))
                    for n in range(0, grid_num + 1):
                        grid_level = grid_levels[f'grid_level_{n}'].iloc[-1]
                        if exchange_name == 'upbit':
                            grid_level = get_corrected_rounded_price(grid_level)
                        else:
                            grid_level = round(grid_level, int(price_precision))
                        closest_levels.append((n, grid_level))

                    closest_levels.sort(key=lambda x: abs(x[1] - current_price))
                    closest_levels = closest_levels[:4]
                    # 상위 2개와 하위 2개의 그리드 레벨 출력
                    upper_levels = [level for level in closest_levels if level[1] >= current_price][:2]
                    lower_levels = [level for level in closest_levels if level[1] < current_price][:2]
                    #print(f"근접 찾기 {symbol} current_price : {current_price}({grid_level}), upper levels: {upper_levels} , lowerlevels : {lower_levels}")
                    if direction == 'long':
                        upper_levels = [level for level in closest_levels if level[1] >= current_price][:1]
                        lower_levels = [level for level in closest_levels if level[1] < current_price][:2]
                    elif direction == 'short':
                        upper_levels = [level for level in closest_levels if level[1] >= current_price][:2]
                        lower_levels = [level for level in closest_levels if level[1] < current_price][:1]
                except Exception as e:
                    print(f"An error occurred on calculating closest levels: {e}")

                #print(f"{symbol} current_price : {current_price}({grid_level}), levels: {upper_levels} , {lower_levels}")

                #-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
                #===========================================숏 주문 생성 로직 시작========================================
                #-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
                short_logic_start_time = time.time()
                try:
                    order_placed = await get_order_placed(exchange_name, user_id, symbol_name, grid_num)
                    #order_placed = user_keys.get(user_id, {}).get("symbol", {}).get(symbol_name, {}).get("order_placed", {n: False for n in range(0, grid_num + 1)})
                    #print(f"{symbol} : order_placed", order_placed)
                except Exception as e:
                    print(f"An error occurred1001: {e}")
                    order_placed = {n: False for n in range(0, grid_num + 1)}
                try:
                    await short_logic(exchange_name, user_id, symbol_name, symbol, upper_levels, current_price, grid_levels, order_placed, grid_num,
                                         price_precision, max_notional_value, initial_investment, order_quantities, quantity_list, new_position_size,
                                         direction, take_profit_orders_info, level_quantities, min_notional, temporally_waiting_short_order,
                                         adx_4h, overbought, oversold, order_buffer, exchange_instance, redis, possible_order_id_keys, order_ids, position_size, over_20_grid)
                except Exception as e:
                    print(f"{user_id} : {symbol} An error occurred on short logic: {e}")
                short_logic_end_time = time.time()
                if short_logic_end_time - short_logic_start_time > 1:
                    print(f"{symbol} 숏 로직 소요 시간: {round(short_logic_end_time - short_logic_start_time,4)}")
                #-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
                #===========================================숏 주문 생성 로직 끝==========================================
                #-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-       
                current_time = datetime.now()
                if current_time.minute % 5 == 0 and (current_time.second == 0 or current_time.second == 1 or current_time.second == 2 or current_time.second == 3 or current_time.second == 4):
                    filtered_order_placed = {k: v for k, v in order_placed.items() if v}
                    print(f'{user_id} : {symbol} order placed list :', filtered_order_placed)
                
                #-------------------------------------------------------------------------------------------------------
                #===========================================롱 주문 생성 로직 시작===========================================
                #-------------------------------------------------------------------------------------------------------
                long_logic_start_time = time.time()

                try:
                    await long_logic(exchange_name, user_id, symbol_name, symbol, lower_levels, current_price, grid_levels, order_placed, grid_num,
                     price_precision, max_notional_value, initial_investment, order_quantities, quantity_list,
                     direction, take_profit_orders_info, level_quantities, min_notional, temporally_waiting_long_order,
                     adx_4h, overbought, oversold, order_buffer, exchange_instance, redis, possible_order_id_keys, order_ids, position_size, under_1_grid)
                except Exception as e:
                    print(f"{user_id} : An error occurred on long logic: {e}")
                long_logic_end_time = time.time()
                if long_logic_end_time - long_logic_start_time > 1 :
                    print(f"{symbol} 롱 로직 소요 시간: {round(long_logic_end_time - long_logic_start_time,4)}")
                await asyncio.sleep(2.5)  # 주문 생성 간격 (예: 1초)

                #current_time = int(time.time())
                #current_minute = current_time // 60 % 60  # 현재 분 계산
                #seconds = current_time % 60  # 현재 초 
                #if current_minute % 1 == 0 and seconds == 0:  # 1분마다 한 번씩 실행되도록 수정
                #    if current_time - last_execution_time > 50:
                #        print(f"순회 확인: {symbol} {current_minute}분 {seconds}초")
                #        circulation_count += 1
                #        print(f"순회 횟수: {circulation_count}")
                #        last_execution_time = time.time()
            except Exception as e:
                error_message = str(e)
                if 'KeyError' in error_message:
                    print(f"KeyError: {error_message}")
                    raise e
                elif 'UnboundLocalError' in error_message:
                    print(f"UnboundLocalError: {error_message}")
                    raise e
                elif "'NoneType' object is not subscriptable" in error_message:
                    print(f"Error placing {symbol} grid orders: {error_message}")
                else:
                    print(f"🟡 :{take_profit_orders_info}")
                    print(f"An error occurred on placing {symbol} grid orders: {error_message}")
                print(traceback.print_exc())

                

        #================================================================================================
        # 루프 종료
        #================================================================================================
        print('종료.')
        return

    except Exception as e:
        if 'remove' in str(e):
            print(f"{user_id} : remove the symbol {symbol}: {e}")
            await strategy.close(exchange_instance, symbol_name, message = f'{user_id} : 종목을 제거하고 재탐색 합니다.',user_id = user_id,)
            completed_symbols.add(symbol)

            raise Exception(f"remove")
        print(f"An error occurred008: {e}")
        print(traceback.print_exc())
        return

    finally:
        recovery_mode = False
        try:
            user_key = f'{exchange_name}:user:{user_id}'
            user_data = await redis.hgetall(user_key)
            stop_task_only = parse_bool(user_data.get('stop_task_only', '0'))
        except Exception as e :
            print(f"exception on stop_task_only: {e}")
            stop_task_only = False
        try:
            recovery_state = await redis.get('recovery_state')
            recovery_mode = True if recovery_state == 'True' else False
        except Exception as e:
            print(f"An error occurred: {e}")
            recovery_mode = False
        print(f"recovery_state: {recovery_state}")
        print(f"recovery_mode: {recovery_mode}")
        print(f"stop_task_only: {stop_task_only}")
        if exchange_name is not None:
            if stop_task_only or recovery_mode:
                print(f"{user_id} : stop_task_only 혹은 recovery_mode가 활성화 되어 포지션 종료 없이 {symbol} 심볼 테스크만 취소합니다.")
                
                pass
            else:
                print(f"{user_id} : 포지션 종료")
                await strategy.close(exchange = exchange_name, symbol = symbol_name, user_id = user_id)
            await strategy.cancel_all_limit_orders(exchange_name, symbol_name, user_id)
            #global_messages.trading_message.put(f"{symbol_name}의 모든 주문이 취소되었습니다.")
            message = f"{symbol_name}의 모든 주문이 취소되었습니다."
            #await manager.add_user_message(user_id, message)
            await add_user_log(user_id, message)
            await exchange_instance.close()
        if not recovery_mode and not stop_task_only:
            completed_symbols.add(symbol)
            running_symbols.remove(symbol)
            await redis.hset(user_key, 'completed_trading_symbols', json.dumps(list(completed_symbols)))
            await redis.hset(user_key, 'running_symbols', json.dumps(list(running_symbols)))
            print(f"{user_id} : {symbol} 종료 후 completed_symbols : {completed_symbols}")
            print(f"{user_id} : {symbol} 종료 후 running_symbols : {running_symbols}")
        #await redis.hset(user_key, 'is_running', '0')
        #await redis.close()
        return
        

async def periodic_15m_logic(exchange_name, user_id, symbol_name, symbol, grid_num, price_precision, max_notional_value, initial_investment, order_quantities, direction, take_profit_orders_info, level_quantities, min_notional, adx_4h, overbought, oversold, order_buffer, exchange_instance, redis, possible_order_id_keys, order_ids, total_grid_count,current_price, current_time, position_size, sum_of_initial_capital):
    
    current_timestamp = int(time.time())
    temporally_waiting_short_order = False
    print(f"{symbol} 이 15분로직에 들어옴")
    #last_placed_price = {n: 0.0 for n in range(0, grid_num + 1)}
    await reset_order_placed(exchange_name, user_id, symbol_name, grid_num)
    print(f"현재 {symbol}의 그리드 카운트 총 합 : {total_grid_count}")
    await asyncio.sleep(0.1)
    #print(f"{symbol}의 current price: {current_price}, currnet_time : {current_time}, server_time : {server_time}")
    print(f"{symbol}의 current price: {current_price}, currnet_time : {current_time}")
    # 그리드 레벨 업데이트
    try:
        await asyncio.sleep(random.random())
        if exchange_name == 'okx' or exchange_name == 'okx_spot':
            grid_levels = await periodic_analysis.calculate_grid_logic(direction, grid_num = grid_num, symbol = symbol, exchange_name = exchange_name, user_id = user_id, exchange_instance=exchange_instance)
        else:
            grid_levels = await periodic_analysis.calculate_grid_logic(direction, grid_num = grid_num, symbol = symbol, exchange_name = exchange_name, user_id = user_id, exchange_instance=exchange_instance)
    except Exception as e:
        print(f"An error in getting {symbol} Dataframe: {e}")
        await asyncio.sleep(3)
        grid_levels =await periodic_analysis.calculate_grid_logic(direction, grid_num = grid_num, symbol = symbol, exchange_name = exchange_name, user_id = user_id, exchange_instance=exchange_instance)
    end_timestamp = int(time.time())
    elapsed_time = end_timestamp - current_timestamp
    print(f"🐻🌟🥇{symbol} Elapsed time 000 : {elapsed_time} seconds")
    if grid_levels is None:
    #    await redis_database.remove_running_symbol(user_id, symbol, exchange_name, redis)
        print(f"🔴{user_id} : {symbol} : 종목을 제대로 받아올 수 없음. 확인 필요.")
        await asyncio.sleep(20)
    #    raise Exception("remove")
    if not grid_levels.empty:
        # grid_level_0와 grid_level_21 추가
        grid_levels.loc[:, 'grid_level_0'] = grid_levels['grid_level_1'] * (1 - 0.008)
        grid_levels.loc[:, 'grid_level_21'] = grid_levels['grid_level_20'] * (1 + 0.008)
        # grid_num이 20보다 큰 경우 추가 레벨 계산
        if grid_num > 20:
            for i in range(21, grid_num + 1):
                grid_levels.loc[:, f'grid_level_{i}'] = grid_levels['grid_level_20'] * (1 + 0.008 * (i - 20))
        
        # ADX 4H 상태 확인
        if 'adx_state_4h' in grid_levels.columns:
            adx_4h = grid_levels['adx_state_4h'].iloc[-1]
        else:
            adx_4h = 0
            print(f"Error: 🔴ADX 4H state not found in grid_levels for {symbol}. Setting ADX 4H to 0.")
    else:
        await asyncio.sleep(2)
        #raise ValueError("grid_levels is empty")
    
    # 기존 주문 취소
    try:
        current_time = int(time.time())
        current_minute = current_time // 60 % 60  # 현재 분 계산
        current_second = current_time % 60  # 현재 초 계산
        order_placed = {n: False for n in range(0, grid_num + 1)}

        current_position_size = await get_balance_of_symbol(exchange_instance, symbol_name, user_id)
        
        # Redis에서 symbol 관련 데이터 가져오기
        user_key = f'{exchange_name}:user:{user_id}'
        user_data = await redis.hgetall(user_key)
        symbol_key = f'{user_key}:symbol:{symbol_name}'
        #symbol_data = json.loads(await redis.hget(symbol_key, 'data') or '{}')
        take_profit_orders_info = await get_take_profit_orders_info(redis, exchange_name, user_id, symbol_name, grid_num, force_restart=False)
        initial_balance = 0.0
        #initial_balance = user_data.get('initial_balance', 0)
        #<-- Initial Balance를 제거
        #previous_position_size = symbol_data.get('previous_new_position_size', 0) #<--p- 당장 key문제.

        new_position_size = (current_position_size) if current_position_size is not None else 0.0 #<-- 우선, OKX선물만 진행하니까, Initial Balance를 제거. 
        ordered_position_size = 0.0
        last_entry_size = new_position_size - user_keys[user_id]["symbols"][symbol]["previous_new_position_size"]
        user_keys[user_id]["symbols"][symbol]["last_entry_size"] = new_position_size
        user_keys[user_id]["symbols"][symbol]["previous_new_position_size"] = new_position_size
        #print(f"{symbol}의 현재 포지션 사이즈 : {last_entry_size}, 마지막 진입 사이즈 : {last_entry_size}") 
        if exchange_name == 'upbit' or exchange_name == 'binance_spot' or exchange_name == 'bitget_spot' or exchange_name == 'okx_spot':
            if new_position_size < 0.0:
                initial_balance_of_symbol = 0.0
        try:
            maxi_position_size = (sum_of_initial_capital / current_price)
        except Exception as e:
            initial_investment = json.loads(await redis.hget(user_key, 'initial_capital'))
            sum_of_initial_capital = sum(initial_investment)
            maxi_position_size = (sum_of_initial_capital / current_price)
        if (new_position_size) > maxi_position_size*0.95:
            overbought = True
            if current_minute % 60 == 0:
                print(f"현재 포지션 사이즈 : {new_position_size}, 최대 롱 포지션 사이즈 : {maxi_position_size}")

        elif (new_position_size < -maxi_position_size*0.95):
            oversold = True
            if current_minute % 60 == 0:
                print(f"현재 포지션 사이즈 : {new_position_size}, 최대 숏 포지션 사이즈 : -{maxi_position_size}")
        else:
            overbought = False
            oversold = False
    except Exception as e:
        print(f"{user_id} : An error occurred105: {e}")
        print(traceback.format_exc())
        overbought = False
        oversold = False
    end_timestamp = int(time.time())
    elapsed_time = end_timestamp - current_timestamp
    print(f"😇{symbol} Elapsed time 01 : {elapsed_time} seconds")
    ### 익절 주문 로직 ###
    try:
        closest_levels = []
        if grid_num > 20:
            for i in range(21, grid_num + 1):
                grid_levels[f'grid_level_{i}'] = grid_levels['grid_level_20'] * (1 + 0.008 * (i - 20))
        for n in range(0, grid_num + 1):
            grid_level = grid_levels[f'grid_level_{n}'].iloc[-1]
            if exchange_name == 'upbit':
                grid_level = get_corrected_rounded_price(grid_level)
            else:
                grid_level = round(grid_level, int(price_precision))
            closest_levels.append((n, grid_level))
        closest_levels.sort(key=lambda x: abs(x[1] - current_price))
        closest_levels = closest_levels[:4]
        # 상위 2개와 하위 2개의 그리드 레벨 출력
        upper_levels = [level for level in closest_levels if level[1] >= current_price][:2]
        lower_levels = [level for level in closest_levels if level[1] < current_price][:2]
        print(f"15분 로직 {symbol} current_price : {current_price}({grid_level}), levels: {upper_levels} , {lower_levels}")
        if direction == 'long':
            upper_levels = [level for level in closest_levels if level[1] > current_price][:1]
            lower_levels = [level for level in closest_levels if level[1] <= current_price][:2]
        elif direction == 'short':
            upper_levels = [level for level in closest_levels if level[1] >= current_price][:2]
            lower_levels = [level for level in closest_levels if level[1] < current_price][:1]
    except Exception as e:
        print(f"{user_id} : An error occurred on 익절 계산 로직: {e}")
    try:
        #print(type(level))
        orders_count = 0 
        max_orders = 4
        if (abs(new_position_size) > 0.0) or abs(last_entry_size > 0.0):
            tp_order_side = 'sell' if new_position_size > 0 else 'buy'
            if new_position_size == 0.0:
                tp_order_side = 'sell' if last_entry_size > 0 else 'buy'
            print(f"{symbol} 익절 주문 사이드 : {tp_order_side}")
            #print(f"{symbol} 익절 주문 정보 : {take_profit_orders_info}")
            #for level, info in user_keys[user_id]["symbols"][symbol_name]["take_profit_orders_info"].items(): # <--원본. 07181640

            for level, info in take_profit_orders_info.items(): 
                level_index = int(level)  # level을 정수로 변환
                level_str = str(level)
                #if (direction == 'long-short' and position_size != 0) or info["active"]: #<-- Take Profit Order Info에서, 익절주문이 활성화되는 경우.
                if info["active"]: #<-- Take Profit Order Info에서, 익절주문이 활성화되는 경우.
                    saved_quantity = info['quantity']
                    if info["active"]:
                        print(f"{symbol}의 {level}번째 active된 익절 주문 정보 : {info}. 현재 포지션 사이즈 : {new_position_size}")
                    
                        print(f"{symbol}이 {level}에서 활성화된 익절 주문이 있습니다. 정보 : {info}")
                    if saved_quantity == 0.0 and info["active"]:
                        print(f"{level}에서 활성화된 익절 주문이 있지만, 수량이 0입니다. 정보 : {info}")
                        await telegram_message.send_telegram_message(f"{symbol}에서 {level}에서 활성화된 익절 주문이 있지만, 수량이 0입니다. 정보 : {info}", exchange_name, debug = True)
                        #continue
                    await asyncio.sleep(random.uniform(0.05, order_buffer+0.1))
                    try:
                        if level_index > 1 and level_index < int(grid_num):
                            new_price = grid_levels[f'grid_level_{level_index-1}'].iloc[-1] if tp_order_side == 'buy' else grid_levels[f'grid_level_{level_index+1}'].iloc[-1]
                            if isinstance(new_price, tuple):
                                print(f"Level: {level_index}, tp_order_side: {tp_order_side}, price is a tuple: {new_price}")
                                new_price = float(new_price) if not isinstance(new_price, tuple) else float(new_price[0])
                            else:
                                if level_index > 1 and level_index < int(grid_num):
                                    new_price = float(grid_levels[f'grid_level_{level_index-1}'].iloc[-1]) if tp_order_side == 'buy' else float(grid_levels[f'grid_level_{level_index+1}'].iloc[-1])
                                    if isinstance(new_price, tuple):
                                        print(f"🔥튜플1 Level: {level_index}, tp_order_side: {tp_order_side}, price is a tuple: {new_price}")
                                        new_price = float(new_price[0])  # 튜플의 첫 번째 값을 사용
                                    else:
                                        new_price = float(new_price)
                                elif level_index == 1 and tp_order_side == 'buy':
                                    new_price = float(grid_levels[f'grid_level_{1}'].iloc[-1])*0.99
                                    if instance(new_price, tuple):
                                        print(f"🔥튜플2 Level: {level}, tp_order_side: {tp_order_side}, price is a tuple: {new_price}")
                                        new_price = float(new_price[0])
                                elif level_index == grid_num and tp_order_side == 'sell':
                                    new_price = float(grid_levels[f'grid_level_{grid_num}'].iloc[-1])*1.01
                                    if isinstance(new_price, tuple):
                                        print(f"🔥튜플3 Level: {level_index}, tp_order_side: {tp_order_side}, price is a tuple: {new_price}")
                                        new_price = float(new_price[0])
                                        # 디버깅을 위해 추가된 출력
                                    print(f"Level: {level_index}, new_price: {new_price}, info: {info}")
                    except Exception as e:
                        print(f"{user_id} : An error occurred on tp order23 : {e}")
                        traceback.print_exc()
                    try:
                        #take_profit_side = 'buy' if take_profit_orders_info.get(level, {}).get('side') == 'buy' else 'sell'
                        #take_profit_side = 'buy' if user_keys[user_id]["symbols"][symbol_name]["take_profit_orders_info"][level]['side'] == 'buy' else 'sell'# <-- 이게 원본07181642
                        take_profit_side = 'buy' if info['side'] == 'buy' else 'sell'
                        okay_to_order = await okay_to_place_order(exchange_name, user_id, symbol, new_price, max_notional_value, order_direction = tp_order_side)
                        if (okay_to_order):
                            if (current_price > new_price) and (take_profit_side == 'sell'):
                                new_price = current_price*(1 + 0.007*orders_count)
                            elif (current_price < new_price) and (take_profit_side == 'buy'):
                                new_price = current_price*(1 - 0.007*orders_count)
                            if ((current_price < new_price) and (take_profit_side == 'sell')) or ((current_price > new_price) and (take_profit_side == 'buy')) and orders_count < max_orders : 
                                if (not await is_price_placed(exchange_name, user_id, symbol, new_price, grid_level = level_index)) and (not await is_order_placed(exchange_name, user_id, symbol, level)):
                                    await asyncio.sleep(random.uniform(0.05, order_buffer+0.5))
                                    print(f"{symbol}이 order_buffer만큼 대기합니다1. {order_buffer}")
                                    if exchange_name == 'upbit':
                                        new_price = get_corrected_rounded_price(new_price)
                                    else:
                                        new_price = round(new_price, price_precision)
                                    if exchange_name == 'bitget':
                                        tp_order = await exchange_instance.create_order(
                                            symbol=symbol_name,
                                            type='limit',
                                            side=tp_order_side, #<-- side는, 이전 주문의 반대로 해야함. 일단은 sell 설정.
                                            amount=info["quantity"],
                                            price=new_price,
                                            params={
                                            'contract_type': 'swap',
                                            'position_mode': 'single',
                                            'marginCoin': 'USDT',
                                            'reduce_only': True
                                            }
                                        )
                                    elif exchange_name == 'binance':
                                        try:
                                            tp_order = await exchange_instance.create_order(
                                                symbol=symbol_name,
                                                type='limit',
                                                side=tp_order_side, 
                                                amount=abs(info["quantity"]),
                                                price=new_price,
                                                params={'reduceOnly': True}
                                            )
                                        except Exception as e:
                                            if ('margin' in str(e)) or ('Insufficient' in str(e)):
                                                print(f"{user_id} : An error occurred on tp order : {e}")
                                                temporally_waiting_long_order = True
                                                temporally_waiting_short_order = True
                                            else:
                                                print(f"{user_id} : An error occurred on tp order : {e}")
                                    elif exchange_name == 'binance_spot':
                                        try:
                                            tp_order = await exchange_instance.create_order(
                                                symbol=symbol_name,
                                                type='limit',
                                                side='sell', #<-- 현물이므로, sell 설정.
                                                amount=info["quantity"],
                                                price=new_price
                                            )
                                        except Exception as e:
                                            print(f"{user_id} : An error occurred18: {e}")
                                    elif exchange_name == 'okx':
                                        try:
                                            tp_order = await exchange_instance.create_order(
                                                symbol=symbol_name,
                                                type='limit',
                                                side=tp_order_side, #<-- side는, 이전 주문의 반대로 해야함. 일단은 sell 설정.
                                                amount=abs(info["quantity"]),
                                                price=new_price,
                                                params={'reduceOnly': True}
                                            )
                                            print('tp_order09')
                                        except Exception as e:
                                            if 'margin' in str(e) or 'insufficient' in str(e):
                                                print(f"{user_id} : An error occurred on tp order : {e}")
                                                temporally_waiting_long_order = True
                                                temporally_waiting_short_order = True
                                            else:
                                                print(f"{user_id} : An error occurred on tp order : {e}")
                                    elif exchange_name == 'okx_spot':
                                        print('exchange okx_spot')
                                        try:
                                            tp_order = await exchange_instance.create_order(
                                                symbol=symbol_name,
                                                type='limit',
                                                side='sell', #<-- side는, 현물이므로 sell.
                                                amount=info["quantity"],
                                                price=new_price,
                                            )

                                        except Exception as e:
                                            print(f"An error occurred on limitorder: {e}")
                                    elif exchange_name == 'bitget_spot':
                                        tp_order = await exchange_instance.create_order(
                                            symbol=symbol_name,
                                            type='limit',
                                            side='sell', #<-- side는, 이전 주문의 반대로 해야함. 일단은 sell 설정.
                                            amount=info["quantity"],
                                            price=new_price,
                                        )
                                    elif exchange_name == 'upbit':
                                        try:
                                            print(f"amount 확인 : {info['quantity']}. new_price : {new_price}")
                                            if info['quantity'] <= 0:
                                                print(f'🚨익절물량이 0보다 작으므로 확인해봐야한다. 함수 시작saved : {saved_quantity}')
                                                await telegram_message.send_telegram_message(f'🚨{symbol}의 {level} 익절물량이 0보다 작으므로 확인해봐야한다. 함수 시작saved : {saved_quantity}', exchange_name = 'upbit', user_id = user_id, debug = True)

                                            tp_order = await retry_async(strategy.place_order, exchange = exchange_instance, symbol=symbol_name,order_type='limit',side='sell',amount=info["quantity"],price=new_price)
                                        except Exception as e: 
                                            print(f"{user_id} : An error occurred for tp : {e}")
                                            return
                                    else:
                                        print(f"{symbol}에서, {exchange_name}가 이상하게 설정됨..")
                                        tp_order = await exchange_instance.create_order(
                                            symbol=symbol_name,
                                            type='limit',
                                            side=tp_order_side, #<-- 여기, side는 이전 주문의 반대로 설정해야함
                                            amount=info["quantity"],
                                            price=new_price
                                        )
                                        print('tp_orer10')
                                    for key in possible_order_id_keys:
                                        if tp_order is not None and 'info' in tp_order and key in tp_order['info']:
                                            order_id = tp_order['info'][key]
                                            break
                                    try:
                                        asyncio.create_task(monitor_tp_orders_websocekts(exchange_name,symbol_name ,user_id, level, take_profit_orders_info))
                                        await add_placed_price(exchange_name, user_id, symbol, new_price)
                                        await set_order_placed(exchange_name, user_id, symbol, grid_level, level_index=level_index)
                                        print(f"🔥여기에서, grid_level이 어떻게 표현되는지 확인. {grid_level}")
                                        
                                        #take_profit_orders_info = user_keys[user_id]["symbols"][symbol_name]["take_profit_orders_info"]
                                        #user_keys[user_id]["symbols"][symbol_name]["take_profit_orders_info"][level]['order_id'] = order_id
                                        #user_keys[user_id]["symbols"][symbol_name]["take_profit_orders_info"][level]['target_price'] = new_price
                                        #user_keys[user_id]["symbols"][symbol_name]["take_profit_orders_info"][level]['quantity'] = (info["quantity"])
                                        #user_keys[user_id]["symbols"][symbol_name]["take_profit_orders_info"][level]['active'] = True
                                        take_profit_orders_info[level_str].update({
                                            'order_id': order_id,
                                            'target_price': new_price,
                                            'quantity': info["quantity"],
                                            'active': True
                                        })
                                        print(f"{symbol}의 {level}번째 익절 주문이 활성화되었습니다. 정보 : {take_profit_orders_info[str(level)]}")
                                        await update_take_profit_orders_info(redis, exchange_name,user_id,symbol_name,level,order_id,new_price,info["quantity"], active = True, side = tp_order_side)
                                        #symbol_data['take_profit_orders_info'] = take_profit_orders_info
                                        #await redis.hset(symbol_key, 'take_profit_orders_info', json.dumps(symbol_data))
                                        order_placed[level] = True
                                        orders_count += 1  # 주문 생성 후 수를 증가
                                        print(f" {symbol}의 order count : {orders_count}")
                                    except Exception as e:
                                        print(f"{user_id} : An error occurred on tp order 15m logic : {e}")
                                        #raise e

                            elif ((current_price < new_price) and (take_profit_side == 'buy')) and (not await is_price_placed(exchange_name, user_id, symbol_name, new_price, grid_level = level)): #<-- 숏 주문에 대한 익절 주문 가격 설정
                                if level > 1:
                                    new_price = float(grid_levels[f'grid_level_{level-1}'].iloc[-1])
                                    print(f"분기5. 숏 주문에 대한 new_price : {new_price}")
                                elif level == 1:
                                    new_price = float(grid_levels[f'grid_level_{1}'].iloc[-1])*0.993
                                    print(f"분기6. 숏 주문에 대한 new_price : {new_price}")
                                else:
                                    new_price = float(current_price)*0.995
                                    print(f"분기7. 숏 주문에 대한 new_price : {new_price}. current_price : {current_price}")
                                if exchange_name == 'upbit':
                                    new_price = get_corrected_rounded_price(new_price)
                                else:
                                    new_price = round(new_price, price_precision)
                                if exchange_name == 'bitget':
                                    tp_order = await exchange_instance.create_order(
                                        symbol=symbol_name,
                                        type='limit',
                                        side='buy', #<-- side는, 이전 주문의 반대로 해야함. 일단은 sell 설정.
                                        amount=abs(info["quantity"]),
                                        price=new_price,
                                        params={
                                        'contract_type': 'swap',
                                        'position_mode': 'single',
                                        'marginCoin': 'USDT',
                                        'reduce_only': True
                                        }
                                    )
                                elif exchange_name == 'binance':
                                    try:
                                        tp_order = await exchange_instance.create_order(
                                            symbol=symbol_name,
                                            type='limit',
                                            side=take_profit_side, 
                                            amount=abs(info["quantity"]),
                                            price=new_price,
                                            params={'reduceOnly': True}
                                        )
                                    except Exception as e:
                                        print(f"An error occurred on tp order : {e}")
                                elif exchange_name == 'okx':
                                    try:
                                        tp_order = await exchange_instance.create_order(
                                            symbol=symbol_name,
                                            type='limit',
                                            side=take_profit_side, #<-- side는, 이전 주문의 반대로 해야함. 일단은 sell 설정.
                                            amount=abs(info["quantity"]),
                                            price=new_price,
                                            params={'reduceOnly': True}
                                        )
                                        await add_placed_price(exchange_name, user_id, symbol_name, price=new_price)
                                        await set_order_placed(exchange_name, user_id, symbol_name, new_price, level_index = level_index)
                                        print('tp_order11')
                                    except Exception as e:
                                        print(f"{user_id} : An error occurred on limitorder: {e}")
                                else:
                                    tp_order = await exchange_instance.create_order(
                                        symbol=symbol_name,
                                        type='limit',
                                        side=take_profit_side, #<-- 여기, side는 이전 주문의 반대로 설정해야함
                                        amount=info["quantity"],
                                        price=new_price
                                    )
                                for key in ['order_id', 'uuid', 'orderId', 'ordId']:
                                    if 'info' in tp_order and key in tp_order['info']:
                                        order_id = tp_order['info'][key]
                                        break
                                asyncio.create_task(monitor_tp_orders_websocekts(exchange_name,symbol_name ,user_id, level, take_profit_orders_info))
                                #user_keys[user_id]["symbols"][symbol_name]["take_profit_orders_info"][level]['order_id'] = order_id
                                #user_keys[user_id]["symbols"][symbol_name]["take_profit_orders_info"][level]['target_price'] = new_price
                                #user_keys[user_id]["symbols"][symbol_name]["take_profit_orders_info"][level]['quantity'] = (info["quantity"])
                                #user_keys[user_id]["symbols"][symbol_name]["take_profit_orders_info"][level]['active'] = True
                                take_profit_orders_info[str(level)].update({
                                            'order_id': order_id,
                                            'target_price': new_price,
                                            'quantity': info["quantity"],
                                            'active': True
                                        })
                                await add_placed_price(exchange_name, user_id, symbol, new_price)
                                await set_order_placed(exchange_name, user_id, symbol, new_price, level_index = level_index)
                                await update_take_profit_orders_info(redis, exchange_name,user_id,symbol_name,level,order_id,new_price,info["quantity"], True, side = take_profit_side)
                                order_placed[level_index] = True
                                orders_count += 1  # 주문 생성 후 수를 증가

                            elif ((current_price > new_price) and (take_profit_side == 'sell')) :
                                if level < grid_num:
                                    new_price = float(grid_levels[f'grid_level_{level+1}'].iloc[-1])
                                elif level == grid_num:
                                    new_price = float(grid_levels[f'grid_level_{grid_num}'].iloc[-1])*1.007
                                else:
                                    new_price = float(current_price)*1.005
                                if exchange_name == 'upbit':
                                    new_price = get_corrected_rounded_price(new_price)
                                else:
                                    new_price = round(new_price, price_precision)
                                if exchange_name == 'bitget':
                                    tp_order = await exchange_instance.create_order(
                                        symbol=symbol_name,
                                        type='limit',
                                        side=take_profit_side, #<-- side는, 이전 주문의 반대로 해야함. 일단은 sell 설정.
                                        amount=info["quantity"],
                                        price=new_price,
                                        params={
                                        'contract_type': 'swap',
                                        'position_mode': 'single',
                                        'marginCoin': 'USDT',
                                        'reduce_only': True
                                        }
                                    )
                                elif exchange_name == 'binance':
                                    try:
                                        tp_order = await exchange_instance.create_order(
                                            symbol=symbol_name,
                                            type='limit',
                                            side=take_profit_side, 
                                            amount=info["quantity"],
                                            price=new_price,
                                            params={'reduceOnly': True}
                                        )
                                    except Exception as e:
                                        print(f"An error occurred on tp order : {e}")
                                elif exchange_name == 'binance_spot':
                                    try:
                                        tp_order = await exchange_instance.create_order(
                                            symbol=symbol_name,
                                            type='limit',
                                            side='sell', #<-- 현물이므로, sell 설정.
                                            amount=info["quantity"],
                                            price=new_price
                                        )
                                    except Exception as e:
                                        print(f"An error occurred20: {e}")
                                elif exchange_name == 'okx':
                                    try:
                                        tp_order = await exchange_instance.create_order(
                                            symbol=symbol_name,
                                            type='limit',
                                            side=take_profit_side, #<-- side는, 이전 주문의 반대로 해야함. 일단은 sell 설정.
                                            amount=info["quantity"],
                                            price=new_price
                                        )
                                    except Exception as e:
                                        if 'margin' in str(e) or 'insufficient' in str(e):
                                            print(f"{user_id} : An error occurred on tp order : {e}")
                                            temporally_waiting_long_order = True
                                            temporally_waiting_short_order = True
                                        else:
                                            print(f"{user_id} : An error occurred on limitorder: {e}")
                                elif exchange_name == 'okx_spot':
                                    print('exchange okx_spot')
                                    try:
                                        tp_order = await exchange_instance.create_order(
                                            symbol=symbol_name,
                                            type='limit',
                                            side='sell', #<-- side는, 현물이므로 sell.
                                            amount=info["quantity"],
                                            price=new_price,
                                        )

                                    except Exception as e:
                                        print(f"An error occurred on limitorder: {e}")
                                elif exchange_name == 'bitget_spot':
                                    tp_order = await exchange_instance.create_order(
                                        symbol=symbol_name,
                                        type='limit',
                                        side='sell', #<-- side는, 이전 주문의 반대로 해야함. 일단은 sell 설정.
                                        amount=info["quantity"],
                                        price=new_price,
                                    )
                                elif exchange_name == 'upbit':
                                    try:
                                        tp_order = await retry_async(strategy.place_order, exchange = exchange_instance, symbol=symbol_name,order_type='limit',side='sell',amount=info["quantity"],price=new_price)
                                    except Exception as e: 
                                        print(f"An error occurred for tp : {e}")
                                        raise e
                                else:
                                    tp_order = await exchange_instance.create_order(
                                        symbol=symbol_name,
                                        type='limit',
                                        side=take_profit_side, #<-- 여기, side는 이전 주문의 반대로 설정해야함
                                        amount=info["quantity"],
                                        price=new_price
                                    )
                                for key in possible_order_id_keys:
                                    if 'info' in tp_order and key in tp_order['info']:
                                        order_id = tp_order['info'][key]
                                        break
                                #user_keys[user_id]["symbols"][symbol_name]["take_profit_orders_info"][level]['order_id'] = order_id
                                #user_keys[user_id]["symbols"][symbol_name]["take_profit_orders_info"][level]['target_price'] = new_price
                                #user_keys[user_id]["symbols"][symbol_name]["take_profit_orders_info"][level]['quantity'] = info["quantity"]
                                #user_keys[user_id]["symbols"][symbol_name]["take_profit_orders_info"][level]['active'] = True
                                await update_take_profit_orders_info(redis, exchange_name,user_id,symbol_name,level,order_id,new_price,info["quantity"], active = True, side = take_profit_side)
                                order_placed[level] = True
                                await add_placed_price(exchange_name, user_id, symbol_name, price=new_price)
                                await set_order_placed(exchange_name, user_id, symbol_name, new_price, level_index = level)
                                await asyncio.sleep(random.uniform(0.05, order_buffer+0.1))
                                asyncio.create_task(monitor_tp_orders_websocekts(exchange_name,symbol_name , user_id, level, take_profit_orders_info))
                                orders_count += 1  # 주문 생성 후 수를 증가
                            else:
                                pass
                                #print(f"level: {level}, current_price: {current_price}, new_price: {new_price}, take_profit_side: {take_profit_side}, symbol: {symbol_name}, orders_count: {orders_count}")
                        
                    except Exception as e:
                        print(f'{user_id} 1: An error occurred on tp order(long): {e}')
                        
                elif (new_position_size > 0.0 ) and not take_profit_orders_info[str(level)]["active"] and float(take_profit_orders_info[str(level)]["quantity"]) > 0.0:
                    await asyncio.sleep(random.uniform(0.05, order_buffer+0.1))
                    try:

                        if isinstance(upper_levels[0], tuple):
                            print(f"튜플로 나오는 것 확인. {upper_levels[0]}")
                            new_price = float(upper_levels[0][1])
                            print(f'적용 후 {new_price}')
                        else:
                            new_price = float(upper_levels[0])
                        #print("quantity 확인" ,take_profit_orders_info[level]["quantity"])
                        tp_order = await exchange_instance.create_order(
                            symbol=symbol_name,
                            type='limit',
                            side='sell',
                            #amount=take_profit_orders_info[level]["quantity"],
                            amount=float(info["quantity"]), #user_keys[user_id]["symbols"][symbol_name]["take_profit_orders_info"][str(level)]["quantity"],
                            price=max(new_price, current_price*1.005)
                        )
                        order_id = None
                        for key in possible_order_id_keys:
                            if 'info' in tp_order and key in tp_order['info']:
                                order_id = tp_order['info'][key]
                                print("order_id 연속성 확인", order_id)
                                break
                            print("order_id 연속성 확인", order_id)
                            #user_keys[user_id]["symbols"][symbol_name]["take_profit_orders_info"][level]["order_id"] = order_id
                            #user_keys[user_id]["symbols"][symbol_name]["take_profit_orders_info"][level]["target_price"] = max(new_price, current_price*1.005)
                            #user_keys[user_id]["symbols"][symbol_name]["take_profit_orders_info"][level]["active"] = True
                            target_price = max(new_price, current_price*1.005)
                            await update_take_profit_orders_info(redis, exchange_name,user_id,symbol_name,level,order_id,target_price,info["quantity"], True, side = 'sell')
                            await asyncio.sleep(random.uniform(0.05, order_buffer+0.1))
                            asyncio.create_task(monitor_tp_orders_websocekts(exchange_name, symbol_name, user_id, level, take_profit_orders_info))
                            order_placed[level] = True
                            await add_placed_price(exchange_name, user_id, symbol_name, price=new_price)
                            await set_order_placed(exchange_name, user_id, symbol_name, new_price, level_index = level)
                            orders_count += 1  # 주문 생성 후 수를 증가
                            break
                    #elif (new_position_size < 0.0 ) and not take_profit_orders_info[level]["active"] and float(take_profit_orders_info[level]["quantity"]) > 0.0 and direction == 'short':
                        
                    except Exception as e:
                        print(f"{user_id} 2: An error occurred on tp order(long): {e}")
                        tp_order = None
                #else:
                #    if position_size != 0 and info["active"] == False:
                #        print(f"{symbol}의 info : {info}")
                    
                    #if info["active"] == False:
                    #    await update_take_profit_orders_info(redis, exchange_name,user_id,symbol_name = symbol_name, level = level, order_id = None, new_price = 0.0, quantity= 0.0, active =  False, side= None)
                        #user_keys[user_id]["symbols"][symbol_name]["take_profit_orders_info"][level]["order_id"] = None
                        #user_keys[user_id]["symbols"][symbol_name]["take_profit_orders_info"][level]["target_price"] = 0.0
                        #user_keys[user_id]["symbols"][symbol_name]["take_profit_orders_info"][level]["quantity"] = 0.0
                        #user_keys[user_id]["symbols"][symbol_name]["take_profit_orders_info"][level]["side"] = None
                    #else:
                    #    print(f"익절 주문이 이미 활성화되어 있습니다. {symbol_name} {level}레벨의 주문 정보 : {take_profit_orders_info[level]}")
                    #    continue
            else:
                pass
                #print(f"{symbol} current_price : {current_price}, 근접 Upper: {upper_levels} Lower: {lower_levels}")
    except Exception as e:
        print(f"An {symbol} order error on take profit orders: {e}")
        traceback.print_exc()
    update_flag = False  # 실행 후 update_flag를 False로 설정
    last_execution_time = current_time  # 마지막 실행 시간 갱신
    end_timestamp = int(time.time())
    elapsed_time = end_timestamp - current_timestamp
    current_time_str = datetime.fromtimestamp(current_timestamp).strftime('%Y-%m-%d %H:%M:%S')
    print(f"{symbol}의 15분 주기 업데이트가 완료되었습니다. 소요시간 : {elapsed_time}초 현재시간 : {current_time_str}")
    
    
    
    try:
        if adx_4h == -2 and grid_levels['adx_state_4h'].iloc[-2] != -2 and grid_levels['adx_state_4h'].iloc[-3] != -2:
            print(f'{symbol}의 4시간봉 ADX 상태가 -2입니다. 롱포지션을 종료합니다.')
            message = f"{symbol}의 4시간봉 추세가 하락입니다. 숏 매매 위주로 진행합니다."
            position_size = await get_position_size(exchange_name, user_id, symbol)
            try:
                if position_size > 0:
                    #await manager.add_user_message(user_id, message)
                    await add_user_log(user_id, message)
                    await telegram_message.send_telegram_message(f"{symbol}의 4시간봉 추세가 하락입니다. 롱포지을 종료합니다.", exchange_name, debug = True)
                    await asyncio.sleep(random.uniform(0.02, order_buffer))
                    asyncio.create_task(strategy.close(exchange_instance, symbol, qty = max(new_position_size , position_size), message = f'4시간봉 추세가 하락으로 전환됩니다.\n{symbol}그리드 롱포지션을 종료합니다.', action = 'close_long'))
                    level_quantities = {n: 0 for n in range(0, grid_num + 1)}
                    for n in range(0, grid_num + 1):
                        await update_take_profit_orders_info(redis, exchange_name,user_id,symbol_name, n, None, 0.0, 0.0, False, None)
                        #user_keys[user_id]["symbols"][symbol_name]["take_profit_orders_info"][n]["active"] = False
                        #user_keys[user_id]["symbols"][symbol_name]["take_profit_orders_info"][n]["order_id"] = None
                        #user_keys[user_id]["symbols"][symbol_name]["take_profit_orders_info"][n]["target_price"] = 0.0
                        #user_keys[user_id]["symbols"][symbol_name]["take_profit_orders_info"][n]["quantity"] = 0.0
                        #user_keys[user_id]["symbols"][symbol_name]["take_profit_orders_info"][n]["side"] = None
            except Exception as e:
                logging.error(f"An error occurred on closing long ADX Logic: {e}")
            
        if adx_4h == 2 and grid_levels['adx_state_4h'].iloc[-2] != 2 and grid_levels['adx_state_4h'].iloc[-3] != 2:
            print('4시간봉 ADX 상태가 2입니다. 숏포지션을 종료합니다.')
            #global_messages.trading_message.put = f"{symbol}의 4시간봉 추세가 상승입니다. 롱 매매 위주로 진행합니다."
            message = f"{symbol}의 4시간봉 추세가 상승입니다. 롱 매매 위주로 진행합니다."
            #await manager.add_user_message(user_id, message)
            await add_user_log(user_id, message)
            try:
                if position_size < 0:
                    await asyncio.sleep(random.uniform(0.02, order_buffer))
                    asyncio.create_task(strategy.close(exchange_instance, symbol, qty = min(new_position_size, position_size), message = f'4시간봉 추세가 상승으로 전환됩니다.\n{symbol}그리드 숏포지션을 종료합니다.', action = 'close_short'))
                    level_quantities = {n: 0 for n in range(0, grid_num + 1)}
            except Exception as e:
                logging.error(f"An error occurred on closing short ADX Logic: {e}")
            
    except Exception as e:
        print(f"An error occurred on ADX logic: {e}")
        
async def long_logic(exchange_name, user_id, symbol_name, symbol, lower_levels, current_price, grid_levels, order_placed, grid_num,
                     price_precision, max_notional_value, initial_investment, order_quantities, quantity_list,
                     direction, take_profit_orders_info, level_quantities, min_notional, temporally_waiting_long_order,
                     adx_4h, overbought, oversold, order_buffer, exchange_instance, redis, possible_order_id_keys, order_ids, position_size, under_1_grid):
                long_logic_start_time = time.time()
                order_placed = await get_order_placed(exchange_name, user_id, symbol_name, grid_num)
                #print(f"order_placed 확인 : {order_placed}")
                for level in lower_levels:
                    grid_level = int(level[0])
                    price_level = level[1]
                    
                    if (grid_level >= 2) :
                        prev_level = grid_level - 1

                        if grid_level == 2:
                            if current_price > grid_levels[f'grid_level_{prev_level}'].iloc[-1]:
                                under_1_grid = False
                        
                        

                        initial_capital = initial_investment[prev_level]
                        order_quantity = order_quantities[prev_level]
                        #print(f"take_profit_orders_info55", take_profit_orders_info)
                        #print(f"prevlevel 확인 : {prev_level}")
                        #print('type 확인', type(prev_level))
                        #print(f"prevlevel 값 확인 : {prev_level in take_profit_orders_info}")
                        #print(f"take_profit_orders_info[prev_level]['active']", take_profit_orders_info[prev_level]["active"])
                        #print(f"prev_level: {prev_level}")
                        #print(f"take_profit_orders_info keys: {take_profit_orders_info.keys()}") #<<-- 0713에, 계속 key error 나온건, 다른 게 아니라, 이게 str로 되어있었다. 그래서 다시 int로 수정. 확인함. <-- 'dict key로 1,2,3,..로 int로저장됨 0715확인
                        
                            #print(f"An error occurred on checking minimum volatility: {e}")
                        #print(f"minimum_volatility{minimum_volatility} :last_placed_price 확인 : {last_placed_price[grid_level]},🔸 volatility = {abs(float(last_placed_price[grid_level]) - float(current_price)) / float(current_price)}")
                        ###롱 주문 생성 로직 

                        
                        if  int(prev_level) >= 1 and ((str(prev_level) in take_profit_orders_info and (not take_profit_orders_info[str(prev_level)]["active"]))) and (not order_placed[prev_level]) and (price_level < current_price) and (adx_4h != -2 or position_size < 0.0) and (not temporally_waiting_long_order) and not overbought  :
                            okay_to_order = await okay_to_place_order(exchange_name, user_id, symbol_name, price_level, max_notional_value, order_direction = 'long')
                            if (okay_to_order) and (not order_placed[prev_level] and (direction != 'short')) or (position_size < 0 and direction == 'short') and (not await is_price_placed(exchange_name, user_id, symbol_name, prev_level)):
                                #print(f'{symbol} 50')
                                long_level = grid_levels[f'grid_level_{prev_level}'].iloc[-1]
                                if long_level > 100000 or long_level < 0:
                                    print(f"{symbol} : long level : {long_level}, price_level : {price_level}")
                                    continue
                                if long_level < current_price * 0.9:
                                    long_level = (current_price + long_level) * 0.5
                                if exchange_name == 'upbit':
                                    long_level = get_corrected_rounded_price(long_level)
                                else:
                                    long_level = adjust_price_precision(long_level, price_precision)

                                if exchange_name == 'upbit':
                                    order_price_unit = get_order_price_unit_upbit(current_price)
                                    quantity_former = initial_capital / current_price
                                    processing_qty = round_to_upbit_tick_size(quantity_former)
                                    adjusted_quantity = processing_qty
                                elif exchange_name =='okx' :
                                    adjusted_quantity = order_quantities[grid_level-1]
                                    if symbol.startswith("ETH"):
                                        min_quantity = 0.1
                                    elif symbol.startswith("SOL"):
                                        min_quantity = 0.01
                                    elif symbol.startswith("BTC"):
                                        min_quantity = 0.01
                                    else:
                                        min_quantity = 0.1  # 그 외 종목의 최소 수량
                                elif min_notional is not None:
                                    min_quantity = min_notional / long_level
                                    
                                    if level_quantities[prev_level] > 0:
                                        adjusted_quantity = max(level_quantities[prev_level], min_quantity)
                                    else:
                                        adjusted_quantity = max(quantity_list[grid_level-1], min_quantity)
                                else:
                                    if level_quantities[prev_level] > 0:
                                        adjusted_quantity = level_quantities[prev_level]
                                    else:
                                        adjusted_quantity = quantity_list[grid_level-1]
                                try:
                                    print(f'{symbol} 롱 분기 확인! 0101 현재 level : {grid_level} 이전 level : {prev_level} 현재가 : {current_price} long_level : {long_level}, order_placed : {order_placed}')
                                    if not await is_price_placed( exchange_name, user_id, symbol_name, price = long_level, grid_level = prev_level):
                                        if exchange_name == 'bitget':
                                            long_order = await exchange_instance.create_order(
                                                symbol=symbol_name,
                                                type='limit',
                                                side='buy',
                                                amount=adjusted_quantity,
                                                price=long_level,
                                                params={
                                                'contract_type': 'swap',
                                                'position_mode': 'single',
                                                'marginCoin': 'USDT',
                                                }
                                            )
                                        #elif exchange_name == 'bitget_spot':
                                        #    long_order = await exchange_instance.create_order(
                                        #        symbol=symbol_name,
                                        #        type='limit',
                                        #        side='buy',
                                        #        amount=adjusted_quantity,
                                        #        price=long_level
                                        #    )
                                        elif exchange_name == 'okx' or exchange_name == 'okx_spot':
                                            try:
                                                if long_level < 1000000 and long_level > 0:
                                                    if position_size < 0 :
                                                        try:
                                                            long_order = await exchange_instance.create_order(
                                                                symbol=symbol_name,
                                                                type='limit',
                                                                side='buy',
                                                                amount=adjusted_quantity,
                                                                price=long_level,
                                                                params={'reduceOnly': True}
                                                            )
                                                            print(f'{symbol} okx-short direc의 숏 익절 롱주문 12✔︎')
                                                        except Exception as e:
                                                            print(f"Reduce Only error occurred on making long order on okx:(short익절) quantity : {adjusted_quantity} price : {long_level} {e}")
                                                            long_order = None
                                                    else:
                                                        long_order = await exchange_instance.create_order(
                                                            symbol=symbol_name,
                                                            type='limit',
                                                            side='buy',
                                                            amount=adjusted_quantity,
                                                            price=long_level
                                                        )
                                                        #print('okx의 롱주문 13✔︎')
                                                else:
                                                    print(f"long_level : {long_level} {symbol} {adjusted_quantity}")
                                                    continue
                                                    
                                                    #print('okx의 롱주문 14✔︎'
                                                await set_order_placed(exchange_name, user_id, symbol_name, long_level, level_index = prev_level)
                                                
                                            except Exception as e:
                                                if ('margin' in str(e)) or ('Insufficient' in str(e)):
                                                    print(f"{user_id} : Insufficient balance for {symbol_name} at {prev_level} level. Temporally waiting for next opportunity.")
                                                    temporally_waiting_long_order = True
                                                    temporally_waiting_short_order = True
                                                    await asyncio.sleep(2)
                                                    continue
                                                elif "You don't have any positions'" in str(e):
                                                    print(f"{user_id} : You don't have any positions for {symbol_name} at {prev_level} level. Temporally waiting for next opportunity.")
                                                    temporally_waiting_long_order = True
                                                    temporally_waiting_short_order = True
                                                    await asyncio.sleep(3)
                                                    #continue
                                                else:
                                                    if ('margin' in str(e)) or ('Insufficient' in str(e)):
                                                        print(f"{user_id} : Insufficient balance for {symbol_name} at {prev_level} level. Temporally waiting for next opportunity.")
                                                        temporally_waiting_long_order = True
                                                        temporally_waiting_short_order = True
                                                        await asyncio.sleep(3)
                                                        continue
                                                    else:
                                                        if ('margin' in str(e)) or ('Insufficient' in str(e)):
                                                            print(f"{user_id} : Insufficient balance for {symbol_name} at {prev_level} level. Temporally waiting for next opportunity.")
                                                            temporally_waiting_long_order = True
                                                            temporally_waiting_short_order = True
                                                            await asyncio.sleep(3)
                                                            continue
                                                        else:
                                                            print(f"{user_id} :{symbol} level ; {grid_level} An error occurred on making long order on okx:(short익절) quantity : {adjusted_quantity} price : {long_level} {e}") 
                                                            long_order = None
                                                            continue


                                        elif exchange_name == 'upbit':
                                            long_order = await retry_async(strategy.place_order, exchange = exchange_instance, symbol=symbol_name,order_type='limit',side='buy',amount=adjusted_quantity,price=long_level)
                                        else:
                                            long_order = await exchange_instance.create_order(
                                                symbol=symbol_name,
                                                type='limit',
                                                side='buy',
                                                amount=adjusted_quantity,
                                                price=long_level
                                            )
                                            #print('long_order1🔥5')
                                        if long_order is not None:
                                            print(f"{symbol}52")
                                            #print(long_order)
                                            temporally_waiting_long_order = False
                                            for key in possible_order_id_keys:
                                                if 'info' in long_order and key in long_order['info']:
                                                    order_id = long_order['info'][key]
                                                    if exchange_name == 'okx' or exchange_name == 'okx_spot':
                                                        if isinstance(order_id, int) or (isinstance(order_id, str) and order_id.isdigit() and 1 <= len(order_id) <= 20):
                                                            
                                                            break
                                                        else:
                                                            print(f"잘못된 order_id: {order_id}")
                                                    else:
                                                        if isinstance(order_id, int) or (isinstance(order_id, str) and 1 <= len(order_id) <= 60):
                                                            break
                                                        else:
                                                            print(f"잘못된 order_id: {order_id} type: {type(order_id)}")
                                            print(f"{user_id} : Long order placed at {long_level} : {symbol_name} {prev_level}레벨")
                                            order_ids[str(prev_level)] = order_id  # 주문 ID 저장
                                            #print(f"last_placed_price 확인 : {last_placed_price}")
                                            #print(f'grid level이랑 preve레벨 헷갈려서, grid level : {grid_level}, prev_level : {prev_level}')
                                            await add_placed_price(exchange_name, user_id, symbol_name, price=long_level)
                                            await set_order_placed(exchange_name, user_id, symbol_name, long_level, level_index = prev_level)
                                            await asyncio.sleep(random.uniform(0.05, order_buffer+0.5))
                                            asyncio.create_task(check_order_status(exchange_instance, exchange_name, order_ids[str(prev_level)], symbol_name, grid_levels, adjusted_quantity, price_precision, False, order_placed, prev_level, level_quantities, take_profit_orders_info, grid_num, direction, max_notional_value, user_id))
                                except Exception as e:
                                    error_message = str(e)
                                    if "insufficient funds" in error_message.lower() or "금액(KRW)이 부족합니다" in error_message or "Insufficient balance" in error_message or "Insufficient margin" in error_message:
                                        temporally_waiting_long_order = True
                                        print(f"Long order failed at {long_level} : Insufficient funds for {symbol_name} at {prev_level} level. Temporally waiting for next opportunity.")
                                    else:
                                        # 다른 예외 처리
                                        print(f"Failed to place order due to error: {error_message}")
                                        print(traceback.format_exc())
                                        
                                        temporally_waiting_long_order = True
                                        await asyncio.sleep(3)  # 실패 후 잠시 대기
                        level_end_time = time.time()
                        level_elapsed_time = level_end_time - long_logic_start_time
                        if level_elapsed_time > 1:
                            print(f"{symbol}의 {prev_level}레벨 롱주문 로직 완료{long_level}. 소요시간 : {round(level_elapsed_time,2)}초")
                        else:
                            current_time = int(time.time())
                            current_minute = current_time // 60 % 60  # 현재 분 계산
                            current_second = current_time % 60  # 현재 초 계산
                            if  current_minute % 7 == 0 and current_second < 2:
                                if order_placed[prev_level] :
                                    print(f"{user_id} : {symbol}의 {prev_level}레벨 롱 주문이 이미 있습니다 time : {current_minute}.")
                                elif adx_4h == -2 :
                                    print(f"{symbol}의 ADX == -2여서 롱 주문 불가능 상황")
                                else:
                                    print(f"롱 주문 불가능한 이유 확인. {symbol} order_placed : {order_placed[prev_level]}, price_level : {price_level}, current_price : {current_price}, adx_4h : {adx_4h}, overbought : {overbought}")
                    elif grid_level == 1 or grid_level == 0:
   
                        if under_1_grid == False:
                            under_1_grid = True
                            message = f"☑️{symbol}의 그리드 최하단에 도달했습니다."
                            position_size = await get_position_size(exchange_name, user_id, symbol)

                            if position_size < 0 and (exchange_name == 'binance' or exchange_name == 'okx' or exchange_name == 'bitget'):
                                #await manager.add_user_message(user_id, message)
                                await add_user_log(user_id, message)
                                print(message)
                                try:
                                    await strategy.close(exchange_instance, symbol_name, qty = max(abs(position_size), position_size), message = message, action = 'close_short')
                                    level_quantities = {n: 0 for n in range(0, grid_num + 1)}
                                    print(f"최하단 숏 종료. {symbol_name} {grid_level}레벨")
                                    #asyncio.create_task(telegram_message.send_telegram_message(message, exchange_instance))
                                except Exception as e:
                                    print(f"최하단 숏 종료 로직 재확인 필요: {e}")
                        else:
                            if position_size < 0 and (exchange_name == 'binance' or exchange_name == 'okx' or exchange_name == 'bitget' or exchange_name == 'bybit'):

                                try:
                                    okay_to_order = await okay_to_place_order(exchange_name, user_id, symbol_name, price_level, max_notional_value, order_direction='long')
                                    prev_level = grid_level - 1
                                    #print('grid level 0가 있는지 확인. ', grid_levels[f'grid_level_{prev_level}'].iloc[-1])
                                    order_quantity = order_quantities[grid_level-1]
                                    if (okay_to_order) and (not take_profit_orders_info[str(prev_level)]["active"]) and (not order_placed[int(grid_level)] and price_level < current_price) and adx_4h != 2 and (not temporally_waiting_long_order) and not overbought and  (not await is_order_placed(exchange_name, user_id, symbol, level)):
                                        if (not order_placed[int(prev_level)]) and (direction == 'short'):
                                            long_level = float(grid_levels[f'grid_level_0'].iloc[-1])
                                            if long_level < current_price * 0.9:
                                                long_level = (current_price + long_level) * 0.5
                                            long_level = adjust_price_precision(long_level, price_precision)
                                            print(f'{symbol} 분기 확인! 0102 ')
                                            if not await is_price_placed( exchange_name, user_id, symbol_name, price = long_level, grid_level = prev_level):
                                                if exchange_name =='okx' :
                                                    adjusted_quantity = order_quantities[grid_level-1]
                                                    if symbol.startswith("ETH"):
                                                        min_quantity = 0.1
                                                        adjusted_quantity = max(adjusted_quantity, min_quantity)
                                                    elif symbol.startswith("SOL"):
                                                        min_quantity = 0.01
                                                        adjusted_quantity = max(adjusted_quantity, min_quantity)
                                                    elif symbol.startswith("BTC"):
                                                        min_quantity = 0.01
                                                        adjusted_quantity = max(adjusted_quantity, min_quantity)
                                                    else:
                                                        min_quantity = 0.1  # 그 외 종목의 최소 수량
                                                elif min_notional is not None:
                                                    min_quantity = min_notional / long_level
                                                    if level_quantities[prev_level] > 0:
                                                        adjusted_quantity = max(level_quantities[prev_level], min_quantity)
                                                    else:
                                                        adjusted_quantity = max(quantity_list[grid_level-1], min_quantity)
                                                else:
                                                    if level_quantities[prev_level] > 0:
                                                        adjusted_quantity = level_quantities[prev_level]
                                                    else:
                                                        adjusted_quantity = quantity_list[grid_level-1]
                                                try:
                                                    if exchange_name == 'bitget':
                                                        long_order = await exchange_instance.create_order(
                                                            symbol=symbol_name,
                                                            type='limit',
                                                            side='buy',
                                                            amount=adjusted_quantity,
                                                            price=long_level,
                                                            params={
                                                            'contract_type': 'swap',
                                                            'position_mode': 'single',
                                                            'marginCoin': 'USDT',
                                                            }
                                                        )
                                                    elif exchange_name == 'okx' :

                                                        if direction == 'short' and position_size < 0:
                                                            try:
                                                                long_order = await exchange_instance.create_order(
                                                                    symbol=symbol_name,
                                                                    type='limit',
                                                                    side='buy',
                                                                    amount=adjusted_quantity,
                                                                    price=long_level,
                                                                    params={'reduceOnly': True}
                                                                )
                                                                print(f'{symbol} Long Order(short close01✔︎)')
                                                            except Exception as e:
                                                                
                                                                print(f"{user_id} : An error occurred on making long order on okx for reduce only: {e}")
                                                                long_order = None
                                                                continue
                                                                #raise e
                                                        else:
                                                            long_order = await exchange_instance.create_order(
                                                                symbol=symbol_name,
                                                                type='limit',
                                                                side='buy',
                                                                amount=adjusted_quantity,
                                                                price=long_level
                                                            )
                                                            print(f'{symbol} long_order16')

                                                    else:
                                                        long_order = await exchange_instance.create_order(
                                                            symbol=symbol_name,
                                                            type='limit',
                                                            side='buy',
                                                            amount=adjusted_quantity,
                                                            price=long_level
                                                        )
                                                        print(f'{symbol} long_order02')
                                                    if long_order is not None:
                                                        temporally_waiting_long_order = False
                                                        for key in possible_order_id_keys:
                                                            if 'info' in long_order and key in long_order['info']:
                                                                order_id = long_order['info'][key]
                                                                if exchange_name == 'okx' or exchange_name == 'okx_spot':
                                                                    if isinstance(order_id, int) or (isinstance(order_id, str) and order_id.isdigit() and 1 <= len(order_id) <= 25):
                                                                        break
                                                                    else:
                                                                        print(f"잘못된 order_id: {order_id}")
                                                                else:
                                                                    if isinstance(order_id, int) or (isinstance(order_id, str) and 1 <= len(order_id) <= 60):
                                                                        break
                                                                    else:
                                                                        print(f"잘못된 order_id: {order_id} type: {type(order_id)}")
                                                        #print(f"Long order placed at {long_level} : {order_id}, {symbol_name} {prev_level}레벨")
                                                        order_ids[str(grid_level)] = order_id  # 주문 ID 저장
                                                        order_placed[int(grid_level)] = True
                                                        print(f"타입 체킹. grid_level type : {type(grid_level)}")
                                                        await set_order_placed(exchange_name, user_id, symbol_name, long_level, level_index = prev_level)
                                                        asyncio.create_task(check_order_status(exchange_instance, exchange_name, order_ids[str(grid_level)], symbol_name, grid_levels, adjusted_quantity, price_precision, False, order_placed, prev_level, level_quantities, take_profit_orders_info, grid_num, direction,max_notional_value, user_id))
                                                except Exception as e:
                                                    error_message = str(e)
                                                    if "insufficient funds" in error_message.lower() or "금액(KRW)이 부족합니다" in error_message or "Insufficient balance" in error_message or "Insufficient margin" in error_message:
                                                        temporally_waiting_long_order = True
                                                        print(f"Long order failed at {long_level} : Insufficient funds for {symbol_name} at {prev_level} level. Temporally waiting for next opportunity.")
                                                    else:
                                                        # 다른 예외 처리
                                                        print(f"Failed to place order due to error: {error_message}")

                                                        temporally_waiting_long_order = True
                                                        await asyncio.sleep(3)  # 실패 후 잠시 대기
                                            else:
                                                print(f"{symbol} : {long_level}이 이미 주문되어 있습니다(01).")

                                except Exception as e:
                                    print(f"{user_id} : {symbol} An error occurred on making short tp order: {e}") #<-- 여기서 계속, -1이라는 오류 발생.
                                    print(traceback.format_exc()) 

                    else:
                        print(f'{user_id} {symbol} 정의해두지 않은 상황. 디버깅.')
                        #await telegram_message.send_telegram_message('정의해두지 않은 상황. 디버깅.', exchange_instance, debug = True)
                return order_placed, temporally_waiting_long_order, under_1_grid

async def short_logic(exchange_name, user_id, symbol_name, symbol, upper_levels, current_price, grid_levels, order_placed, grid_num,
                     price_precision, max_notional_value, initial_investment, order_quantities, quantity_list, new_position_size,
                     direction, take_profit_orders_info, level_quantities, min_notional, temporally_waiting_short_order,
                     adx_4h, overbought, oversold, order_buffer, exchange_instance, redis, possible_order_id_keys, order_ids, position_size, over_20_grid):
    order_placed = await get_order_placed(exchange_name, user_id, symbol_name, grid_num)
    if (direction == 'long' and position_size > 0) or (direction != 'long') :
        for level in upper_levels:
            try:
                grid_level = level[0]
                price_level = level[1]
                position_size = await get_position_size(exchange_name, user_id, symbol)
                #print(order_placed)
                #print(grid_level)
                #print(f"{symbol}의 숏 주문로직 시작. {level}")
                current_time = int(time.time())
                current_minute = current_time // 60 % 60  # 현재 분 계산
                current_second = current_time % 60  # 현재 초 계산
                if price_level < 1000000 and (not order_placed.get(int(grid_level), False) and price_level > current_price)  and (adx_4h != 2 or position_size > 0.0):
                    await asyncio.sleep(random.uniform(0.05, order_buffer+0.1))
                    okay_to_order = await okay_to_place_order(exchange_name, user_id, symbol, price_level, max_notional_value, order_direction = 'short')
                    if (okay_to_order) and (grid_level <= grid_num and direction != 'long') or (grid_level <= grid_num and direction == 'long' and position_size > 0) and temporally_waiting_short_order == False and (not await is_order_placed(exchange_name, user_id, symbol, grid_level)):
                        try:
                            if (int(grid_level) < int(grid_num)) :
                                over_20_grid = False
                                next_level = grid_level + 1
                                if next_level > grid_num:
                                    next_level = grid_num
                                if ((not order_placed.get(next_level, False) and ((direction != 'long')) or (position_size > 0 and direction == 'long'))) and (not await is_order_placed(exchange_name, user_id, symbol, next_level)) :
                                    short_level = grid_levels[f'grid_level_{next_level}'].iloc[-1]
                                    if short_level > 100000:
                                        print(f"{symbol} : short level : {short_level}, price_level : {price_level}")
                                        continue
                                
                                    if exchange_name == 'upbit':
                                        short_level = get_corrected_rounded_price(short_level)
                                    else:
                                        short_level = adjust_price_precision(short_level, price_precision)
                                        #print(f"{symbol} short_level : {short_level}")
                                    if short_level > current_price * 1.1:
                                        short_level = (current_price + short_level) * 0.5
                                    #print(f'{symbol} 숏 분기 확인! 0104. 현재 level : {grid_level} 주문 걸 next_level : {next_level}')
                                    if (not await is_price_placed( exchange_name, user_id, symbol_name, price = short_level, grid_level = next_level )):
                                        if exchange_name == 'okx' :
                                            adjusted_quantity = order_quantities[grid_level-1]
                                                # 종목별 최소 수량 설정
                                            if symbol.startswith("ETH"):
                                                min_quantity = 0.1
                                            elif symbol.startswith("SOL"):
                                                min_quantity = 0.01
                                            elif symbol.startswith("BTC"):
                                                min_quantity = 0.01
                                            else:
                                                min_quantity = 0.1  # 그 외 종목의 최소 수량
                                        elif min_notional is not None:
                                            min_quantity = min_notional / short_level
                                            if symbol.startswith("ETH"):
                                                min_quantity = 0.1
                                            elif symbol.startswith("SOL"):
                                                min_quantity = 0.01
                                            elif symbol.startswith("BTC"):
                                                min_quantity = 0.01
                                            else:
                                                min_quantity = 0.1  # 그 외 종목의 최소 수량
                                            if level_quantities[next_level] > 0:
                                                adjusted_quantity = max(level_quantities[next_level], min_quantity)
                                            else:
                                                adjusted_quantity = max(quantity_list[grid_level-1], min_quantity)
                                        else:
                                            if level_quantities[next_level] > 0:
                                                adjusted_quantity = level_quantities[next_level]
                                            else:
                                                adjusted_quantity = quantity_list[grid_level-1]
                                        if exchange_name == 'binance' :
                                            short_order = await exchange_instance.create_order(
                                                symbol=symbol,
                                                type='limit',
                                                side='sell',
                                                amount=adjusted_quantity,
                                                price=short_level
                                            )
                                        elif exchange_name == 'binance_spot' and new_position_size > 0:
                                            short_order = await exchange_instance.create_order(
                                                symbol=symbol,
                                                type='limit',
                                                side='sell',
                                                amount=adjusted_quantity,
                                                price=short_level
                                            )
                                        elif exchange_name == 'okx_spot' and new_position_size > 0:
                                            short_order = await exchange_instance.create_order(
                                                symbol=symbol,
                                                type='limit',
                                                side='sell',
                                                amount=adjusted_quantity,
                                                price=short_level
                                            )
                                        elif exchange_name == 'okx' :
                                            if symbol.startswith("ETH"):
                                                min_quantity = 0.1
                                            elif symbol.startswith("SOL"):
                                                min_quantity = 0.01
                                            elif symbol.startswith("BTC"):
                                                min_quantity = 0.01
                                            try:
                                                if temporally_waiting_short_order == False:
                                                    if position_size > 0.0:
                                                        short_order = await retry_async(create_short_orders, exchange_instance, symbol, short_level, adjusted_quantity, min_quantity, user_id ,reduce_only = True)
                                                        order_placed[next_level] = True
                                                        await set_order_placed(exchange_name, user_id, symbol_name, short_level, level_index = next_level)
                                                    else:
                                                        try:
                                                            short_order =await retry_async(create_short_orders, exchange_instance, symbol, short_level, adjusted_quantity, min_quantity, user_id)
                                                            order_placed[next_level] = True
                                                            await set_order_placed(exchange_name, user_id, symbol_name, short_level, level_index = next_level)
                                                        except Exception as e:
                                                            print(f"{user_id} : An error occurred on making short order202:2 {e}")
                                                            if ('margin' in str(e)) or ('insufficient' in str(e)):
                                                                short_order = None
                                                                temporally_waiting_short_order = True
                                                                temporally_waiting_long_order = True
                                                                
                                                            else:
                                                                print(f"{user_id} : An error occurred on making short order: {e}")       
                                                                short_order = None 
                                            except Exception as e:
                                                if ('margin' in str(e)) or ('insufficient' in str(e)):
                                                    print(f"{user_id} : An error occurred on making short order: {e}")
                                                    short_order = None
                                                    temporally_waiting_short_order = True
                                                    temporally_waiting_long_order = True
                                                else:
            
                                                    print(f"{user_id} : An error occurred on making short order: {e}")       
                                                    short_order = None 
                                            
                                        elif exchange_name == 'bitget':
                                            try:
                                                short_order = await exchange_instance.create_order(
                                                    symbol=symbol_name,
                                                    type='limit',
                                                    side='sell',
                                                    amount=adjusted_quantity,
                                                    price=short_level,
                                                    params={
                                                    'contract_type': 'swap',
                                                    'position_mode': 'single',
                                                    'marginCoin': 'USDT',
                                                }
                                                )
                                            except Exception as e:
                                                print(f"An error occurred7: {e}")
                                        elif exchange_name == 'bitget_spot' and new_position_size > 0:
                                            short_order = await exchange_instance.create_order(
                                                symbol=symbol_name,
                                                type='limit',
                                                side='sell',
                                                amount=adjusted_quantity,
                                                price=short_level
                                            )
                                            
                                        if short_order is not None:
                                            for key in possible_order_id_keys:
                                                if 'info' in short_order and key in short_order['info']:
                                                    order_id = short_order['info'][key]
                                                    break
                                            temporally_waiting_short_order = False
                                            order_ids[str(grid_level)] = order_id  # 주문 ID 저장
                                            print(f"{user_id} : Short order placed at {short_level} : , {symbol_name} {grid_level}레벨")
                                            try:
                                                await asyncio.sleep(random.uniform(0.05, order_buffer+0.1))
                                                asyncio.create_task(check_order_status(exchange_instance, exchange_name, order_ids[str(grid_level)], symbol_name, grid_levels, adjusted_quantity, price_precision, True, order_placed, next_level, level_quantities, take_profit_orders_info, grid_num, direction,max_notional_value, user_id))
                                                order_placed[grid_level] = True
                                                #last_placed_price[grid_level] = short_level
                                                await add_placed_price(exchange_name, user_id, symbol_name, price=short_level)
                                                await set_order_placed(exchange_name, user_id, symbol_name, short_level, level_index = grid_level)
                                            except Exception as e:
                                                print(f"An error occurred128: {e}")
                                #else:
                                #    print(f"{symbol} : {grid_level}레벨의 주문이 이미 있습니다(short logic).")
                        except Exception as e:
                            print(f"{user_id} : An error occurred on making short order: {e}")
                            print(traceback.format_exc())
                    else:
                        try:

                            if over_20_grid == False and grid_level >= grid_num:
                                print(f"grid_level : {grid_level}")
                                message = f"☑️{symbol}의 그리드 최상단에 도달했습니다."
                                if current_minute % 60 == 0:
                                    #global_messages.trading_message.put(message)
                                    #await manager.add_user_message(user_id, message)
                                    await add_user_log(user_id, message)
                                over_20_grid = True
                                position_size = await get_position_size(exchange_name, user_id, symbol)
                                print(f"{user_id} : {symbol} postiion_size: {get_position_size}")
                                if position_size > 0:
                                    print(message)
                                    try:
                                        await strategy.close(exchange_instance, symbol_name, qty = max(new_position_size ,position_size), message = message, action = 'close_long')
                                        level_quantities = {n: 0 for n in range(0, grid_num + 1)}
                                        for n in range(0, grid_num + 1):
                                            take_profit_orders_info[str(level)].update({
                                                        'order_id': None,
                                                        'target_price': 0.0,
                                                        'quantity': 0.0,
                                                        'active': False
                                                    })
                                            await update_take_profit_orders_info(redis, exchange_name,user_id,symbol_name = symbol_name, level = n, order_id = None, new_price = 0.0, quantity=0.0, active =  False, side = None)
                                            #user_keys[user_id]["symbols"][symbol_name]["take_profit_orders_info"][n]["order_id"] = None
                                            #user_keys[user_id]["symbols"][symbol_name]["take_profit_orders_info"][n]["active"] = False
                                            #user_keys[user_id]["symbols"][symbol_name]["take_profit_orders_info"][n]["target_price"] = 0.0
                                            #user_keys[user_id]["symbols"][symbol_name]["take_profit_orders_info"][n]["quantity"] = 0.0
                                            #user_keys[user_id]["symbols"][symbol_name]["take_profit_orders_info"][n]["side"] = None
                                            
                                        #asyncio.create_task(telegram_message.send_telegram_message(message, exchange_instance))
                                    except Exception as e:
                                        print(f"An error occurred on Closing whole long: {e}")
                                else: 
                                    temporally_waiting_short_order = True
                        except Exception as e:
                            print(f"{user_id} : An error occurred on making short order2: {e}")
                else:
                    if current_minute % 7 == 0 and current_second < 2:
                        
                        if order_placed.get(int(grid_level), True):
                            print(f"{symbol}의 {grid_level}레벨 주문이 이미 있습니다. {datetime.fromtimestamp(current_time).strftime('%Y-%m-%d %H:%M:')} ")
                        elif adx_4h == 2 :
                            print(f"{level} : {symbol}의 ADX == 2여서 숏 주문 불가능 상황 time : {datetime.fromtimestamp(current_time).strftime('%Y-%m-%d %H:%M:')} ")
                        else:
                            print(f'{level} : {symbol} 숏 주문 불가능 상황 .이유 확인. order_placed : {order_placed[int(grid_level)]}, price_level : {price_level}, current_price : {current_price}, adx_4h : {adx_4h}, oversold : {oversold}')
            except Exception as e:
                print(f"{user_id} :{symbol} An error occurred on making totally short {e}")
                print(traceback.format_exc())
    return order_placed, temporally_waiting_short_order, over_20_grid

#================================================================================================
#                              Grid Trading Strategy
#================================================================================================
#async def update_is_running(redis, user_key):
#    try:
#        is_running = await redis.hget(user_key, 'is_running')
#        is_running = is_running.decode('utf-8') if isinstance(is_running, bytes) else is_running
#        return bool(int(is_running or '0'))
#    except Exception as e:
#        print(f"Error updating is_running status: {e}")
#        return False

            
async def fetch_order_with_retry(exchange_instance, order_id, symbol, max_retries=3):
    for attempt in range(max_retries):
        try:
            return await exchange_instance.fetch_order(order_id, symbol)
        except Exception as e:
            if 'Order does not exist' in str(e):
                return {'status': 'closed'}
            if attempt == max_retries - 1:
                raise
            print(f"Fetch order attempt {attempt + 1} failed: {e}")
            await asyncio.sleep(5)

async def check_order_status(exchange_instance,exchange_name, order_id, symbol, grid_levels, adjusted_quantity, price_precision, is_short_order, order_placed, level_index, level_quantities, take_profit_orders_info, grid_num, direction, max_notional_value, user_id):
    global user_keys
    try:
        redis = await get_redis_connection()
        user_key = f'{exchange_name}:user:{user_id}'
        possible_order_id_keys = ['order_id', 'uuid', 'orderId', 'ordId', 'id']
        is_running = await redis.hget(user_key, 'is_running')
        is_running = is_running.decode('utf-8') if isinstance(is_running, bytes) else is_running
        is_running = bool(int(is_running or '0'))
        if not is_running:
            return
    except Exception as e:
        print(f"An error occurred:507 {e}")
        print(traceback.format_exc())
        return
    try:
        while is_running:
            current_time = datetime.now()
            minutes = current_time.minute
            seconds = current_time.second
            # 15분 단위 시간 확인 (14분 55초, 29분 55초, 44분 55초, 59분 55초에 종료)
            if (minutes in [14, 29, 44, 59] and seconds >= 55) or (minutes == 59 and seconds >= 55):
                #print(f"{symbol} 시간 기준 도달 - 함수 종료")
                break
            try:
                retry_count = 0
                await asyncio.sleep(random.uniform(0.5, 2.5))
                fetched_order = await fetch_order_with_retry(exchange_instance, order_id, symbol)
            except Exception as e:
                if 'Order does not exists' in str(e):
                    print(f"Order does not exist: {order_id}")
                    break
                print(f"{user_id} An error occurred4: {e}")
                await log_exception(e)
                break
            if fetched_order['status'] == 'closed':
                filled_quantity = fetched_order.get('filled', adjusted_quantity)  # 'filled' 키가 없는 경우 기본값 0
                level_quantities[level_index] = round(adjusted_quantity,4 )
                print(f"f 체결. {level_quantities[level_index]}")
                trading_direction = '🔴 숏' if is_short_order else '🟢 롱'
                message = f"<{symbol} :{level_index}의 {trading_direction} 주문 체결되었습니다.>\n 수량 : {level_quantities[level_index]} | 가격 : {fetched_order['price']} | 시간 : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                asyncio.create_task(telegram_message.send_telegram_message(message, exchange_name, user_id))
                #await manager.add_user_message(user_id, message)
                await add_user_log(user_id, message)
                print(f"{user_id} : <{symbol} :{level_index}의  {trading_direction} 주문 체결되었습니다.>\n 수량 : {level_quantities[level_index]} | 가격 : {fetched_order['price']} | 시간 : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                current_price = fetched_order['price']
                # 마지막 진입 시간 기록
                await redis_database.set_trading_volume(exchange_name, user_id, symbol, filled_quantity)
                symbol_key = f'{user_key}:symbol:{symbol}'
                user_keys[user_id]["symbols"][symbol]["last_entry_time"] = datetime.now()
                user_keys[user_id]["symbols"][symbol]["last_entry_size"] = filled_quantity
                # 데이터 읽기
                user_data = await redis.hgetall(user_key)
                symbol_data = await redis.hgetall(symbol_key)
                symbol_data['last_entry_time'] = datetime.now()
                symbol_data['last_entry_size'] = filled_quantity
                grid_count = -1 if is_short_order else 1
                await update_active_grid(redis, exchange_name, user_id, symbol, level_index, fetched_order['price'], level_quantities[level_index], execution_time = datetime.now(),grid_count = grid_count, pnl = None)
                await update_take_profit_orders_info(redis, exchange_name, user_id, symbol, level = level_index, order_id=  order_id, new_price = fetched_order['price'], quantity = level_quantities[level_index], active = True, side = 'short' if is_short_order else 'long')
                if is_short_order:
                    take_profit_level = max(min(current_price * 0.993, grid_levels[f'grid_level_{level_index - 1}'].iloc[-1]), current_price * 0.93) #<-- 숏 주문이 익절될 곳. 현재의 level_index보다 한 칸 낮은 곳. 그러나 최소 0.7%는 떨어져야함.
                    #print(f"Take profit level: {take_profit_level}")
                    tp_side = 'buy'
                    print(f'{user_id} : Short 체결. {take_profit_level}에 새로운 tpside:{tp_side} 주문 생성')
                    if level_index < grid_num:
                        new_order_level = max(grid_levels[f'grid_level_{level_index + 1}'].iloc[-1],current_price*1.005) #<-- 새로운 주문이 걸릴 곳. 현재의 level_index보다 한 칸 높은 곳.그러나 최소 0.5%는 올라가야함.
                        print(f"New order level: {new_order_level}")
                        new_order_side = 'sell' #<-- 새로운 주문이 걸릴 side(숏 주문이 추가로 걸릴 side)
                        if direction == 'long':
                            new_order_side = None
                        new_order_quantity = level_quantities[level_index] 
                        #print(f"새로 진입할 물량 :{level_quantities[level_index]}")
                    else:
                        new_order_level = None
                        new_order_side = None
                        new_order_quantity = 0.0
                        print('최상단 도달. 따라서 새로운 주문은 들어가지 않음')
                else:
                    #print('Long 익절 + 새로운 order')
                    take_profit_level = min(max(current_price*1.004, grid_levels[f'grid_level_{level_index + 1}'].iloc[-1]), current_price*1.08) #<-- 롱 주문이 익절될 곳. 현재의 level_index보다 한 칸 높은 곳. 그러나 최대 8%가 한계. 그리고 최소 0.5%는 떨어져야.
                    #print(f"Take profit level: {take_profit_level}")
                    tp_side = 'sell'
                    print(f"{user_id} : Long 체결. {take_profit_level}에 새로운 tpside:{tp_side} 주문 생성")
                    if level_index > 1:
                        new_order_level = min(grid_levels[f'grid_level_{level_index - 1}'].iloc[-1], current_price*0.995) #새로 롱주문이 들어갈 곳. 현재의 level_index보다 한 칸 낮은 곳. 그러나,최소 0.5%는 떨어져야함.
                        #print(f"New order level: {new_order_level}")
                        new_order_side = 'buy' #새로운 주문이 들어갈 side(롱 주문이 추가로 들어갈 side)
                        if direction == 'short':
                            new_order_side = None
                        new_order_quantity = level_quantities[level_index] #새로운 주문이 들어갈 물량
                        #print(f"체결물량 (익절 대상 물량):{level_quantities[level_index]}")
                    else:
                        new_order_level = None
                        new_order_side = None
                        new_order_quantity = 0.0
                        print('최하단 도달. 따라서 새로운 주문은 들어가지 않음')

                if exchange_instance.id.lower() == 'upbit':
                    take_profit_level = get_corrected_rounded_price(take_profit_level)
                else:
                    take_profit_level = adjust_price_precision(take_profit_level, price_precision)
                #print(f"Take profit level: {take_profit_level}")

                ##익절주문##
                await asyncio.sleep(0.5)
                if level_index > 1 and level_index < grid_num:
                    #⭐️여기서 중복주문이 많이 발생한다. 해결방법은, 현재 오픈오더를 확인하고 거는 방법이지만, API제한때문에 그렇게 할 수는 없다. 만약 중복주문이 발생한다면 이 곳을 확인하기. 0721 1525
                    is_okay_to_place = await okay_to_place_order(exchange_name, user_id, symbol, take_profit_level, max_notional_value, order_direction = tp_side)
                    if is_okay_to_place :  #<-- 여기, #direction != 'long-short': <-- 원래, 여기 익절주문 거는 것에 있어서, direction이 long-short은 걸지 않도록 했었는데, 그랬더니 익절주문이 안나가고 active가 False가 되고 있었다. 0721 1525
                        if exchange_instance.id.lower() == 'upbit':
                            tp_order = await retry_async(strategy.place_order, exchange_instance, symbol, order_type='limit',side='sell', amount = level_quantities[level_index], price = take_profit_level)
                            adjusted_quantity = level_quantities[level_index]
                        elif exchange_instance.id.lower() == 'bitget' and exchange_name == 'bitget':
                            tp_order = await exchange_instance.create_order(
                                symbol=symbol,
                                type='limit',
                                side=tp_side,
                                amount=adjusted_quantity,
                                price=take_profit_level,
                                params={
                                    'contract_type': 'swap',
                                    'position_mode': 'single',
                                    'marginCoin': 'USDT'
                                }
                                )
                        #elif exchange_instance.id.lower() == 'bitget' and exchange_name == 'bitget_spot':
                        #    tp_order = await exchange_instance.create_order(
                        #        symbol=symbol,
                        #        type='limit',
                        #        side='sell',
                        #        amount=min(new_order_quantity, adjusted_quantity),
                        #        price=take_profit_level,
                        #        )
                        elif exchange_instance.id.lower() == 'okx' and exchange_name == 'okx':
                            tp_order = await exchange_instance.create_order(
                                symbol=symbol,
                                type='limit',
                                side=tp_side, #<-- 원래, tp_side였는데, reduce 방향을 바꾸라고 오류가 나와서, new_order_side로 변경함.(06.01) <-- 06.19 TP side가 맞다.
                                amount=level_quantities[level_index],
                                price=take_profit_level,
                                params={'reduceOnly': True} #<-- reduce only를 지우는 이유는, 예를들어, 롱을 갖고 있고 숏이 잡혔는데(즉 롱 익절), reduce only로 하면, 또 롱이 잡힌다. 그래서 reduce only를 빼는게 맞다.
                                                            )                                #<--하지만, 추가주문이 아니라 익절주문이잖아? 그러니까True가 맞지.
                            #print('tp_order03')
                        elif exchange_instance.id.lower() == 'okx' and exchange_name == 'okx_spot':
                            tp_order = await exchange_instance.create_order(
                                symbol=symbol,
                                type='limit',
                                side='sell',
                                amount=level_quantities[level_index],
                                price=take_profit_level,
                                params={'reduceOnly': True}
                                )
                        elif exchange_name == 'binance_spot':
                            tp_order = await exchange_instance.create_order(
                                symbol=symbol,
                                type='limit',
                                side='sell',
                                amount=min(adjusted_quantity, new_order_quantity),
                                price=take_profit_level,
                                )
                        else:
                            tp_order = await exchange_instance.create_order(
                                symbol=symbol,
                                type='limit',
                                side=tp_side, #<-- 원래, tp_side였는데, reduce 방향을 바꾸라고 오류가 나와서, new_order_side로 변경함.(06.01) #<-- 0619 tp side가 맞으므로 다시 수정
                                amount=level_quantities[level_index],
                                price=take_profit_level,
                                params={'reduceOnly': True}  #if is_short_order else {} < -- ??? 이건 왜 롱오더에 대해선 적용을 안한거지
                            )
                            #print('tp_order04')
                            #print(f"Take profit order placed at {take_profit_level}")
                        # 익절 주문 정보 업데이트
                        for key in possible_order_id_keys:
                            if 'info' in tp_order and key in tp_order['info']:
                                order_id = tp_order['info'][key]
                                if exchange_name == 'okx' or exchange_name == 'okx_spot':
                                    if isinstance(order_id, int) or (isinstance(order_id, str) and order_id.isdigit() and 1 <= len(order_id) <= 20):
                                        break
                                    else:
                                        print(f"{user_id} : 잘못된 order_id: {order_id}")
                                else:
                                    if isinstance(order_id, int) or (isinstance(order_id, str)  and 1 <= len(order_id) <= 60):
                                        break
                                    else:
                                        print(f"{user_id} : 잘못된 order_id: {order_id}. type : {type(order_id)}")
                        if tp_order is not None:
                            level_index = level_index + 1 if not is_short_order else level_index - 1
                            take_profit_orders_info[str(level_index)] = {
                                "order_id": order_id, 
                                "quantity": adjusted_quantity, 
                                "target_price": take_profit_level, 
                                "active": True,
                                "side": tp_side
                            }
                            print(f"{user_id} : 익절 주문 추가. {take_profit_level}(level : {level_index}에 새로운 주문 생성. order_quantity : {adjusted_quantity})")
                        try:
                            await add_placed_price(exchange_name, user_id, symbol, take_profit_level)
                            await set_order_placed(exchange_name, user_id, symbol, take_profit_level, level_index=level_index)
                            grid_count = -1 if is_short_order else 1
                            

                        except Exception as e:
                            print(f" {user_id} : An error occurred10: {e}")
                    else: #<-- 주문을 걸어야하지만, 주문을 걸 수 없는 경우(거기에 이미 주문이 있는 경우)
                        try:
                            print(f"이미 그 자리에 주문이 걸려있기에, 따로 익절주문을 걸지는 않음.")
                        except Exception as e:
                            print(f" {user_id} : An error occurred11: {e}")
                else: #<-- level index가 1이거나 grid num인 경우
                    position_size = await get_position_size(exchange_name, user_id, symbol)
                    if level_index == 1 or level_index == grid_num:
                        if level_index == grid_num:
                            tp_price = grid_levels[f'grid_level_{level_index}'].iloc[-1]*1.005
                        else:
                            tp_price = grid_levels[f'grid_level_{level_index}'].iloc[-1]*0.995 
                        if exchange_instance.id.lower() == 'upbit':
                            tp_order = await retry_async(strategy.place_order, exchange_instance, symbol, order_type='limit',side='sell', amount = level_quantities, price = tp_price)
                            adjusted_quantity = level_quantities
                        elif exchange_instance.id.lower() == 'okx' and exchange_name == 'okx':
                            tp_order = await exchange_instance.create_order(
                                symbol=symbol,
                                type='limit',
                                side=tp_side, #<-- 원래, tp_side였는데, reduce 방향을 바꾸라고 오류가 나와서, new_order_side로 변경함.(06.01) <-- 06.19 TP side가 맞다.
                                amount=min(position_size, new_order_quantity),
                                price=tp_price,
                                params={'reduceOnly': True}
                                )
                            #print('tp_order05')
                        elif exchange_instance.id.lower() == 'okx' and exchange_name == 'okx_spot':
                            tp_order = await exchange_instance.create_order(
                                symbol=symbol,
                                type='limit',
                                side='sell',
                                amount=level_quantities[level_index],
                                price=take_profit_level,
                                )
                        elif exchange_name == 'binance_spot':
                            tp_order = await exchange_instance.create_order(
                                symbol=symbol,
                                type='limit',
                                side='sell',
                                amount=min(adjusted_quantity, new_order_quantity),
                                price=tp_price,
                                )
                        else:
                            tp_order = await exchange_instance.create_order(
                                symbol=symbol,
                                type='limit',
                                side=tp_side, #<-- 원래, tp_side였는데, reduce 방향을 바꾸라고 오류가 나와서, new_order_side로 변경함.(06.01) #<-- 0619 tp side가 맞으므로 다시 수정
                                amount=level_quantities[level_index],
                                price=tp_price,
                                params={'reduceOnly': True}  #if is_short_order else {} < -- ??? 이건 왜 롱오더에 대해선 적용을 안한거지
                            )
                            #print('tp_order06')
                            #print(f"Take profit order placed at {take_profit_level}")
                        # 익절 주문 정보 업데이트
                        for key in possible_order_id_keys:
                            if 'info' in tp_order and key in tp_order['info']:
                                order_id = tp_order['info'][key]
                                if exchange_name == 'okx' or exchange_name == 'okx_spot':
                                    if (isinstance(order_id, int) or (isinstance(order_id, str)) and order_id.isdigit() and 1 <= len(order_id) <= 20):
                                        break
                                    else:
                                        print(f"잘못된 order_id: {order_id}")
                                else:
                                    if (isinstance(order_id, int) or (isinstance(order_id, str))) and (1 <= len(order_id) <= 60):
                                        break
                                    else:
                                        print(f"잘못된 order_id: {order_id}. type : {type(order_id)}")
                        if tp_order is not None:
                            level_index = level_index + 1 if not is_short_order else level_index - 1
                            take_profit_orders_info[str(level_index)] = {
                                "order_id": order_id, 
                                "quantity": adjusted_quantity, 
                                "target_price": take_profit_level, 
                                "active": True,
                                "side": tp_side
                            }
                        try:
                            await asyncio.sleep(random.random())
                            await update_take_profit_orders_info(redis, exchange_name, user_id, symbol, level = level_index, order_id = order_id, new_price =  take_profit_level, quantity = adjusted_quantity,active = True, side =tp_side)
                            await add_placed_price(exchange_name, user_id, symbol, take_profit_level)
                            await set_order_placed(exchange_name, user_id, symbol, take_profit_level, level_index = level_index)
                            asyncio.create_task(monitor_tp_orders_websocekts(exchange_name,symbol, user_id, level_index, take_profit_orders_info))
                        except Exception as e:
                            print(f" {user_id} : An error occurred10: {e}")
                ###익절 후, 새로운 주문을 아래에 거는 것###
                if new_order_level is not None:
                    if new_order_side is not None:
                        if exchange_instance.id.lower() == 'upbit':
                            new_order_level = get_corrected_rounded_price(new_order_level)
                        else:
                            new_order_level = adjust_price_precision(new_order_level, price_precision)
                        if not await is_price_placed(exchange_name, user_id, symbol, price = new_order_level, grid_level = level_index):
                            try:
                                if exchange_name == 'bitget':
                                    new_order = await exchange_instance.create_order(
                                        symbol=symbol,
                                        type='limit',
                                        side=new_order_side,
                                        amount=adjusted_quantity,
                                        price=new_order_level,
                                        params={
                                            'contract_type': 'swap',
                                            'position_mode': 'single',
                                            'marginCoin': 'USDT',
                                        })
                                elif exchange_name == 'binance':
                                    new_order = await exchange_instance.create_order(
                                        symbol=symbol,
                                        type='limit',
                                        side=new_order_side,
                                        amount=adjusted_quantity,
                                        price=new_order_level
                                    )
                                elif exchange_name == 'binance_spot':
                                    new_order = await exchange_instance.create_order(
                                        symbol=symbol,
                                        type='limit',
                                        side='sell',
                                        amount=min(adjusted_quantity, new_order_quantity),
                                        price=new_order_level
                                    )
                                elif exchange_instance.id.lower() == 'upbit':
                                    new_order = await retry_async(strategy.place_order, exchange_instance, symbol, order_type='limit',side='buy', amount = adjusted_quantity, price = new_order_level)
                                elif exchange_name == 'okx':
                                    #print('okx_order9')
                                    new_order = await exchange_instance.create_order(
                                        symbol=symbol,
                                        type='limit',
                                        side=new_order_side,
                                        amount=adjusted_quantity,
                                        price=new_order_level
                                    )
                                elif exchange_name == 'okx_spot':
                                    new_order = await exchange_instance.create_order(
                                        symbol=symbol,
                                        type='limit',
                                        side='sell',
                                        amount=adjusted_quantity,
                                        price=new_order_level
                                    )
                            except Exception as e:
                                print(f" {user_id} :An error occurred5: {e}")    
                            print(f"New order placed at {new_order_level}")
                            order_placed[int(level_index)] = True # 주문이 성공적으로 생성되었음을 표시
                            await add_placed_price(exchange_name, user_id, symbol, new_order_level)
                            await set_order_placed(exchange_name, user_id, symbol, new_order_level, level_index = level_index)
                        else:
                            print(f"{symbol}의 {level_index}레벨 주문이 이미 있습니다.(check_order_status)")
                        
                        
                break
            elif fetched_order['status'] == 'canceled':
                order_placed[level_index] = False
                break
            await asyncio.sleep(3)

    finally:
        order_placed[int(level_index)] = False
        await redis.close()
        return order_placed



MAX_RETRIES = 3
RETRY_DELAY = 4  # 재시도 사이의 대기 시간(초)

async def retry_async(func, *args, **kwargs):
    func_name = func.__name__  # 함수 이름 가져오기
    #print(f"Retrying {func_name}")
    for attempt in range(MAX_RETRIES):
        try:
            #print(f"Attempting {func_name}: try {attempt + 1}/{MAX_RETRIES}")
            return await func(*args, **kwargs)
        except Exception as e:
            if "remove" in str(e):
                print(f"remove the symbol: {e}")
                raise "remove"
            print(f"{func_name} failed on attempt {attempt + 1}/{MAX_RETRIES}. Error: {str(e)}")
            if attempt == MAX_RETRIES - 1:
                print(f"Maximum retries reached for {func_name}. Exiting.")
                raise e
            await asyncio.sleep(RETRY_DELAY)






async def monitor_tp_orders_websocekts(exchange_name, symbol_name, user_id, level_index, take_profit_orders_info):
    global cancel_state, user_keys
    #print(f"take_profit_orders_info: {take_profit_orders_info}")
    redis = await get_redis_connection()
    user_key = f"exchange:{exchange_name}:user:{user_id}"
    first_time_check = True
    is_running = await redis.hget(user_key, 'is_running')
    try:
        if is_running is not None:
            is_running = is_running.decode('utf-8') if isinstance(is_running, bytes) else str(is_running)
            is_running = bool(int(is_running or '0'))
        else:
            is_running = False
    except Exception as e:
        print(f"An error occurred on getting is_running! : {str(e)}")
    #print(f"{symbol_name}으로 익절 주문 감시 시작")
    
    async def handle_order_update(order, level, symbol_name):
        if level is not None:
            if order['status'] == 'closed':
                print(f"레벨 {level} 익절 주문 체결")
                #global_messages.trading_message.put(f"{symbol_name}의 {level}번째 그리드 익절 주문이 체결되었습니다.\n[수량 : {info['quantity']}, 가격 : {info['target_price']} 시간 : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]")
                message = f"{symbol_name}의 {level}번째 그리드 익절 주문이 체결되었습니다.\n[수량 : {info['quantity']}, 가격 : {info['target_price']} 시간 : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]"
                await add_user_log(user_id, message)
                grid_count = 1 if order['side'] == 'buy' else -1
                await update_active_grid(redis, exchange_name, user_id, symbol_name, level, entry_price = 0.0, position_size = 0.0, execution_time = datetime.now(), grid_count = grid_count ,pnl = None)
                await update_take_profit_orders_info(redis, exchange_name, user_id, symbol_name, level, order_id = None, new_price = 0.0, quantity = 0.0, active = False, side = None)
                asyncio.create_task(telegram_message.send_telegram_message(message, exchange_name, user_id))
                if info['quantity'] == 0:
                    print("❗️DEBUG: 익절 주문 수량이 0입니다. 확인이 필요합니다")
                    print(f"❗️DEBUG: 익절 주문 정보: {info}")
                    #print(f"take_profit_orders_info: {take_profit_orders_info}")
                    #asyncio.create_task(telegram_message.send_telegram_message(f"❗️DEBUG: {symbol_name}의 익절 주문 수량이 0입니다. 확인이 필요합니다", exchange_name, user_id, debug = True))
                take_profit_orders_info[str(level)] = {"order_id": None, "quantity": 0, "target_price": 0, "active": False, "side": None}
                await update_take_profit_orders_info(redis, exchange_name, user_id, symbol_name, level_index, order_id = None, new_price = 0.0, quantity = 0.0, active = False, side = False)
                print(f"{user_id} : {symbol_name}의 {level}번째 그리드 익절 주문이 체결되었습니다.")
            elif order['status'] == 'canceled':
                current_time = datetime.now()
                minutes = current_time.minute
                seconds = current_time.second
                if ((minutes in [14, 29, 44, 59] and seconds >= 58)) : #TODO : cancel_state == 1일때 구현 필요. :
                    take_profit_orders_info[level] = {"order_id": None, "quantity": info['quantity'], "target_price": 0, "active": True, "side": None}
                    await update_take_profit_orders_info(redis, exchange_name, user_id, symbol_name, level, order_id = None, new_price = 0.0, quantity = info['quantity'], active = True,  side = None)
                else:
                    take_profit_orders_info[level] = {"order_id": None, "quantity": info['quantity'], "target_price": 0, "active": True, "side": None} #<-- 이게 active가 True인건지, 확인이 필요함. <--0705. False가 맞다. cancel은 기본적으로 직접 한거니까. 그런데, 현재 중앙통제 구조에서는 True도맞다
                    await update_take_profit_orders_info(redis, exchange_name, user_id, symbol_name, level, order_id = None, new_price = 0.0, quantity = info['quantity'], active = False,  side = None)
                print(f"{user_id} : {symbol_name}의 {level}번째 그리드 익절 주문이 취소되었습니다. 익절 테스크를 종료합니다")
                return
            #else:
            #    print(f"레벨 {level} 주문 상태 업데이트: {order['status']}")
    try:
        exchange_instance = await get_exchange_instance(exchange_name, user_id)
    except Exception as e:
        print(f"{user_id} : An error occurred21: {e}")
        return
    try:
        while True:
            await asyncio.sleep(random.uniform(0.5, 2))
            current_time = datetime.now()
            minutes = current_time.minute
            seconds = current_time.second
            # 15분 단위 시간 확인 (14분 55초, 29분 55초, 44분 55초, 59분 55초에 종료)
            #take_profit_orders_info = user_keys[user_id]["symbols"][symbol_name]["take_profit_orders_info"]
            take_profit_orders_info = await get_take_profit_orders_info(redis, exchange_name, user_id, symbol_name, level_index,  force_restart=False)
            #print("15분확인", take_profit_orders_info)
            if ((minutes in [15, 30, 45, 0] and seconds >= 55)) and not first_time_check:
                #print("15분봉 마감 도달 - 익절 관리 종료")
                try:
                    orders_to_cancel = []
                    for level, info in take_profit_orders_info.items():
                        if info["order_id"] is not None:
                            try:
                                orders_to_cancel.append(info["order_id"])
                                #await exchange_instance.cancel_order(info["order_id"], symbol_name) #<-- batch 주문으로 중앙화 
                            except Exception as e:
                                print(f"익절 주문 취소 실패. {symbol_name} {level}레벨, {info['order_id']}")
                                await telegram_message.send_telegram_message(f"익절 주문 취소 실패: {e}", exchange_name, user_id, debug = True)
                    return
                except Exception as e:
                    print(f"익절 관리 종료 혹은 주문 취소할 것 없음 Monitor_tp_orders: {e}")
                    return
            else:
                for level, info in take_profit_orders_info.items():
                    if info["active"] and info["order_id"] is not None:
                        try:
                            #print(f" {symbol_name} 레벨 {level} 익절 주문 감시 시작")
                            order = await exchange_instance.fetch_order(info["order_id"], symbol_name)
                            await handle_order_update(order, level, symbol_name)
                        except Exception as e:
                            if 'Order does not exist' in str(e):
                                print(f"{user_id} : 익절 주문이 존재하지 않음. {symbol_name} {level}레벨, {info['order_id']}")
                                await update_take_profit_orders_info(redis, exchange_name, user_id, symbol_name, level, order_id = None, new_price = 0.0, quantity = 0.0, active = False, side = False)
                                continue
                first_time_check = False
                await asyncio.sleep(4.36)  # 4초마다 체크

    except Exception as e:
        print(f"{user_id} : 기타 예외 처리1: {e}")
        print(traceback.print_exc())
        await asyncio.sleep(5)
    #####TODO : 인스턴스 재활용버젼에서는 필요없어서 우선 확인
    finally:
        return
    #    if exchange_instance is not None:
    #        await exchange_instance.close()
        
    
#================================================================================================
# Monitor SL Orders
#================================================================================================



async def monitor_positions(exchange_name, user_id):
    redis = await get_redis_connection()
    retry_count = 0
    max_retry_count = 3
    user_data = await redis.hgetall(f'{exchange_name}:user:{user_id}')
    await asyncio.sleep(4.5)
    exchange = None
    is_running = parse_bool(user_data.get('is_running', '0'))
    if is_running:
        try:
            exchange = await get_exchange_instance(exchange_name, user_id)
            await asyncio.sleep(0.8)
            while True:
                is_running = parse_bool(user_data.get('is_running', '0'))
                try:
                    if (not is_running):
                        return
                    await check_and_close_positions(exchange, user_id)
                    if not running_symbols and not is_running:  # running_symbols가 비었는지 확인
                        print("모든 포지션을 청산했습니다. 모니터링을 종료합니다.")
                        break
                    await asyncio.sleep(15)  # 15초 대기
                except Exception as e:
                    print(f"{user_id} : An error occurred on monitor_positions1: {e}")
                    print(traceback.format_exc())
                    retry_count =+ 1
                    if max_retry_count == retry_count:
                        print(f"모니터링 SL테스크 생성 중 오류가 발생하여 종료합니다.")
                        break
                    await asyncio.sleep(4)
                    continue
        except Exception as e:
            if 'API' in str(e):
                print(f"{user_id} API 키 오류로 인한 모니터링 종료")
                await redis.hset(f'{exchange_name}:user:{user_id}', 'is_running', 0)
                return
                
            print(f"{user_id} : An error occurred on monitor_positions0: {e}")
            print(traceback.format_exc())
        finally:
            return
            #if exchange:
            #    await exchange.close()
    else:
        print(f"User {user_id} is not running. Stopping monitor_positions.")
        return
            
            
async def monitor_custom_stop(exchange_name, user_id, custom_stop):
    redis = await get_redis_connection()
    try:
        print(f"Starting monitor_custom_stop for user {user_id} on {exchange_name}")
        while True:
            user_key = f'{exchange_name}:user:{user_id}'
            is_running = await redis.hget(user_key, 'is_running')
            if is_running is not None:
                try:
                    is_running = is_running.decode('utf-8') if isinstance(is_running, bytes) else str(is_running)
                    is_running = bool(int(is_running or '0'))
                except Exception as e:
                    print(f"{user_id} : An error occurred on getting is_running! : {str(e)}")
                    is_running = True
            else:
                is_running = False
            #print(f"Debug: User {user_id} is_running status: {is_running}")  # 디버그 로그 추가

            if not is_running:
                logger.info(f"User {user_id} is not running. Stopping monitor_custom_stop.")
                break

            try:
                await check_entry_order(exchange_name, user_id, custom_stop)
            except Exception as e:
                print(f"{user_id} : An error occurred on check_entry_order: {e}")
                print(traceback.format_exc())

            await asyncio.sleep(15)  # 15초 대기
        if not is_running:
            print(f"User {user_id} is not running. Stopping monitor")
        
    except Exception as e:
        print(f"{user_id} : An error occurred on monitor_custom_stop: {e}")
        print(traceback.format_exc())
        return

    finally:
        await redis.close()
        print(f"monitor_custom_stop for user {user_id} on {exchange_name} has stopped.")
        return

async def check_entry_order(exchange_name, user_id, custom_stop):
    redis = await get_redis_connection()
    exchange = None
    try:
        user_data = await redis.hgetall(f'{exchange_name}:user:{user_id}')
        if not user_data:
            print(f"No data found for user {user_id}")
            return

        running_symbols = set(json.loads(user_data.get('running_symbols', '[]')))
        symbols_data = json.loads(user_data.get('symbols', '{}'))

        for symbol in running_symbols:
            if symbol not in symbols_data:
                continue

            last_entry_time = symbols_data[symbol].get("last_entry_time")
            if custom_stop > 0 and last_entry_time is not None:
                last_entry_time = datetime.fromisoformat(last_entry_time)
                if (datetime.now() - last_entry_time).total_seconds() >= custom_stop * 60:
                    exchange = await get_exchange_instance(exchange_name, user_id)
                    trades = await exchange.fetch_my_trades(symbol, limit=1)
                    if trades:
                        actual_last_entry_time = datetime.strptime(trades[0]['datetime'], "%Y-%m-%dT%H:%M:%S.%fZ")
                        if (datetime.now() - actual_last_entry_time).total_seconds() >= custom_stop * 60:
                            print(f"{user_id} : 마지막 진입 시간이 지정된 시간 {custom_stop}분을 초과하여 {symbol} 포지션을 청산합니다.\n마지막 진입 : {actual_last_entry_time}")
                            await manually_close_symbol(exchange_name, user_id, symbol)
                        else:
                            # 실제 마지막 진입 시간으로 Redis 업데이트
                            symbols_data[symbol]["last_entry_time"] = actual_last_entry_time.isoformat()
                            await redis.hset(f'{exchange_name}:user:{user_id}', 'symbols', json.dumps(symbols_data))
                            print(f"{symbol}의 last_entry_time을 {actual_last_entry_time}으로 업데이트했습니다.")

    except Exception as e:
        print(f"{user_id} : An error occurred on check_entry_order: {e}")
        print(traceback.format_exc())
    ####TODO : 인스턴스 재활용버젼에서는 필요없어서 우선 확인
    #finally:
    #    if exchange is not None:
    #        await exchange.close()

async def check_and_close_positions(exchange, user_id):
    redis = await get_redis_connection()
    try:
        exchange_name = str(exchange.id).lower()
        user_key = f'{exchange_name}:user:{user_id}'
        user_data = await redis.hgetall(user_key)
        
        running_symbols = set(json.loads(user_data.get('running_symbols', '[]')))
        is_running = parse_bool(user_data.get('is_running', '0'))
        stop_loss = float(user_data.get('stop_loss', 0))
        if not is_running:
            return
        if exchange_name == 'okx' or exchange_name == 'okx_spot':
            # 캐시 키 생성
            cache_key = f'{exchange_name}:positions:{user_id}'

            # 캐시에서 포지션 데이터 가져오기 시도
            cached_positions = await redis.get(cache_key)
            if cached_positions:
                try:
                    positions_data = json.loads(cached_positions)
                    #logger.info(f"Cached positions data for user {user_id}: {positions_data}")
                    if isinstance(positions_data, list):
                        for position in positions_data:
                            
                            if isinstance(position, dict):
                                # Process each position
                                symbol = position.get('instId')
                                if symbol in running_symbols:
                                    # Your position processing logic here
                                    pass
                            else:
                                logger.warning(f"Unexpected position data format for user {user_id}: {position}")
                    elif isinstance(positions_data, dict):
                        # If positions_data is a dict, it might be a single position
                        symbol = positions_data.get('instId')
                        if symbol in running_symbols:
                            # Your position processing logic here
                            pass
                    else:
                        logger.warning(f"Unexpected positions data format for user {user_id}: {positions_data}")

                except json.JSONDecodeError as e:
                    logger.error(f"Error decoding cached positions for user {user_id}: {e}")
                if positions_data is not None:
                    try:
                        if isinstance(positions_data, list):
                            for position in positions_data:
                                if isinstance(position, dict) and 'instId' in position:
                                    symbol = position['instId']
                                    if symbol in running_symbols:

                                        quantity = float(position['pos']) if position['pos'] else 0.0
                                        avg_entry_price = float(position['avgPx']) if position['avgPx'] else 0.0
                                        current_price = float(position['last']) if position['last'] else 0.0
                                        side = 'long' if quantity > 0 else 'short'
                                        #print('여기까지 확인(ws)! ', symbol, quantity, avg_entry_price, current_price, side)
                                        if side == 'long':
                                            pnl_percent = ((current_price - avg_entry_price) / avg_entry_price) * 100
                                        else:  # short position
                                            pnl_percent = ((avg_entry_price - current_price) / avg_entry_price) * 100

                                        if stop_loss > 0 and pnl_percent < -stop_loss:
                                            print(f"{user_id} : Warning: {symbol} has exceeded the stop loss threshold with a PnL% of {pnl_percent}")
                                            await strategy.close_position(exchange, symbol, side, abs(quantity), user_id)

                                            message = f"⚠️{user_id} {symbol}의 손실률이 -{stop_loss}%를 초과하여 포지션을 청산합니다.\n평균단가 : {avg_entry_price}\n방향 : {side} \nPNL퍼센트 : {round(pnl_percent,2)}"
                                            await telegram_message.send_telegram_message(message, exchange_name, user_id)
                                            await add_user_log(user_id, message)

                                            completed_symbols = set(json.loads(user_data.get('completed_trading_symbols', '[]')))
                                            completed_symbols.add(symbol)
                                            running_symbols.remove(symbol)

                                            await redis.hset(user_key, 'completed_trading_symbols', json.dumps(list(completed_symbols)))
                                            await redis.hset(user_key, 'running_symbols', json.dumps(list(running_symbols)))
                                            print(f"{user_id} :  changed running symbol : {running_symbols}")

                                            print(f"❗️{symbol} removed from running_symbols for user {user_id}.")

                                            await asyncio.sleep(6)
                    except Exception as e:
                        print(f"{user_id} : An error occurred on check_and_close_positions: {e}. type : {type(positions_data)}")
                        print(traceback.format_exc())
            else:
                try:
                    await asyncio.sleep(random.uniform(0.1, 1) + 0.9)
                    #position_data = json.loads(cached_positions)
                    positions_data = await exchange.private_get_account_positions()
                    await redis.set(cache_key, json.dumps(positions_data), ex=20)
                except Exception as e:
                    raise e
                
                for position in positions_data['data']:
                    symbol = position['instId']
                    if symbol in running_symbols:
                        quantity = float(position['pos']) if position['pos'] else 0.0
                        avg_entry_price = float(position['avgPx']) if position['avgPx'] else 0.0
                        current_price = float(position['last']) if position['last'] else 0.0
                        side = 'long' if quantity > 0 else 'short'

                        print(f"Checking position for {symbol} , {quantity}, {avg_entry_price}, {current_price}, {side}")
                        if side == 'long':
                            pnl_percent = ((current_price - avg_entry_price) / avg_entry_price) * 100
                        else:  # short position
                            pnl_percent = ((avg_entry_price - current_price) / avg_entry_price) * 100

                        if stop_loss > 0 and pnl_percent < -stop_loss:
                            print(f"Warning: {symbol} has exceeded the stop loss threshold with a PnL% of {pnl_percent}")
                            await strategy.close_position(exchange, symbol, side, abs(quantity), user_id)

                            message = f"⚠️{user_id} {symbol}의 손실률이 -{stop_loss}%를 초과하여 포지션을 청산합니다.\n평균단가 : {avg_entry_price}\n방향 : {side} \nPNL퍼센트 : {round(pnl_percent,2)}"
                            await telegram_message.send_telegram_message(message, exchange_name, user_id)
                            await add_user_log(user_id, message)

                            completed_symbols = set(json.loads(user_data.get('completed_trading_symbols', '[]')))
                            completed_symbols.add(symbol)
                            running_symbols.remove(symbol)

                            await redis.hset(user_key, 'completed_trading_symbols', json.dumps(list(completed_symbols)))
                            await redis.hset(user_key, 'running_symbols', json.dumps(list(running_symbols)))
                            print(f" changed running symbol : {running_symbols}")

                            print(f"❗️{symbol} removed from running_symbols for user {user_id}.")

                            await asyncio.sleep(6)
        try:
            if exchange_name == 'upbit' : 
                await asyncio.sleep(random.uniform(0.6, 2.2))
                balance = await exchange.fetch_balance()
                base_currency = symbol.split('-')[1]  # 'KRW-ETC'에서 'ETC'를 추출
                print("fetched positions for upbit")
                for position in positions_data:
                    symbol = position['symbol']
                    if symbol in running_symbols:
                        print(position)
                        quantity = float(position['amount']) if position['amount'] else 0.0  # 'pos' 값을 float로 변환합니다.
                        avg_entry_price = float(position['avgPx']) if position['avgPx'] else 0.0  # 'avgPx' 값을 float로 변환합니다.
                        current_price = float(position['last']) if position['last'] else 0.0  # 'last' 값을 float로 변환합니다.
                        side = 'long' if quantity > 0 else 'short'  # 'posSide' 값 확인 (long/short)

                        if side == 'long':
                            pnl_percent = ((current_price - avg_entry_price) / avg_entry_price) * 100
                        else:  # short position
                            pnl_percent = ((avg_entry_price - current_price) / avg_entry_price) * 100

                        #print(f"[{user_id}] Symbol: {symbol}, Quantity: {quantity}, PnL%: {pnl_percent}")

                        if (stop_loss is not None) and (stop_loss > 0) and pnl_percent < -stop_loss:
                            print(f"Warning: {symbol} has exceeded the stop loss threshold with a PnL% of {pnl_percent}")
                            await strategy.close_position(exchange, symbol, side, quantity, user_id)

                            await telegram_message.send_telegram_message(f"⚠️ {symbol}의 손실률이 -{stop_loss}%를 초과하여 포지션을 청산합니다.\n평균단가 : {avg_entry_price}\n방향 : {side} \nPNL퍼센트 : {round(pnl_percent,2)}", exchange, user_id)
                            message = f"⚠️ {symbol}의 손실률이 -{stop_loss}%를 초과하여 포지션을 청산합니다.\n평균단가 : {avg_entry_price}\n방향 : {side} \nPNL퍼센트 : {round(pnl_percent,2)}"
                            #await manager.add_user_message(user_id, message)
                            await add_user_log(user_id, message)
                            #global_messages.trading_message.put(f"⚠️ {symbol}의 손실률이 -{stop_loss}%를 초과하여 포지션을 청산합니다.\n평균단가 : {avg_entry_price}\n방향 : {side} \nPNL퍼센트 : {round(pnl_percent,2)}")

                            print(f"❗️{symbol} removed from running_symbols.")

                            #포지션 청산 후, 새로운 포지션 진입 로직 
                            await asyncio.sleep(5)
                        
                        
        except Exception as e:
            print(f"{user_id} : An error occurred3153: {e}")
            raise e
    except Exception as e:
        if 'API' in str(e):
            print(f"{user_id} : API 키 오류로 인한 모니터링 종료")
            await redis.hset(f'{exchange_name}:user:{user_id}', 'is_running', 0)
            raise e
        if 'Invalid' in str(e):
            print(f"{user_id} : API 키 오류로 인한 모니터링 종료")
            await redis.hset(f'{exchange_name}:user:{user_id}', 'is_running', 0)
            raise e
        if 'AuthenticationError' in str(e):
            print(f"{user_id} : API 키 오류로 인한 모니터링 종료")
            await redis.hset(f'{exchange_name}:user:{user_id}', 'is_running', 0)
            raise e
        print(f"{user_id}: An error occurred30131: {e}")
        raise e
    finally:
        if redis is not None:
            await redis.close()

async def manually_close_positions(exchange_name, user_id):
    redis = await get_redis_connection()
    exchange = None
    try:
        user_key = f'{exchange_name}:user:{user_id}'
        user_data = await redis.hgetall(user_key)
        running_symbols = set(json.loads(user_data.get('running_symbols', '[]')))
        
        exchange = await get_exchange_instance(exchange_name, user_id)
        
        if exchange_name == 'okx' or exchange_name == 'okx_spot':
            positions_data = await exchange.private_get_account_positions()
            for position in positions_data['data']:
                symbol = position['instId']
                if symbol in running_symbols:
                    quantity = float(position['pos'])
                    side = 'long' if quantity > 0 else 'short'
                    await strategy.close_position(exchange, symbol, side, abs(quantity), user_id)
        elif exchange_name == 'upbit':
            position_data = await exchange.fetch_balance()
            for symbol in running_symbols:
                base_currency = symbol.split('-')[1]
                quantity = float(position_data['total'].get(base_currency, 0))
                if quantity > 0:
                    await strategy.close_position(exchange, symbol, 'long', quantity, user_id)
        else:
            positions_data = await exchange.fetch_positions()
            for position in positions_data:
                symbol = position['symbol']
                if symbol in running_symbols:
                    quantity = float(position['amount'])
                    side = 'long' if quantity > 0 else 'short'
                    await strategy.close_position(exchange, symbol, side, abs(quantity), user_id)
        
        log_message = "{user_id}  : 전체 포지션을 종료하고 새로운 종목으로 탐색합니다"
        message = "{user_id}  : 전체 포지션을 종료하고 새로운 종목으로 탐색합니다"
        await telegram_message.send_telegram_message(message, exchange_name, user_id)
        await add_user_log(user_id, log_message)
        
        completed_symbols = set(json.loads(user_data.get('completed_trading_symbols', '[]')))
        completed_symbols.update(running_symbols)
        running_symbols.clear()
        
        await redis.hset(user_key, 'completed_trading_symbols', json.dumps(list(completed_symbols)))
        await redis.hset(user_key, 'running_symbols', json.dumps(list(running_symbols)))
        
        print(f"❗️All symbols removed from running_symbols for user {user_id}.")
        
        await asyncio.sleep(3)
        
    except Exception as e:
        print(f"{user_id} : An error occurred in manually_close_positions: {e}")
        print(traceback.format_exc())
    finally:
        #if exchange is not None:
        #    await exchange.close()
        if redis is not None:
            await redis.close()
    
async def manually_close_symbol(exchange_name, user_id, symbol):
    redis = await get_redis_connection()
    exchange = None
    try:
        user_key = f'{exchange_name}:user:{user_id}'
        user_data = await redis.hgetall(user_key)
        running_symbols = set(json.loads(user_data.get('running_symbols', '[]')))
        
        if symbol not in running_symbols:
            print(f"Symbol {symbol} is not in running symbols for user {user_id}")
            return
        
        exchange = await get_exchange_instance(exchange_name, user_id)
        
        if exchange_name == 'okx' or exchange_name == 'okx_spot':
            positions_data = await exchange.private_get_account_positions()
            for position in positions_data['data']:
                if position['instId'] == symbol:
                    quantity = float(position['pos'])
                    side = 'long' if quantity > 0 else 'short'
                    await strategy.close_position(exchange, symbol, side, abs(quantity), user_id)
                    break
        elif exchange_name == 'upbit':
            position_data = await exchange.fetch_balance()
            base_currency = symbol.split('-')[1]
            quantity = float(position_data['total'].get(base_currency, 0))
            if quantity > 0:
                await strategy.close_position(exchange, symbol, 'long', quantity, user_id)
        else:
            positions_data = await exchange.fetch_positions()
            for position in positions_data:
                if position['symbol'] == symbol:
                    quantity = float(position['amount'])
                    side = 'long' if quantity > 0 else 'short'
                    await strategy.close_position(exchange, symbol, side, abs(quantity), user_id)
                    break
        
        message = f"{user_id}  : {symbol}에 대해 설정한 기간동안 포지션 진입이 없습니다.\n{symbol}을 종료하고 새로운 종목으로 탐색합니다"
        await telegram_message.send_telegram_message(message, exchange_name, user_id)
        await add_user_log(user_id, message)
        
        completed_symbols = set(json.loads(user_data.get('completed_trading_symbols', '[]')))
        completed_symbols.add(symbol)
        running_symbols.remove(symbol)
        
        await redis.hset(user_key, 'completed_trading_symbols', json.dumps(list(completed_symbols)))
        await redis.hset(user_key, 'running_symbols', json.dumps(list(running_symbols)))
        
        print(f"❗️{symbol} removed from running_symbols for user {user_id}.")
        
        await asyncio.sleep(3)
        
    except Exception as e:
        print(f"{user_id} : An error occurred in manually_close_symbol: {e}")
        print(traceback.format_exc())
    finally:
        if exchange is not None:
            await exchange.close()
        await redis.close()
    



# =======[TOOLS_SECTION_START]=======
# Tools 
# ==================================
# 타임프레임을 float형태로
# 다음 타임프레임까지의 시간 계산
# 타임존 계산
# ===================================


def async_debounce(wait):
    def decorator(fn):
        last_called = None
        task = None
        
        @wraps(fn)
        async def debounced(*args, **kwargs):
            nonlocal last_called, task
            current_time = asyncio.get_event_loop().time()
            
            if last_called is None or current_time - last_called >= wait:
                last_called = current_time
                if task:
                    task.cancel()
                task = asyncio.create_task(fn(*args, **kwargs))
                return await task
        
        return debounced
    return decorator


def parse_timeframe(timeframe):
    # Determine if timeframe is in minutes or hours
    if 'm' in timeframe:
        timeframe_unit = 'minutes'
        timeframe_value = int(timeframe.replace('m', ''))
    elif 'h' in timeframe:
        timeframe_unit = 'hours'
        timeframe_value = int(timeframe.replace('h', ''))
    else:
        raise ValueError("Invalid timeframe format")
    return timeframe_unit, timeframe_value


def calculate_current_timeframe_start(timeframe, timezone="Asia/Seoul"):
    now = datetime.now(pytz.timezone(timezone))
    timeframe_unit, timeframe_value = parse_timeframe(timeframe)

    if timeframe_unit == 'minutes':
        current_timeframe_start = now - timedelta(minutes=now.minute % timeframe_value)
    elif timeframe_unit == 'hours':
        current_timeframe_start = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=now.hour % timeframe_value)

    return current_timeframe_start

def calculate_next_timeframe_start(now, timeframe):
    timeframe_unit, timeframe_value = parse_timeframe(timeframe)

    next_minute, next_hour = now.minute, now.hour
    if timeframe_unit == 'minutes':
        next_minute = ((now.minute // timeframe_value + 1) * timeframe_value) % 60
        if next_minute <= now.minute:
            next_hour = (now.hour + 1) % 24
    elif timeframe_unit == 'hours':
        next_hour = (now.hour + timeframe_value) % 24
        next_minute = 0

    next_timeframe_start = now.replace(hour=next_hour, minute=next_minute, second=0, microsecond=0)
    return next_timeframe_start

def calculate_sleep_duration(now, next_timeframe_start):
    delta = next_timeframe_start - now
    return max(15, delta.total_seconds())




#================================================================================================
# CREATE ORDERS
#================================================================================================

async def create_short_orders(exchange_instance, symbol, short_level, adjusted_quantity, min_quantity, user_id, reduce_only=False):
    try:
        if reduce_only:
            short_order = await exchange_instance.create_order(
                symbol=symbol,
                type='limit',
                side='sell',
                amount= max(adjusted_quantity, min_quantity),
                price=short_level,
                params={'reduceOnly': True}
            )
            print(f'{symbol} long direction short_order11✔︎')
        else:
            short_order = await exchange_instance.create_order(
                symbol=symbol,
                type='limit',
                side='sell',
                amount= max(adjusted_quantity, min_quantity),
                price=short_level
            )
            print(f"{user_id} : {symbol} direction short_order22✔︎")
        
        return short_order
    except Exception as e:
        
        print(f"{user_id} : An error occurred in create_short_orders2: {e}")

        raise e

# ==============================================================================
#                              Searching Data
# ==============================================================================

def sort_ai_trading_data(exchange_name, direction):
    if exchange_name is None:
        raise ValueError("exchange 변수가 None입니다. 올바른 값을 제공해야 합니다.")

    summary_path = path_helper.grid_dir / str(exchange_name) / str(direction) / f"{exchange_name}_summary_trading_results.csv"
    print(summary_path)
    df_summary = pd.read_csv(summary_path)

    # 'symbol' 열을 'name'으로 이름 변경
    df_summary.rename(columns={'symbol': 'name'}, inplace=True)
    # 'total_profit' 열을 'win_rate'로 이름 변경하여 사용하기
    df_summary.rename(columns={'total_profit': 'win_rate'}, inplace=True)

    return df_summary[['name', 'win_rate']]

async def build_sort_ai_trading_data(exchange_name, enter_strategy) -> List[WinrateDto]:
    direction = str(enter_strategy).lower()
    if exchange_name is None:
        raise ValueError("exchange 변수가 None입니다. 올바른 값을 제공해야 합니다.")
    if direction is None:
        raise ValueError("direction 변수가 None입니다. 올바른 값을 제공해야 합니다.")

    exchange_name = str(exchange_name).lower()
    summary_path = path_helper.grid_dir / str(exchange_name) / direction / f"{exchange_name}_summary_trading_results.csv"
    # summary_trading_results.csv 파일에서 데이터 읽기
    df_summary = pd.read_csv(summary_path)

    # 'total_profit' 열을 기반으로 각 win_rate 값 설정, assuming 'total_profit' column exists
    df_summary['long_win_rate'] = df_summary['total_profit']
    df_summary['short_win_rate'] = df_summary['total_profit']
    df_summary['total_win_rate'] = df_summary['total_profit']

    # Ensure that 'symbol' column is correctly renamed to 'name'
    df_summary_renamed = df_summary.rename(columns={'symbol': 'name'})

    # Create WinrateDto objects from the DataFrame
    win_rate_data = [
        WinrateDto(
            name=row['name'],  # Correctly reference the 'name' column after renaming
            long_win_rate=row['long_win_rate'],
            short_win_rate=row['short_win_rate'],
            total_win_rate=row['total_win_rate']
        )
        for _, row in df_summary_renamed.iterrows()
    ]

    return win_rate_data


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


async def get_all_bitget_usdt_symbols(future = True):
    """비트겟의 모든 USDT 선물 마켓 종목과 거래량을 비동기적으로 가져오는 함수"""
    # 비트겟 선물 API 엔드포인트
    url = "https://api.bitget.com/api/mix/v1/market/tickers?productType=umcbl"

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            data = await response.json()

        # 응답 데이터 구조 확인
        if data['code'] != '00000':
            print(f"Error: {data['msg']}")
            return []

        if 'data' not in data or not isinstance(data['data'], list):
            print("Error: Unexpected response structure")
            return []

        # 비트겟에서의 응답 데이터 구조에 맞게 파싱
        usdt_volume_data = []
        for item in data['data']:
            if 'USDT' in item['symbol']:  # USDT 선물 마켓 확인
                original_symbol = item['symbol']
                symbol = original_symbol.replace('USDT_UMCBL', '/USDT')
                usdt_volume = float(item['usdtVolume'])  # USDT 24시간 거래량
                usdt_volume_data.append((symbol, usdt_volume))

        sorted_usdt_volume_data = sorted(usdt_volume_data, key=lambda x: x[1], reverse=True)
        return [item[0] for item in sorted_usdt_volume_data]





async def custom_sleep(timeframe):
    now = datetime.now()
    next_timeframe_start = calculate_next_timeframe_start(now, timeframe)
    print(f"다음 타임프레임 시작 시간: {next_timeframe_start}")
    
    while datetime.now() < next_timeframe_start:
        await asyncio.sleep(random.uniform(0.5, 1.5))

#================================================================================================
# 화이트리스트 / 블랙리스트
#================================================================================================

async def get_ban_list_from_db(user_id, exchange_name):
    db_path = f'{exchange_name}_users.db'
    # 데이터베이스 파일 존재 여부 확인
    if not os.path.exists(db_path):
        print(f"Database file not found: {db_path}")
        return []
    async with aiosqlite.connect(db_path) as db:
        async with db.execute('SELECT symbol FROM blacklist WHERE user_id = ?', (user_id,)) as cursor:
            ban_list = [row[0] for row in await cursor.fetchall()]
    return ban_list

async def get_white_list_from_db(user_id, exchange_name):
    db_path = f'{exchange_name}_users.db'
    async with aiosqlite.connect(db_path) as db:
        async with db.execute('SELECT symbol FROM whitelist WHERE user_id = ?', (user_id,)) as cursor:
            white_list = [row[0] for row in await cursor.fetchall()]
    return white_list

async def clear_blacklist(user_id, exchange_name):
    db_path = f'{exchange_name}_users.db'
    async with aiosqlite.connect(db_path) as db:
        await db.execute('DELETE FROM blacklist WHERE user_id = ?', (user_id,))
        await db.commit()

async def clear_whitelist(user_id, exchange_name):
    db_path = f'{exchange_name}_users.db'
    async with aiosqlite.connect(db_path) as db:
        await db.execute('DELETE FROM whitelist WHERE user_id = ?', (user_id,))
        await db.commit()

async def add_symbols(user_id, exchange_name, symbols, setting_type):
    db_path = f'{exchange_name}_users.db'
    table = setting_type
    async with aiosqlite.connect(db_path) as db:
        for symbol in symbols:
            await db.execute(f'INSERT INTO {table} (user_id, symbol) VALUES (?, ?)', (user_id, symbol))
        await db.commit()




#================================================================================================
async def generate_profit_data(exchange_name, direction, market_data):
    if exchange_name == 'upbit':
        profit_data = pd.DataFrame(market_data.items(), columns=['name', 'change_rate'])
        sorted_column = 'change_rate'
    else:
        summarize_trading_results(exchange_name=exchange_name, direction=direction)
        profit_data = sort_ai_trading_data(exchange_name=exchange_name, direction=direction)
        sorted_column = 'win_rate'
    
    return profit_data, sorted_column

async def process_exchange_data(exchange_name, direction, ban_list, white_list, market_data=None):
    # 캐시 키 생성
    cache_key = f"{exchange_name}:summarize:{direction}"
    
    # 캐시 확인
    cached_data = await redis_client.get(cache_key)
    
    if cached_data:
        # 캐시된 데이터가 있으면 역직렬화
        cached_result = json.loads(cached_data)
        if 'symbols' in cached_result:
            profit_data = pd.DataFrame(cached_result['symbols'])
            sorted_column = 'win_rate'  # 'win_rate'로 고정
        else:
            # 'symbols'가 없으면 캐시를 무시하고 새로 데이터를 생성
            profit_data, sorted_column = await generate_profit_data(exchange_name, direction, market_data)
    else:
        # 캐시된 데이터가 없으면 새로 데이터를 생성
        profit_data, sorted_column = await generate_profit_data(exchange_name, direction, market_data)
    
    # 결과를 캐시에 저장 (90초 TTL 설정)
    cache_data = {
        'symbols': profit_data.to_dict(orient='records')
    }
    await redis_client.set(cache_key, json.dumps(cache_data), ex=90)  # 'ex' 파라미터로 90초 TTL 설정
    
    # 거래소별 필터링 적용
    if exchange_name in ['binance', 'bitget', 'binance_spot', 'bitget_spot', 'okx_spot']:
        symbols = profit_data[(profit_data['name'].astype(str).str.endswith('USDT')) &
                              ~(profit_data['name'].astype(str).str.contains('USDC')) &
                              ~(profit_data['name'].astype(str).str.contains('USTC'))]
    elif exchange_name == 'okx':
        symbols = profit_data[(profit_data['name'].astype(str).str.endswith('USDT-SWAP')) &
                              ~(profit_data['name'].astype(str).str.contains('USDC')) &
                              ~(profit_data['name'].astype(str).str.contains('USTC'))]
    else:
        symbols = profit_data
    
    # ban_list 적용
    for ban_word in ban_list:
        symbols = symbols[~symbols['name'].str.contains(ban_word, case=False)]
    
    return symbols, sorted_column

async def get_running_symbols(exchange_id: str, user_id: str):
    redis = await get_redis_connection()
    redis_key = f"running_symbols:{exchange_id}:{user_id}"
    running_symbols_json = await redis.get(redis_key)
    
    
    if running_symbols_json:
        await redis.delete(redis_key)
        return json.loads(running_symbols_json)
    return []

async def get_completed_symbols(user_id, exchange_name):
    redis = await get_redis_connection()
    user_key = f'{exchange_name}:user:{user_id}'
    completed_symbols = await redis.hget(user_key, 'completed_trading_symbols')
    if completed_symbols:
        return json.loads(completed_symbols)
    return []
    

async def get_top_symbols(user_id, exchange_name, direction='long-short', limit=20, force_restart=False, get_new_only_symbols = False):
    try:
        ban_list = await get_ban_list_from_db(user_id, exchange_name)
        print(f"{user_id} ban_list : ", ban_list)
    except FileNotFoundError:  
        ban_list = []
        print('ban_list.json 파일이 존재하지 않습니다. 빈 리스트로 초기화합니다.')

    if ban_list is None:
        ban_list = []
    ban_list.extend(['XEC', 'USTC', 'USDC', 'TRY', 'CEL', 'GAL', 'OMG', 'SPELL', 'KSM', 'GPT', 'BLOCK', 'FRONT', 'TURBO', 'ZERO', 'MSN', 'FET'])

    try:
        white_list = await get_white_list_from_db(user_id, exchange_name)
    except FileNotFoundError:
        white_list = []
        print('white_list.json 파일이 존재하지 않습니다. 빈 리스트로 초기화합니다.')

    if white_list is None:
        white_list = []
    if exchange_name == 'upbit':
        market_data = await get_upbit_market_data() 
    else:
        market_data = None

    symbols, sorted_column = await process_exchange_data(exchange_name, direction, ban_list, white_list, market_data)

    if white_list:
        if exchange_name in ['binance', 'bitget', 'binance_spot', 'bitget_spot']:
            white_list = [symbol + 'USDT' for symbol in white_list]
        elif exchange_name == 'upbit':
            white_list = ['KRW-' + symbol for symbol in white_list]
        elif exchange_name == 'okx':
            white_list = [symbol + '-USDT-SWAP' for symbol in white_list]
        elif exchange_name == 'okx_spot':
            white_list = [symbol + '-USDT' for symbol in white_list]


    # get_all_positions 함수를 사용하여 현재 포지션 정보 가져오기
    positions = await get_all_positions(exchange_name, user_id)
    excluded_symbols = ['BTC-USDT-SWAP', 'ETH-USDT-SWAP', 'SOL-USDT-SWAP']
    positions = {k: v for k, v in positions.items() if k not in excluded_symbols}
    print(f"Current positions (after exclusion): {positions}")

    try:
        if force_restart:
            former_running_symbols = await get_running_symbols(exchange_name, user_id)
            if former_running_symbols is None:
                former_running_symbols = []
            print(f"former_running_symbols : {former_running_symbols}")
        else:
            former_running_symbols = []
    except Exception as e:
        print(f"{user_id} : An error occurred while fetching running symbols: {e}")
        former_running_symbols = []

    # ban_list에 없는 심볼만 포함
    top_symbols = [symbol for symbol in former_running_symbols if symbol not in ban_list]
    
    # positions에서 ban_list에 없는 심볼 추가
    for symbol in positions.keys():
        if symbol not in ban_list and symbol not in top_symbols:
            top_symbols.append(symbol)

    # 기존에 completed symbol이었던 것은 우선 제외
    if get_new_only_symbols:
        try:
            completed_symbols = await get_completed_symbols(user_id, exchange_name)
            top_symbols = [symbol for symbol in top_symbols if symbol not in completed_symbols]
        except Exception as e:
            print(f"An error occurred while fetching completed symbols: {e}")

    remaining_limit = max(limit - len(top_symbols), 0)
    print(f"remaining_limit : {remaining_limit}")

    if remaining_limit > 0:
        # white_list에서 남은 종목 선택 (ban_list에 없는 것만)
        white_list_symbols = symbols[symbols['name'].str.lower().isin([w.lower() for w in white_list]) & ~symbols['name'].isin(ban_list)]
        white_list_top_symbols = white_list_symbols.sort_values(by=sorted_column, ascending=False).head(remaining_limit)
        top_symbols.extend([symbol for symbol in white_list_top_symbols['name'].tolist() if symbol not in top_symbols])
        remaining_limit = limit - len(top_symbols)

        if remaining_limit > 0:
            # 나머지 종목에서 선택 (ban_list에 없는 것만)
            non_selected_symbols = symbols[~symbols['name'].isin(top_symbols) & ~symbols['name'].isin(ban_list)]
            non_selected_top_symbols = non_selected_symbols.sort_values(by=sorted_column, ascending=False).head(remaining_limit)
            top_symbols.extend(non_selected_top_symbols['name'].tolist())

    print(f"{user_id} : ban_list : {ban_list}")
    print(f"{user_id} : Final top_symbols: {top_symbols}")
    return top_symbols

async def get_upbit_market_data():
    url = "https://api.upbit.com/v1/market/all"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            markets = await response.json()
    
    krw_markets = [market['market'] for market in markets if market['market'].startswith('KRW-')]
    
    url = "https://api.upbit.com/v1/ticker"
    params = {"markets": ",".join(krw_markets)}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params) as response:
            tickers = await response.json()
    # 변화율을 절대값이 아닌 실제 값으로 가져오기
    market_data = {ticker['market']: ticker['signed_change_rate'] for ticker in tickers}
    
    # 변화율이 높은 것부터 낮은 순서대로 소팅
    sorted_market_data = dict(sorted(market_data.items(), key=lambda item: item[1], reverse=True))
    
    return sorted_market_data



#==============================================================================
# 테스크 관리
#==============================================================================




async def task_completed(task, new_symbol, exchange_name: str, user_id: str):
    print(f'매개변수 확인. task: {task}, new_symbol: {new_symbol}, exchange_name: {exchange_name}, user_id: {user_id}')
    redis = await get_redis_connection()
    try:
        user_key = f'{exchange_name}:user:{user_id}'
        user_data = await redis.hgetall(user_key)

        grid_num = int(user_data.get("grid_num", 20))
        leverage = float(user_data.get("leverage", 1))
        direction = user_data.get("direction", "long")
        initial_capital_json = user_data.get("initial_capital", "[]")
        initial_capital_list = json.loads(initial_capital_json) if isinstance(initial_capital_json, str) else initial_capital_json
        stop_loss = float(user_data.get("stop_loss", 0))
        numbers_to_entry = int(user_data.get("numbers_to_entry", 10))
        running_symbols = set(json.loads(user_data.get('running_symbols', '[]')))
        completed_symbols = set(json.loads(user_data.get('completed_trading_symbols', '[]')))
        tasks = json.loads(user_data.get('tasks', '[]'))

        running_symbols.discard(new_symbol)
        completed_symbols.add(new_symbol)
        if task in tasks:
            tasks.remove(task)
        await redis.hset(user_key, 'running_symbols', json.dumps(list(running_symbols)))
        await redis.hset(user_key, 'completed_trading_symbols', json.dumps(list(completed_symbols)))
        await redis.hset(user_key, 'tasks', json.dumps(tasks))

        print(f"user_id = {user_id}, exchange_name = {exchange_name}, direction = {direction}")

        new_entry_symbols = await get_new_symbols(user_id=user_id, exchange_name=exchange_name, direction=direction, limit=20)
        if new_entry_symbols is None:
            print('종료')
            return

        limit = int(user_data.get("numbers_to_entry", 1))
        
        filtered_symbols = [symbol for symbol in new_entry_symbols if symbol not in completed_symbols]

        print(f"new_entry_symbols 타입: {type(new_entry_symbols)}")
        print(f"new_entry_symbols 내용: {new_entry_symbols}")
        print(f"filtered_symbols 타입: {type(filtered_symbols)}")
        print(filtered_symbols)
        print('새로운 심볼 탐색 ! 확인! ')
        print(f"limit : {limit}")

        is_running = parse_bool(user_data.get('is_running', '0'))
        
        if is_running:
            print(f"running_symbols : {running_symbols}, len : {len(running_symbols)}")
            if len(running_symbols) <= numbers_to_entry:
                for symbol in filtered_symbols[:limit]:
                    print(f"filtered_symbols[:limit] : {filtered_symbols[:limit]}")
                    print(f"symbol {symbol}")
                    symbol_queues = {symbol: asyncio.Queue(maxsize=1)}
                    message = f"🚀 {user_id} 새로운 심볼{new_entry_symbols}에 대한 매매를 시작합니다."
                    await (create_new_task(new_symbol=symbol, symbol_queues=symbol_queues, 
                                                              initial_investment=initial_capital_list, direction=direction, 
                                                              timeframe='15m', grid_num=grid_num, exchange_name=exchange_name,
                                                              leverage=leverage, user_id=user_id, stop_loss=stop_loss, numbers_to_entry = numbers_to_entry, force_restart=False))
                await telegram_message.send_telegram_message(message, exchange_name, user_id)
                await add_user_log(user_id, message)
            else:
                message = f"{numbers_to_entry}보다 많은 포지션을 보유 중입니다. 새로운 포지션 진입을 종료합니다."
                await telegram_message.send_telegram_message(message, exchange_name, user_id)                
        else:
            print("{user_id} : 테스크가 종료 되었습니다.")
            message = f"🚀 {user_id} 매매가 종료되었습니다.\n모든 트레이딩이 종료되었습니다."
            await telegram_message.send_telegram_message(message, exchange_name, user_id)
            await add_user_log(user_id, message)
            return
    except Exception as e:
        print(f"An error occurred on task_completed: {e}")
        print(traceback.format_exc())
    finally:
        await redis.close()

async def get_new_symbols(user_id, exchange_name, direction, limit):
    redis = await get_redis_connection()
    try:
        user_key = f'{exchange_name}:user:{user_id}'
        user_data = await redis.hgetall(user_key)

        is_running = parse_bool(user_data.get('is_running', '0'))
        if not is_running:
            print('프로세스가 종료되었습니다.')
            return None

        new_trading_symbols = await get_top_symbols(user_id, exchange_name=exchange_name, direction=direction, limit=limit)

        running_symbols = set(json.loads(user_data.get('running_symbols', '[]')))
        completed_trading_symbols = set(json.loads(user_data.get('completed_trading_symbols', '[]')))

        new_entry_symbols = [symbol for symbol in new_trading_symbols 
                             if symbol not in running_symbols and symbol not in completed_trading_symbols]

        return new_entry_symbols

    except Exception as e:
        print(f"An error occurred on get_new_symbols: {e}")
        print(traceback.format_exc())
        return None
    finally:
        await redis.close()



async def cancel_user_limit_orders(user_id, exchange_name):
    print('========================[CANCEL ORDERS REQUEST]========================')
    redis = await get_redis_connection()
    user_key = f'{exchange_name}:user:{user_id}'
    try : 
        user_data = await redis.hgetall(user_key)
        if not user_data:
            print(f"User ID {user_id} not found in Redis")
            return
        running_symbols = json.loads(user_data.get('running_symbols', '[]'))
        #symbols_to_remove = set()
        for symbol_name in running_symbols:
            await strategy.cancel_all_limit_orders(exchange_name, symbol_name, user_id)
            #symbols_to_remove.add(symbol_name)
        print(f"{user_id}의 모든 Limit Order가 취소되었습니다.")
    except Exception as e:
        print(f"An error occurred in cancel_user_limit_orders: {e}")
        print(traceback.format_exc())
        raise e

async def cancel_tasks(user_id, exchange_name, close_positions = False):
    print('========================[GRID MAIN CANCEL REQUEST]========================')
    redis = await get_redis_connection()
    try:
        user_key = f'{exchange_name}:user:{user_id}'
        
        # Get user data from Redis
        user_data = await redis.hgetall(user_key)
        if not user_data:
            print(f"User ID {user_id} not found in Redis")
            return
        user_running_state = parse_bool(user_data.get('is_running', '0'))
        print(f"User {user_id} is running: {user_running_state}")

        if not user_running_state:
            print("프로세스가 이미 종료되었습니다.")
            await redis.hset(user_key, 'is_running', '0')
            print(f"Set is_running to 0. New state: {await redis.hget(user_key, 'is_running')}")
            return

        running_symbols = json.loads(user_data.get('running_symbols', '[]'))
        symbols_to_remove = set()

        for symbol_name in running_symbols:
            await strategy.cancel_all_limit_orders(exchange_name, symbol_name, user_id)
            symbols_to_remove.add(symbol_name)

        updated_running_symbols = list(set(running_symbols) - symbols_to_remove)
        await redis.hset(user_key, 'running_symbols', json.dumps(updated_running_symbols))
        await redis.hset(user_key, 'is_running', '0')
        await redis.hset(user_key, 'is_stopped', '1')

        # Cancel all tasks
        tasks = json.loads(user_data.get('tasks', '[]'))
        for task_name in tasks:
            for task in asyncio.all_tasks():
                if task.get_name() == task_name and not task.done():
                    task.cancel()
        
        print("모든 트레이딩 태스크가 취소되었습니다.")

        # Wait for all cancelled tasks to finish
        cancelled_tasks = [task for task in asyncio.all_tasks() if task.cancelled()]
        await asyncio.gather(*cancelled_tasks, return_exceptions=True)
        print("모든 태스크가 취소되었습니다.")

        # Clear the tasks list in Redis
        await redis.hset(user_key, 'tasks', '[]')
        await redis.hset(user_key, 'completed_trading_symbols', '[]')

        # Update user info in Redis

        #print(f"Updated user data: {await redis.hgetall(user_key)}")

    except Exception as e:
        print(f"{user_id} : An error occurred in cancel_tasks: {e}")
        print(traceback.format_exc())
        raise e
    finally:
        await redis.hset(user_key, 'is_running', '0')
        #await redis.aclose()



# =======[GET SYMBOL 심볼 분석 끝]=======





def summarize_trading_results(exchange_name, direction):
    
    # 경로 패턴을 사용하여 해당 거래소 폴더 내의 모든 CSV 파일을 찾습니다.
    exchange_name = str(exchange_name)
    print(f"{exchange_name}의 거래 전략 요약을 시작합니다.")
    pattern = str(path_helper.grid_dir / exchange_name / direction / "trading_strategy_results_*.csv")
    print(f"패턴: {pattern}")
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
    try:
        print(f"path_helper.grid_dir : {path_helper.grid_dir}")
        summary_df = pd.DataFrame(results).infer_objects()  # infer_objects() 메서드 추가
        summary_file_path = path_helper.grid_dir / exchange_name / direction / f"{exchange_name}_summary_trading_results.csv"
        summary_df.to_csv(summary_file_path, index=False)
        print(f"{exchange_name}의 거래 전략 요약이 완료되었습니다. 파일 경로: {summary_file_path}")
    except Exception as e:
        print(f"An error occurred24: {e}")
        print(traceback.format_exc())




# ==============================================================================
# Main 메인
# ==============================================================================
#
#async def trading_loop(exchange_name, user_id, initial_investment, direction, timeframe, grid_num, leverage, stop_loss, custom_stop, numbers_to_entry):
#    trading_semaphore = asyncio.Semaphore(numbers_to_entry)  # Limit concurrent operations
#    symbol_queues = {}
#    tasks = []
#    completed_symbols = set()
#    running_symbols = set()
#
#    while True:
#        is_running = await get_user_data(exchange_name, user_id, "is_running")
#        if not is_running:
#            break
#
#        async with trading_semaphore:
#            try:
#                # Get new symbols
#                potential_symbols = await get_top_symbols(user_id, exchange_name, direction, limit=10)
#                new_symbols = [s for s in potential_symbols if s not in completed_symbols and s not in running_symbols]
#
#                if new_symbols:
#                    created_tasks = await create_tasks(new_symbols, symbol_queues, initial_investment, direction, timeframe, grid_num, exchange_name, leverage, user_id, stop_loss, numbers_to_entry, custom_stop)
#                    if created_tasks:
#                        tasks.extend(created_tasks)
#                        running_symbols.update(new_symbols)
#                        print(f"Created and managed {len(created_tasks)} new tasks.")
#                    else:
#                        print("No new tasks were created.")
#                else:
#                    print("No suitable new symbols found.")
#
#            except Exception as e:
#                print(f"An error occurred during task creation: {e}")
#                print(traceback.format_exc())
#
#            # Process completed tasks
#            done_tasks = [task for task in tasks if task.done()]
#            for task in done_tasks:
#                try:
#                    result = await task
#                    if result:
#                        completed_symbols.add(result)
#                        running_symbols.remove(result)
#                        print(f"Completed symbol: {result}")
#                except Exception as task_e:
#                    print(f"Error processing completed task: {task_e}")
#                tasks.remove(task)
#
#            # Replace completed or failed tasks
#            if len(running_symbols) < 5:  # Maintain at least 5 running tasks
#                replacement_needed = 5 - len(running_symbols)
#                potential_replacement_symbols = await get_top_symbols(user_id, exchange_name, direction, limit=replacement_needed + 5)
#                replacement_symbols = [s for s in potential_replacement_symbols if s not in completed_symbols and s not in running_symbols][:replacement_needed]
#                
#                if replacement_symbols:
#                    print(f"Attempting to add replacement symbols: {replacement_symbols}")
#                    replacement_tasks = await create_tasks(replacement_symbols, symbol_queues, initial_investment, direction, timeframe, grid_num, exchange_name, leverage, user_id, stop_loss,numbers_to_entry, custom_stop)
#                    if replacement_tasks:
#                        tasks.extend(replacement_tasks)
#                        running_symbols.update(replacement_symbols)
#                        print(f"Successfully added {len(replacement_tasks)} replacement tasks.")
#                    else:
#                        print("No replacement tasks were created.")
#                else:
#                    print("No suitable replacement symbols found.")
#
#        await asyncio.sleep(60)  # Wait for 1 minute before the next iteration
#
#    # Clean up when the loop ends
#    for task in tasks:
#        task.cancel()
#    await asyncio.gather(*tasks, return_exceptions=True)


#================================================================================================
# TASKS
#================================================================================================
async def create_symbol_task(new_symbol, symbol_queues, initial_investment, direction, grid_num, exchange_name, leverage, timeframe, stop_loss, numbers_to_entry, user_id, exchange_instance, force_restart):
    grid_levels = await periodic_analysis.calculate_grid_logic(direction = direction,grid_num = grid_num, exchange_name=exchange_name, symbol=new_symbol, user_id=user_id, exchange_instance=exchange_instance)
    try:
        if grid_levels is None:
            return None

        queue = symbol_queues.get(new_symbol) or asyncio.Queue(maxsize=1)
        symbol_queues[new_symbol] = queue
        print(f"🤖Creating task for symbol {new_symbol}")
        task = asyncio.create_task(run_task(new_symbol, queue, initial_investment, direction, grid_levels, grid_num, exchange_name, leverage, timeframe, stop_loss, numbers_to_entry, user_id, exchange_instance, force_restart))
        #원본이, 의의 asyncio.create_task.그런데 이렇게하면 끝날 때까지 기다리지 않기 때문에, await로 아래처럼 수정해봄. 0928
        #task = await (run_task(new_symbol, queue, initial_investment, direction, grid_levels, grid_num, exchange_name, leverage, timeframe, stop_loss, numbers_to_entry, user_id, exchange_instance, force_restart))
        task_name = f"task_{new_symbol}_{user_id}"
        task.set_name(task_name)
    except Exception as e:
        print(f"An error occurred in create_symbol_task: {e}")
        print(traceback.format_exc())
        return None, new_symbol
    
    return task, task_name

async def create_monitoring_tasks(exchange_name, user_id, stop_loss, custom_stop):
    tasks = []
    if stop_loss is not None and stop_loss > 0 and exchange_name != 'upbit':
        monitor_sl_task = asyncio.create_task(monitor_positions(exchange_name, user_id))
        monitor_sl_task_name = f"monitor_sl_{user_id}"
        monitor_sl_task.set_name(monitor_sl_task_name)
        tasks.append((monitor_sl_task, monitor_sl_task_name))

    if custom_stop is not None:
        monitor_custom_stop_task = asyncio.create_task(monitor_custom_stop(exchange_name, user_id, custom_stop))
        monitor_custom_stop_task_name = f"monitor_custom_stop_{user_id}"
        monitor_custom_stop_task.set_name(monitor_custom_stop_task_name)
        tasks.append((monitor_custom_stop_task, monitor_custom_stop_task_name))

    return tasks

async def create_recovery_tasks(user_id, exchange_name, direction, symbol_queues, initial_investment, timeframe, grid_num, leverage, stop_loss, numbers_to_entry, custom_stop):
    try:
        is_running = await get_user_data(exchange_name, user_id, "is_running")
        if not is_running:
            print(f"Trading process is not running for user {user_id}. Skipping recovery.")
            return []

        potential_recovery_symbols = await get_top_symbols(user_id, exchange_name, direction, limit=40)
        running_symbols = set(await get_user_data(exchange_name, user_id, 'running_symbols'))
        completed_symbols = set(await get_user_data(exchange_name, user_id, 'completed_trading_symbols'))
        
        exchange_instance = await get_exchange_instance(exchange_name, user_id)
        
        new_symbols = [s for s in potential_recovery_symbols if s not in completed_symbols and s not in running_symbols]
        
        if not new_symbols:
            print(f"No new symbols available for recovery for user {user_id}.")
            return []

        print(f"Attempting recovery with symbols: {new_symbols[:1]}")
        
        try:
            recovery_tasks = await create_tasks(
                new_symbols[:1], symbol_queues, initial_investment, direction, timeframe, 
                grid_num, exchange_name, leverage, user_id, stop_loss, numbers_to_entry, 
                custom_stop=custom_stop, exchange_instance=exchange_instance
            )
            
            if recovery_tasks:
                print(f"Successfully created {len(recovery_tasks)} recovery tasks for user {user_id}.")
                await telegram_message.send_telegram_message(
                    f"{user_id}: 새로운 심볼 {new_symbols[:1]}로 재진입", 
                    exchange_name, user_id, debug=True
                )
                return recovery_tasks
            else:
                print(f"No recovery tasks were created for user {user_id}.")
                return []
        
        except Exception as e:
            print(f"Error creating recovery tasks for user {user_id}: {e}")
            print(traceback.format_exc())
            return []

    except Exception as e:
        print(f"An error occurred in create_recovery_tasks for user {user_id}: {e}")
        print(traceback.format_exc())
        return []

async def initialize_and_load_user_data(redis, user_key):
    await initialize_user_data(redis, user_key)
    user_data = await get_user_data_from_redis(redis, user_key)
    
    running_symbols = set(json.loads(user_data.get('running_symbols', '[]')))
    completed_symbols = set(json.loads(user_data.get('completed_trading_symbols', '[]')))
    existing_tasks = json.loads(user_data.get('tasks', '[]'))
    
    return running_symbols, completed_symbols, existing_tasks


async def create_individual_task(
    new_symbol, symbol_queues, initial_investment, direction, grid_num, 
    exchange_name, leverage, timeframe, stop_loss, numbers_to_entry, 
    user_id, exchange_instance, force_restart, redis, user_key
):
    #print(f'{user_id} : ❗️❗️create_individual_task, new_symbol: {new_symbol}')
    try:
        await asyncio.sleep(random.random())
        # Check if symbol is already completed or running
        user_data = await get_user_data_from_redis(redis, user_key)
        completed_symbols = set(json.loads(user_data.get('completed_trading_symbols', '[]')))
        running_symbols = set(json.loads(user_data.get('running_symbols', '[]')))
        if new_symbol in completed_symbols or new_symbol in running_symbols:
            print(f"Symbol {new_symbol} is already completed or running. Skipping.")
            
            return None, new_symbol
        
        
        # Add to running symbols
        running_symbols.add(new_symbol)
        await redis.hset(user_key, 'running_symbols', json.dumps(list(running_symbols)))
        
        # Create the trading task
        ####1008 : 여기를, await가 아니라, asyncio.create_task로 변경해봄.
        task = asyncio.create_task(create_symbol_task(
            new_symbol, symbol_queues, initial_investment, direction, grid_num, 
            exchange_name, leverage, timeframe, stop_loss, numbers_to_entry, 
            user_id, exchange_instance, force_restart
        ))
        if task:
            print(f"Starting trading for {new_symbol}")
            return task
        else:
            # If task creation failed, update symbols accordingly
            running_symbols.remove(new_symbol)
            completed_symbols.add(new_symbol)
            await redis.hset(user_key, 'running_symbols', json.dumps(list(running_symbols)))
            await redis.hset(user_key, 'completed_trading_symbols', json.dumps(list(completed_symbols)))
            return None, new_symbol
    except Exception as e:
        print(f"{user_id} : Error creating task for {new_symbol}: {e}")
        print(traceback.format_exc())
        return None
    
    
async def handle_skipped_symbols(
    skipped_symbols, new_symbols, symbol_queues, initial_investment, direction, timeframe, 
    grid_num, exchange_name, leverage, user_id, stop_loss, numbers_to_entry, 
    exchange_instance, custom_stop, recursion_depth, force_restart, 
    created_tasks
):
    print(f'{user_id} : ❗️❗️handle_skipped_symbols')
    if skipped_symbols and recursion_depth < 3:
        additional_symbols_needed = len(new_symbols) + len(skipped_symbols) + 5
        potential_symbols = await get_top_symbols(
            user_id=user_id, 
            exchange_name=exchange_name, 
            direction=direction, 
            limit=additional_symbols_needed
        )
        existing_symbols = set(new_symbols) | set(skipped_symbols)
        new_additional_symbols = [symbol for symbol in potential_symbols if symbol not in existing_symbols]
        print(f"🚨🚨skipped_symbols: {skipped_symbols}에 대해 새로운 시도. 추가 심볼: {new_additional_symbols}")
        if new_additional_symbols:
            print(f"Adding {len(new_additional_symbols)} new symbols to replace skipped ones.")
            additional_tasks = await create_tasks(
                new_symbols=new_additional_symbols,
                symbol_queues=symbol_queues,
                initial_investment=initial_investment,
                direction=direction,
                timeframe=timeframe,
                grid_num=grid_num,
                exchange_name=exchange_name,
                leverage=leverage,
                user_id=user_id,
                stop_loss=stop_loss,
                numbers_to_entry=numbers_to_entry,
                exchange_instance=exchange_instance,
                custom_stop=custom_stop,
                recursion_depth=recursion_depth + 1,
                force_restart=force_restart
            )
            created_tasks.extend(additional_tasks)
            return additional_tasks
            
            
async def process_new_symbols(
    new_symbols, symbol_queues, initial_investment, direction, timeframe, 
    grid_num, exchange_name, leverage, user_id, stop_loss, numbers_to_entry, 
    exchange_instance, custom_stop, recursion_depth, force_restart, 
    redis, user_key
):
    created_tasks = []
    tasks = []
    testing_tasks = []
    skipped_symbols = []
    try:
        for new_symbol in new_symbols:
            task = asyncio.create_task(create_individual_task(
                new_symbol, symbol_queues, initial_investment, direction, grid_num, 
                exchange_name, leverage, timeframe, stop_loss, numbers_to_entry, 
                user_id, exchange_instance, force_restart, redis, user_key
            ), name=f"task_{new_symbol}_{user_id}")
            task_name = new_symbol
            if task :
                created_tasks.append(task)
                tasks.append(task_name)
                print(f"새로 task {task_name} 추가 for symbol {new_symbol}")
                testing_tasks.append(task)
                
        
        await redis.hset(user_key, 'tasks', json.dumps(tasks))
        await redis.hset(user_key, 'tasks_symbol', json.dumps(tasks)) #<--- symbol name이 저장되지 않고 테스크 객체가 저장되어서. 
        #print("Tasks to store:", testing_tasks)
        task_names = [task.get_name() for task in testing_tasks]
        await redis.hset(user_key, 'tasks_testing', json.dumps(task_names))
    except Exception as e:
        print(f"{user_id} : Error creating tasks: {e}")
        print(traceback.format_exc())
        
    # Handle skipped symbols and potentially create additional tasks
    # Note: The original code added skipped symbols to a list but didn't use them directly.
    # This part can be adjusted based on specific requirements.
    # For now, we'll assume skipped_symbols are the ones that failed during task creation
    try:
        skipped_symbols = [symbol for symbol in new_symbols if symbol not in tasks]
        await handle_skipped_symbols(
            skipped_symbols, new_symbols, symbol_queues, initial_investment, direction, timeframe, 
            grid_num, exchange_name, leverage, user_id, stop_loss, numbers_to_entry, 
            exchange_instance, custom_stop, recursion_depth, force_restart, 
            created_tasks
        )
    except Exception as e:
        print(f"{user_id} : Error handling skipped symbols: {e}")
        traceback.print_exc()
        
    
    return created_tasks


async def monitor_and_handle_tasks(
    created_tasks, exchange_name, user_id, symbol_queues, initial_investment, 
    direction, timeframe, grid_num, leverage, stop_loss, numbers_to_entry, 
    exchange_instance, custom_stop, user_key, redis
):
    while created_tasks:
        done, pending = await asyncio.wait(created_tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task_name = task.get_name()
            if task_name in created_tasks:
                is_running = await get_user_data(exchange_name, user_id, "is_running")
                if not is_running:
                    print('프로세스가 종료되었습니다.')
                    return created_tasks
                
                # Remove completed task
                created_tasks.remove(task)
                await redis.hset(user_key, 'tasks', json.dumps([t.get_name() for t in created_tasks]))
                
                # Handle task completion
                await handle_task_completion(task, task_name, exchange_name, user_id, redis)
                
                # Check if still running
                is_running = await get_user_data(exchange_name, user_id, "is_running")
                if not is_running:
                    print('프로세스가 종료되었습니다.')
                    return created_tasks
                
                # Potentially create recovery tasks if necessary
                if len(created_tasks) <= numbers_to_entry and is_running:
                    try:
                        recovery_tasks = await create_recovery_tasks(
                            user_id, exchange_name, direction, symbol_queues, initial_investment, 
                            timeframe, grid_num, leverage, stop_loss, numbers_to_entry, custom_stop
                        )
                        if recovery_tasks:
                            created_tasks.extend(recovery_tasks)
                            await redis.hset(user_key, 'tasks', json.dumps([t.get_name() for t in created_tasks]))
                    except Exception as e:
                        print(f"{user_id} : Error during recovery: {e}")
                        print(traceback.format_exc())
    return created_tasks


async def create_tasks(
    new_symbols, symbol_queues, initial_investment, direction, timeframe, grid_num, 
    exchange_name, leverage, user_id, stop_loss, numbers_to_entry, 
    exchange_instance, custom_stop=False, recursion_depth=0, force_restart=False
):
    redis = await get_redis_connection()
    user_key = f'{exchange_name}:user:{user_id}'
    
    try:
        # 사용자 데이터 초기화 및 로드
        running_symbols, completed_symbols, existing_tasks = await initialize_and_load_user_data(redis, user_key)
        
        if len(running_symbols) > numbers_to_entry:
            print(f"Running symbols count {len(running_symbols)} is greater than or equal to numbers_to_entry {numbers_to_entry}. Skipping.")
            return []
        
        # 새 심볼에 대한 태스크 생성
        created_tasks = await process_new_symbols(
            new_symbols, symbol_queues, initial_investment, direction, timeframe, 
            grid_num, exchange_name, leverage, user_id, stop_loss, numbers_to_entry, 
            exchange_instance, custom_stop, recursion_depth, force_restart, 
            redis, user_key
        )
        #print(f"created tasks: {created_tasks}, sy")
        # 모니터링 태스크 생성
        monitoring_tasks = await create_monitoring_tasks(exchange_name, user_id, stop_loss, custom_stop)
        for task, task_name in monitoring_tasks:
            created_tasks.append(task)
        
        await redis.hset(user_key, 'tasks', json.dumps([task.get_name() for task in created_tasks]))
        
        # 태스크 완료 처리
        await monitor_and_handle_tasks(
            created_tasks, exchange_name, user_id, symbol_queues, initial_investment, 
            direction, timeframe, grid_num, leverage, stop_loss, numbers_to_entry, 
            exchange_instance, custom_stop, user_key, redis
        )
        
        return created_tasks
    except Exception as e:
        print(f"{user_id} : An error occurred in create_tasks: {e}")
        print(traceback.format_exc())
        return []

#async def create_tasks(new_symbols, symbol_queues, initial_investment, direction, timeframe, grid_num, exchange_name, leverage, user_id, stop_loss, numbers_to_entry, exchange_instance, custom_stop=False, recursion_depth=0, force_restart=False):
#    redis = await get_redis_connection()
#    user_key = f'{exchange_name}:user:{user_id}'
#    
#    try:
#        await initialize_user_data(redis, user_key)
#        user_data = await get_user_data_from_redis(redis, user_key)
#        
#        running_symbols = set(json.loads(user_data.get('running_symbols', '[]')))
#        completed_symbols = set(json.loads(user_data.get('completed_trading_symbols', '[]')))
#        existing_tasks = json.loads(user_data.get('tasks', '[]'))
#        
#        created_tasks = []
#        tasks = []
#        skipped_symbols = []
#        
#        if len(running_symbols) <= numbers_to_entry:
#            for new_symbol in new_symbols:
#                await asyncio.sleep(random.random())
#                if new_symbol in completed_symbols or new_symbol in running_symbols:
#                    print(f"Symbol {new_symbol} is already completed or running. Skipping.")
#                    skipped_symbols.append(new_symbol)
#                    continue
#                
#                try:
#                    running_symbols.add(new_symbol)
#                    await redis.hset(user_key, 'running_symbols', json.dumps(list(running_symbols)))
#                    
#                    task, task_name = await create_symbol_task(new_symbol, symbol_queues, initial_investment, direction, grid_num, exchange_name, leverage, timeframe, stop_loss, numbers_to_entry, user_id, exchange_instance, force_restart)
#                    
#                    if task:
#                        tasks.append(task_name)
#                        created_tasks.append(task)
#                        await redis.hset(user_key, 'tasks', json.dumps(tasks))
#                        print(f"Starting trading for {new_symbol}")
#                    else:
#                        running_symbols.remove(new_symbol)
#                        completed_symbols.add(new_symbol)
#                        skipped_symbols.append(new_symbol)
#                
#                except Exception as e:
#                    print(f"{user_id} : Error creating task for {new_symbol}: {e}")
#                    print(traceback.format_exc())
#                    continue
#            
#            await redis.hset(user_key, 'running_symbols', json.dumps(list(running_symbols)))
#            
#            if skipped_symbols and recursion_depth < 3:
#                additional_symbols_needed = len(new_symbols) + len(skipped_symbols) + 5
#                potential_symbols = await get_top_symbols(user_id=user_id, exchange_name=exchange_name, direction=direction, limit=additional_symbols_needed)
#                existing_symbols = set(new_symbols) | set(running_symbols) | set(completed_symbols) | set(skipped_symbols)
#                new_symbols = [symbol for symbol in potential_symbols if symbol not in existing_symbols]
#                
#                if new_symbols:
#                    print(f"Adding {len(new_symbols)} new symbols to replace skipped ones.")
#                    additional_tasks = await create_tasks(new_symbols, symbol_queues, initial_investment, direction, timeframe, grid_num, exchange_name, leverage, user_id = user_id,  stop_loss = stop_loss, numbers_to_entry = numbers_to_entry, exchange_instance = exchange_instance, custom_stop=custom_stop, recursion_depth=recursion_depth + 1)
#                    created_tasks.extend(additional_tasks)
#        
#        else:
#            print(f"Running symbols count {len(running_symbols)} is greater than or equal to numbers_to_entry {numbers_to_entry}. Skipping.")
#            return []
#        
#        monitoring_tasks = await create_monitoring_tasks(exchange_name, user_id, stop_loss, custom_stop)
#        for task, task_name in monitoring_tasks:
#            tasks.append(task_name)
#            created_tasks.append(task)
#        
#        await redis.hset(user_key, 'tasks', json.dumps(tasks))
#        
#        while created_tasks:
#            done, pending = await asyncio.wait(created_tasks, return_when=asyncio.FIRST_COMPLETED)
#            for task in done:
#                task_name = task.get_name()
#                if task_name in tasks:
#                    is_running = await get_user_data(exchange_name, user_id, "is_running")
#                    if not is_running:
#                        print('프로세스가 종료되었습니다.')
#                        return created_tasks
#                    
#                    tasks.remove(task_name)
#                    await redis.hset(user_key, 'tasks', json.dumps(tasks))
#                    await handle_task_completion(task, new_symbol, exchange_name, user_id, redis)
#                    created_tasks.remove(task)
#                    
#                    
#                    is_running = await get_user_data(exchange_name, user_id, "is_running")
#                    if not is_running:
#                        print('프로세스가 종료되었습니다.')
#                        return created_tasks
#                    
#                    if len(running_symbols) <= numbers_to_entry and is_running:
#                        try:
#                            recovery_tasks = await create_recovery_tasks(user_id, exchange_name, direction, symbol_queues, initial_investment, timeframe, grid_num, leverage, stop_loss, numbers_to_entry, custom_stop)
#                            if recovery_tasks:
#                                created_tasks.extend(recovery_tasks)
#                                tasks.extend([task.get_name() for task in recovery_tasks])
#                                await redis.hset(user_key, 'tasks', json.dumps(tasks))
#                        except Exception as e:
#                            print(f"{user_id} : Error during recovery: {e}")
#                            print(traceback.format_exc())
#        
#        return created_tasks
#    except Exception as e:
#        print(f"{user_id} : An error occurred in create_tasks: {e}")
#        print(traceback.format_exc())
#        return []
#    #finally:
#    #    await redis.close()
#    
async def handle_task_completion(task: asyncio.Task, new_symbol: str, exchange_name: str, user_id: str, redis: aioredis.Redis) -> None:
    user_key = f'{exchange_name}:user:{user_id}'
    try:
        async with redis.pipeline(transaction=True) as pipe:
            # Fetch and update running symbols
            pipe.hget(user_key, 'running_symbols')
            pipe.hget(user_key, 'completed_trading_symbols')
            results = await pipe.execute()

            running_symbols = json.loads(results[0]) if results[0] else []
            completed_symbols = json.loads(results[1]) if results[1] else []

            if new_symbol in running_symbols:
                running_symbols.remove(new_symbol)
            
            completed_symbols.append(new_symbol)

            # Update both lists in Redis
            pipe.hset(user_key, 'running_symbols', json.dumps(running_symbols))
            pipe.hset(user_key, 'completed_trading_symbols', json.dumps(completed_symbols))
            await pipe.execute()

        logging.info(f"Task for {new_symbol} completed. Running symbols: {running_symbols}")
    except json.JSONDecodeError as e:
        logging.error(f"JSON decoding error: {e}")
    except aioredis.RedisError as e:
        logging.error(f"Redis error: {e}")
    except Exception as e:
        logging.exception(f"Unexpected error handling task completion: {e}")


async def create_new_task(new_symbol, symbol_queues, initial_investment, direction, timeframe, grid_num, exchange_name, leverage, user_id, stop_loss, numbers_to_entry, custom_stop=False, force_restart=False):
    user_key = f'{exchange_name}:user:{user_id}'
    try:
        # 사용자 데이터 가져오기
        user_data = await get_user_data(exchange_name, user_id)
        tasks = user_data.get('tasks', [])
        running_symbols = set(user_data.get('running_symbols', []))
        is_running = parse_bool(user_data.get('is_running', '0'))

        if not is_running:
            print(f"Trading process is not running for user {user_id}. Skipping new task creation.")
            return

        if len(running_symbols) > numbers_to_entry:
            print(f"Maximum number of running symbols reached for user {user_id}. Skipping new task creation.")
            return

        # Exchange 인스턴스 가져오기
        exchange_instance = await get_exchange_instance(exchange_name, user_id)

        # 새 심볼 추가 및 그리드 레벨 계산
        running_symbols.add(new_symbol)
        await redis_database.add_running_symbol(user_id, new_symbol, exchange_name)
        print(f"Adding new task for symbol: {new_symbol}")

        grid_levels = await calculate_grid_levels(direction, grid_num, new_symbol, exchange_name, user_id, exchange_instance)

        # 메인 태스크 생성
        queue = symbol_queues[new_symbol]
        main_task = asyncio.create_task(run_task(new_symbol, queue, initial_investment, direction, grid_levels, grid_num, exchange_name, leverage, timeframe, stop_loss, numbers_to_entry, user_id, exchange_instance=exchange_instance, force_restart=force_restart))
        tasks.append(main_task)
        await redis_database.add_tasks(user_id, main_task, exchange_name)

        # Custom Stop 모니터링 태스크 생성 (필요한 경우)
        if custom_stop:
            await create_custom_stop_task(exchange_name, user_id, custom_stop, tasks)

        # Stop Loss 모니터링 태스크 생성 (필요한 경우)
        if stop_loss is not None and stop_loss > 0:
            await create_stop_loss_task(exchange_name, user_id, tasks)

        print(f"Successfully started trading for {new_symbol}")
        return main_task

    except Exception as e:
        print(f"An error occurred in create_new_task for user {user_id}, symbol {new_symbol}: {e}")
        print(traceback.format_exc())
        if new_symbol in running_symbols:
            running_symbols.remove(new_symbol)
            await redis_database.remove_running_symbol(user_id, new_symbol, exchange_name)
        return None


async def create_stop_loss_task(exchange_name, user_id, tasks):
    try:
        monitor_sl_task = asyncio.create_task(monitor_positions(exchange_name, user_id))
        tasks.append(monitor_sl_task)
        await redis_database.add_tasks(user_id, monitor_sl_task, exchange_name)
        print(f"Created stop loss monitoring task for user {user_id}")
    except Exception as e:
        print(f"Error creating stop loss task for user {user_id}: {e}")
        print(traceback.format_exc())


async def create_custom_stop_task(exchange_name, user_id, custom_stop, tasks):
    try:
        monitor_custom_stop_task = asyncio.create_task(monitor_custom_stop(exchange_name, user_id, custom_stop))
        tasks.append(monitor_custom_stop_task)
        await redis_database.add_tasks(user_id, monitor_custom_stop_task, exchange_name)
        print(f"Created custom stop monitoring task for user {user_id}")
    except Exception as e:
        print(f"Error creating custom stop task for user {user_id}: {e}")
        print(traceback.format_exc())

async def calculate_grid_levels(direction, grid_num, symbol, exchange_name, user_id, exchange_instance):
    try:
        return await periodic_analysis.calculate_grid_logic(direction, grid_num=grid_num, symbol=symbol, exchange_name=exchange_name, user_id=user_id, exchange_instance=exchange_instance)
    except Exception as e:
        print(f"{user_id} : Error calculating grid levels for {symbol}: {e}")
        print(traceback.format_exc())
        return None



#==============================================================================


async def run_task(symbol, queue, initial_investment, direction, grid_levels, grid_num, exchange_name, leverage, timeframe, stop_loss, numbers_to_entry, user_id, exchange_instance, force_restart = False):
    redis = await get_redis_connection()
    print(f"Running task for {symbol}")
    try:
        user_key = f'{exchange_name}:user:{user_id}'
        if not await redis.exists(user_key):
            await redis.hset(user_key, mapping = {
                'is_running': '1',
                'tasks': '[]',
                'running_symbols': '[]',
                'completed_trading_symbols': '[]'
            })

        # Get user data from Redis
        user_data = await redis.hgetall(user_key)
        user_data = {k.decode() if isinstance(k, bytes) else k: v.decode() if isinstance(v, bytes) else v for k, v in user_data.items()}
        running_symbols = set(json.loads(user_data.get('running_symbols', '[]')))
        tasks = json.loads(user_data.get('tasks', '[]'))
        is_running = user_data.get('is_running') == '1'
        
        
        
        if is_running and len(running_symbols) <= numbers_to_entry:
            if exchange_name in ['binance', 'bitget', 'okx'] and int(leverage) > 1:
                try:
                    await asyncio.sleep(random.uniform(0.8, 2.0))
                    await retry_async(strategy.change_leverage, exchange_name, symbol, leverage, user_id)
                except Exception as e:
                    print(f"Error changing leverage for {symbol}: {e}")
                    print(traceback.format_exc())
                    return symbol
            try:
                user_key = f'{exchange_name}:user:{user_id}'
                
                await asyncio.sleep(random.uniform(1, 1.7))
                
                #기존 로직 0726 0208
                ws_task = asyncio.create_task(ws_client(exchange_name, symbol, queue, user_id))
                order_task = asyncio.create_task(place_grid_orders(symbol, initial_investment, direction, grid_levels, queue, grid_num, leverage, exchange_name, user_id, force_restart))
                print('💫Task created for ', symbol)
                tasks = json.loads(await redis.hget(user_key, 'tasks') or '[]')
                tasks.extend([str(ws_task.get_name()), str(order_task.get_name())])
                await redis.hset(user_key, 'tasks', json.dumps(tasks))
                results = await asyncio.gather(ws_task, order_task, return_exceptions=True)
                
                #ws_task = asyncio.create_task(ws_client(exchange_name, symbol, queue, user_id))
                #order_task = asyncio.create_task(place_grid_orders(symbol, initial_investment, direction, grid_levels, queue, grid_num, leverage, exchange_name, user_id, force_restart))
                #tasks = json.loads(await redis.hget(user_key, 'tasks') or '[]')
                #tasks.extend(str(order_task.get_name()))
                #await redis.hset(user_key, 'tasks', json.dumps(tasks))
                #results = await asyncio.gather(order_task, return_exceptions=True)    
            
            except Exception as e:
                print(f"Error running tasks for symbol {symbol}: {e}")
                if 'remove' in str(e):
                    print(f"Removing {symbol} from running symbols")
                    return str(e)
                print(traceback.format_exc())
            # Check if user is still running
            is_running = await redis.hget(user_key, 'is_running')
            if is_running is True:
                for result in results:
                    if isinstance(result, QuitException):
                        print("종료? ")
                        await cancel_tasks(user_id, exchange_name)
                        print(f"Task for {symbol} completed. Finding new task...")
                        return symbol
                    else: 
                        print(f"Task for {symbol} failed. Finding new task...")
                        new_task = await task_completed(task=order_task, new_symbol=symbol, symbol_queue=queue, exchange_name=exchange_name, user_id=user_id)
                        return new_task
                #await task_completed(task=order_task, new_symbol=symbol, symbol_queue=queue, exchange_name=exchange_name, user_id=user_id)
                if any(isinstance(result, Exception) for result in results):
                    print(f"Task for {symbol} failed. Finding new task...")
                    return None
                else:
                    print(f"Task for {symbol} completed. Finding new task...")
                    return symbol
            else:
                return None
        return
    
    except Exception as e:
        print(f"{user_id} : Error running tasks for symbol {symbol}: {e}")
        
        print(traceback.format_exc())
        return None


#ONLY FOR OKX API
def check_right_invitee(okx_api, okx_secret, okx_parra):
    import src.utils.check_invitee as check_invitee
    invitee = True
    try:
        invitee, uid = check_invitee.get_uid_from_api_keys(okx_api, okx_secret, okx_parra)
        if invitee:
            return True, uid
        else:
            return False, None
    except Exception as e:
        print(f"Error checking invitee: {e}")
        print(traceback.format_exc())
        return False
    
    
#==============================================================================
# Data Processing
#==============================================================================
    
async def get_user_data(exchange_name: str, user_id: int, field: Optional[str] = None) -> Union[Dict[str, Any], Any]:
    redis = await get_redis_connection()
    user_key = f"{exchange_name}:user:{user_id}"
    
    json_fields = ["tasks", "running_symbols", "completed_trading_symbols", "enter_symbol_amount_list"]
    boolean_fields = ["is_running", "stop_task_only"]
    numeric_fields = ["leverage", "initial_capital"]
    
    def parse_boolean(value: str) -> bool:
        return value.lower() in ('true', '1', 'yes', 'on')
    
    if field:
        value = await redis.hget(user_key, field)
        if value is None:
            return None
        if field in json_fields:
            return json.loads(value)
        elif field in boolean_fields:
            return parse_boolean(value)
        elif field in numeric_fields:
            return float(value)
        else:
            return value
    else:
        data = await redis.hgetall(user_key)
        for key in data:
            if key in json_fields:
                data[key] = json.loads(data[key])
            elif key in boolean_fields:
                data[key] = parse_boolean(data[key])
            elif key in numeric_fields:
                data[key] = float(data[key])
        return data

async def initialize_user_data(redis, user_key):
    if not await redis.exists(user_key):
        await redis.hset(user_key, mapping={
            'is_running': '0',
            'tasks': '[]',
            'running_symbols': '[]',
            'completed_trading_symbols': '[]',
            'stop_task_only': '0',
        })
        
async def get_user_data_from_redis(redis, user_key):
    user_data = await redis.hgetall(user_key)
    return {k.decode('utf-8') if isinstance(k, bytes) else k: 
            v.decode('utf-8') if isinstance(v, bytes) else v 
            for k, v in user_data.items()}




async def update_user_data(exchange_name: str, user_id: int, **kwargs):
    redis = await get_redis_connection()
    user_key = f"{exchange_name}:user:{user_id}"
    
    for key, value in kwargs.items():
        if isinstance(value, (list, set, dict)):
            value = json.dumps(list(value) if isinstance(value, set) else value)
        elif isinstance(value, bool):
            value = str(value).lower()
        else:
            value = str(value)
        await redis.hset(user_key, key, value)


def ensure_user_keys_initialized_old_struc(user_id, enter_symbol_amount_list, grid_num, leverage, stop_loss):
    global user_keys
    if user_id not in user_keys:
        user_keys[user_id] = {
            "api_key": None,
            "api_secret": None,
            "password": None,
            "is_running": False,
            "stop_loss": stop_loss,
            "tasks": [],
            "running_symbols": set(),
            "completed_trading_symbols": set(),
            "initial_capital": enter_symbol_amount_list,
            "grid_num": grid_num,
            "leverage": leverage,
            "symbols": {}
        }
    else:
        if "is_running" not in user_keys[user_id]:
            user_keys[user_id]["is_running"] = False
        if "tasks" not in user_keys[user_id]:
            user_keys[user_id]["tasks"] = []
        if "running_symbols" not in user_keys[user_id]:
            user_keys[user_id]["running_symbols"] = set()
        if "completed_trading_symbols" not in user_keys[user_id]:
            user_keys[user_id]["completed_trading_symbols"] = set()
        if "initial_capital" not in user_keys[user_id]:
            user_keys[user_id]["initial_capital"] = enter_symbol_amount_list
        if "grid_num" not in user_keys[user_id]:
            user_keys[user_id]["grid_num"] = grid_num
        if "leverage" not in user_keys[user_id] and leverage is not None:
            user_keys[user_id]["leverage"] = leverage
        if "stop_loss" not in user_keys[user_id] and stop_loss is not None:
            user_keys[user_id]["stop_loss"] = stop_loss
        if "symbols" not in user_keys[user_id]:
            user_keys[user_id]["symbols"] = {}
    

async def ensure_user_keys_initialized(exchange_name, user_id, enter_symbol_amount_list, grid_num, leverage, stop_loss):
    redis = await get_redis_connection()
    try:
        user_key = f'{exchange_name}:user:{user_id}'
        
        # Check if user exists
        user_exists = await redis.exists(user_key)
        
        if not user_exists:
            # Create new user data
            user_data = {
                "api_key": "",
                "api_secret": "",
                "password": "",
                "is_running": "0",
                "stop_loss": str(stop_loss),
                "tasks": json.dumps([]),
                "running_symbols": json.dumps([]),
                "completed_trading_symbols": json.dumps([]),
                "initial_capital": json.dumps(enter_symbol_amount_list),
                "grid_num": str(grid_num),
                "leverage": str(leverage),
                "symbols": json.dumps({})
            }
            await redis.hset(user_key, mapping = user_data)
        else:
            # Update existing user data
            updates = {}
            
            # Check and update fields if they don't exist
            fields_to_check = [
                ("is_running", "0"),
                ("tasks", json.dumps([])),
                ("running_symbols", json.dumps([])),
                ("completed_trading_symbols", json.dumps([])),
                ("initial_capital", json.dumps(enter_symbol_amount_list)),
                ("grid_num", str(grid_num)),
                ("leverage", str(leverage)),
                ("stop_loss", str(stop_loss)),
                ("symbols", json.dumps({}))
            ]
            
            for field, default_value in fields_to_check:
                if not await redis.hexists(user_key, field):
                    updates[field] = default_value
            
            if updates:
                await redis.hset(user_key, mapping = updates)
        
        # Retrieve and return the user data
        user_data = await redis.hgetall(user_key)
        decoded_data = {}
        return {k.decode() if isinstance(k, bytes) else k: 
        v.decode() if isinstance(v, bytes) else v 
        for k, v in user_data.items()}

    finally:
        await redis.close()
        
        
def encode_value(value):
    if value is None:
        return 'None'
    return json.dumps(value)

def decode_value(value):
    if value == 'None':
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value    

async def ensure_symbol_initialized(exchange_name, user_id, symbol, grid_num):
    redis = await get_redis_connection()
    try:
        user_key = f'{exchange_name}:user:{user_id}'
        # Check if user exists
        if not await redis.exists(user_key):
            raise KeyError(f"User ID {user_id} not found in Redis")

        # Try to get symbol data directly (new structure)
        symbol_key = f'symbol:{symbol}'
        symbol_data = await redis.hget(user_key, symbol_key)

        if symbol_data is None:
            # If not found, try to get all symbols data (old structure)
            all_symbols_data = await redis.hget(user_key, 'symbols')
            if all_symbols_data:
                # Old structure
                user_symbols = json.loads(all_symbols_data)
                if not isinstance(user_symbols, dict):
                    user_symbols = {}
            else:
                # Neither new nor old structure found, initialize new dictionary
                user_symbols = {}

            if symbol not in user_symbols:
                user_symbols[symbol] = {
                    "take_profit_orders_info": {
                        str(n): {
                            "order_id": None,
                            "quantity": 0.0,
                            "target_price": 0.0,
                            "active": False,
                            "side": None
                        } for n in range(0, grid_num + 1)
                    },
                    "last_entry_time": None,
                    "last_entry_size": 0.0,
                    "previous_new_position_size": 0.0
                }
                
                # Initialize order_placed
                order_placed_key = f'{exchange_name}:user:{user_id}:symbol:{symbol}:order_placed'
                if not await redis.exists(order_placed_key):
                    order_placed = {str(n): "false" for n in range(0, grid_num + 1)}
                    await redis.hmset(order_placed_key, order_placed)
                    await redis.expire(order_placed_key, 890)  # 60초 후 만료
                    print(f"Symbol {symbol} and order_placed initialized for user {user_id}")
                order_ids_key = f'{exchange_name}:user:{user_id}:symbol:{symbol}:order_ids'
                if not await redis.exists(order_ids_key):
                    order_ids = {str(n): encode_value(None) for n in range(0, grid_num + 1)}
                    await redis.hmset(order_ids_key, order_ids)
                    #await redis.expire(order_ids_key, 900)  # 60초 후 만료
                    print(f"Symbol {symbol} and order_ids initialized for user {user_id}")
            else:
                print(f"Symbol {symbol} already exists for user {user_id}")
        else:
            print(f"Symbol {symbol} already initialized for user {user_id} in new structure")
            # Check if order_placed exists, if not, initialize it
            order_placed_key = f'{exchange_name}:user:{user_id}:symbol:{symbol}:order_placed'
            if not await redis.exists(order_placed_key):
                order_placed = {str(n): "false" for n in range(0, grid_num + 1)}
                await redis.hmset(order_placed_key, order_placed)
                await redis.expire(order_placed_key, 890)  # 60초 후 만료
                print(f"order_placed initialized for user {user_id} and symbol {symbol}")
    
    except Exception as e:
        print(f"An error occurred while initializing symbol {symbol} for user {user_id}: {e}")
        raise e
    except KeyError as e:
        print(f"KeyError in ensure_symbol_initialized: {e}")
    except json.JSONDecodeError as e:
        print(f"JSON Decode Error in ensure_symbol_initialized: {e}")
        print(f"Raw data: {all_symbols_data if 'all_symbols_data' in locals() else symbol_data}")
    except Exception as e:
        print(f"Unexpected error in ensure_symbol_initialized: {e}")
        print(traceback.format_exc())
    finally:
        await redis.close()



        
async def check_symbol_entry_info(exchange_name, user_id):
    redis = await get_redis_connection()
    try:
        user_key = f'{exchange_name}:user:{user_id}'
        
        # Get user symbols data
        user_symbols_data = await redis.hget(user_key, 'symbols')
        user_symbols = json.loads(user_symbols_data) if user_symbols_data else {}

        for symbol, symbol_info in user_symbols.items():
            last_entry_time = symbol_info.get("last_entry_time")
            last_entry_size = symbol_info.get("last_entry_size")
            print(f"Symbol: {symbol}, Last Entry Time: {last_entry_time}, Last Entry Size: {last_entry_size}")

    except Exception as e:
        print(f"Unexpected error in check_symbol_entry_info: {e}")
        print(traceback.format_exc())
    finally:
        await redis.close()
#==============================================================================
# Main 메인
#==============================================================================
    
async def check_api_permissions(exchange_name, user_id):
    try:
        exchange = await get_exchange_instance(exchange_name, user_id)
        if exchange_name == 'okx':
            positions_data = await exchange.private_get_account_positions()
            logging.info(f"✅ {user_id} API 연결 확인: {exchange_name}")
    except Exception as e : 
        print(f"Error starting: {e}")
        logging.error(f"❌ {user_id} API 연결 실패: {exchange_name}")
        raise e
    ##### TODO : 인스턴스 재활용 부분에선 필요없어서 확인. 
    #finally:
    #    if exchange is not None:
    #        await exchange.close()

async def check_permissions_and_initialize(exchange_name, user_id, enter_symbol_amount_list, grid_num, leverage, stop_loss):
    await check_api_permissions(exchange_name, user_id)
    try:
        await ensure_user_keys_initialized(exchange_name, user_id, enter_symbol_amount_list, grid_num, leverage, stop_loss)
        ensure_user_keys_initialized_old_struc(user_id, enter_symbol_amount_list, grid_num, leverage, stop_loss)
    except Exception as e:
        print(f"Error on initializing user keys: {str(e)}")

async def get_and_format_symbols(exchange_name, user_id, direction, n, force_restart):
    symbols = await get_top_symbols(user_id, exchange_name=exchange_name, direction=direction, limit=n, force_restart=force_restart)
    modified_symbols = modify_symbols(exchange_name, symbols)
    print(symbols)
    return symbols, modified_symbols

def modify_symbols(exchange_name, symbols):
    if exchange_name == 'upbit':
        return [symbol.replace("KRW-", "").replace("USDT", "") for symbol in symbols]
    elif exchange_name == 'bitget':
        return [symbol.replace("KRW-", "").replace("USDT", "") for symbol in symbols]
    elif exchange_name == 'okx':
        return [symbol.replace("-USDT-SWAP", "") for symbol in symbols]
    elif exchange_name == 'bitget_spot':
        return [symbol.replace("KRW-", "").replace("USDT", "") for symbol in symbols]
    elif exchange_name == 'okx_spot':
        return [symbol.replace("-USDT", "") for symbol in symbols]
    elif exchange_name == 'binance_spot':
        return [symbol.replace("KRW-", "").replace("", "") for symbol in symbols]
    else:
        return [symbol.replace("KRW-", "").replace("", "") for symbol in symbols]

async def prepare_initial_messages(exchange_name, user_id, symbols, enter_symbol_amount_list, leverage, total_enter_symbol_amount):
    try:
        currency_symbol = '₩' if exchange_name in ['upbit'] else '$'
        user_id_str = str(user_id)
        symbols_formatted = format_symbols(symbols)
        initial_capital_formatted_list = [f"{amount:,.1f}{currency_symbol}" for amount in enter_symbol_amount_list]
        initial_capital_formatted = "\n".join(
            ', '.join(initial_capital_formatted_list[i:i+4]) for i in range(0, len(initial_capital_formatted_list), 4)
        )
        total_capital_formatted = "{:,.2f}".format(total_enter_symbol_amount)
        total_capital_leveraged_formatted = "{:,.2f}".format(total_enter_symbol_amount * leverage)
        initial_capital_formatted_20x = "{:,.1f}".format(total_enter_symbol_amount * leverage)

        message = (
            f"{user_id} : [{exchange_name.upper()}] 매매 시작 알림\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            f"📊 거래 종목: {symbols_formatted}\n\n"
            f"💰 그리드 당 투입금액: {initial_capital_formatted} $\n\n"
            "📈 투자 요약:\n"
        )
        if leverage != 1:
            message += (
                f"  종목 당 최대 투입 마진 : {total_capital_leveraged_formatted}{currency_symbol}\n"
                f"   ↳ 최대 투입 가능 금액: {initial_capital_formatted_20x}{currency_symbol} ({total_capital_formatted} * {leverage}배)\n"
            )
        else:
            message += (
                f"  종목 당 총 투입 금액: {total_capital_formatted}{currency_symbol}\n"
                f"   ↳ 최대 투입 금액: {initial_capital_formatted_20x}{currency_symbol}*20개\n"
            )
        message += "━━━━━━━━━━━━━━━━━━"
        print(message)
        await send_initial_logs(user_id_str, exchange_name, message)
        return message
    except Exception as e:
        print(f"Error preparing initial messages: {e}")
        print(traceback.format_exc())

def format_symbols(symbols):
    modified_symbols = [f"'{symbol}'" for symbol in symbols]
    return f"[{', '.join(modified_symbols)}]"

async def send_initial_logs(user_id, exchange_name ,message):
    await add_user_log(user_id, message)
    asyncio.create_task(telegram_message.send_telegram_message(message, exchange_name, user_id))

async def handle_completed_tasks(tasks, exchange_name, user_id, completed_symbols, running_symbols, user_key, redis):
    done_tasks = [task for task in tasks if task.done()]
    for task in done_tasks:
        try:
            result = await task
            if result:
                completed_symbols.add(result)
                running_symbols.remove(result)
                await redis.hset(user_key, 'running_symbols', json.dumps(list(running_symbols)))
                await redis.hset(user_key, 'completed_trading_symbols', json.dumps(list(completed_symbols)))
                print(f"Completed symbol: {result}")
        except Exception as task_e:
            print(f"Error processing completed task: {task_e}")
            raise task_e
        tasks.remove(task)

async def main(exchange_name, direction, enter_symbol_count, enter_symbol_amount_list, grid_num, leverage, stop_loss, user_id, custom_stop=None, telegram_id=None, force_restart=False):
    try:
        # 초기 설정 및 권한 확인
        try:
            await check_permissions_and_initialize(exchange_name, user_id, enter_symbol_amount_list, grid_num, leverage, stop_loss)
        except Exception as e:
            print(f"Error on starting: {e}")
            raise e

        # Redis 및 사용자 데이터 초기화
        try:
            redis = await get_redis_connection()
            user_id = int(user_id)
            if telegram_id is not None:
                await redis_database.update_telegram_id(exchange_name, user_id, telegram_id)
            is_running = await get_user_data(exchange_name, user_id, "is_running")
            if is_running is None:
                await update_user_data(exchange_name, user_id, is_running=False, tasks=[], running_symbols=set())
            completed_symbols = set()
            if force_restart:
                completed_trading_symbols = await get_user_data(exchange_name, user_id, "completed_trading_symbols")
            else:
                await redis.hset(f'{exchange_name}:user:{user_id}', 'completed_trading_symbols', json.dumps(list(completed_symbols)))
        except Exception as e:
            print(f"Error on initializing user data: {str(e)}")
            raise e

        # 초기 메시지 준비 및 전송
        total_enter_symbol_amount = sum(enter_symbol_amount_list)
        if (leverage is not None) and (exchange_name in ['bitget', 'binance', 'okx']):
            initial_investment = [amount * leverage for amount in enter_symbol_amount_list]
        else:
            initial_investment = enter_symbol_amount_list
            leverage = 1   
        numbers_to_entry = enter_symbol_count
        initial_capital_list = enter_symbol_amount_list
        modified_symbols = []
        recovery_tasks = []
        timeframe = '15m'
        limit = 1000
        initial_capital = initial_investment
        grid_num = int(grid_num)
        recovery_mode = False
        recovery_state = redis.get('recovery_state')

        try:
            n = int(numbers_to_entry)
        except ValueError as e:
            logging.error(f"숫자 변환 오류: {e}")
            n = 5  # 숫자가 아닌 경우 기본값으로 5을 설정

        if recovery_state:
            await asyncio.sleep(random.random())
        await asyncio.sleep(0.1)

        # 심볼 가져오기 및 포맷팅
        symbols, modified_symbols = await get_and_format_symbols(exchange_name, user_id, direction, n, force_restart)

        symbol_queues = {symbol: asyncio.Queue(maxsize=1) for symbol in symbols}
        symbols_formatted = format_symbols(symbols)

        # 메시지 준비
        message = await prepare_initial_messages(
            exchange_name, user_id, symbols, enter_symbol_amount_list, leverage, total_enter_symbol_amount
        )

        await redis_database.update_user_running_status(exchange_name, user_id, is_running=True) 
        try:
            await add_user_log(user_id, message)
            #asyncio.create_task(telegram_message.send_telegram_message(message, exchange_name, user_id))
            trading_semaphore = asyncio.Semaphore(numbers_to_entry)
            completed_symbols = set()
            running_symbols = set()
            await update_user_data(exchange_name, user_id, running_symbols=set())
            tasks = []
        except Exception as e:
            print(f"{user_id} : An error occurred while sending initial logs: {e}")
            print(traceback.format_exc())
            print("Tasks have been cancelled.")
            raise e

        try:
            exchange_instance = await get_exchange_instance(exchange_name, user_id)
            user_key = f'{exchange_name}:user:{user_id}'
            while True:
                is_running = await get_user_data(exchange_name, user_id, "is_running")
                if not is_running:
                    break

                async with trading_semaphore:
                    if len(running_symbols) <= enter_symbol_count:
                        try:
                            new_symbols = [s for s in symbols if s not in completed_symbols and s not in running_symbols]
                            if new_symbols:
                                print(f"😈Attempting to create tasks for symbols: {new_symbols}")
                                created_tasks = await create_tasks(
                                    new_symbols, symbol_queues, initial_investment, direction, 
                                    timeframe, grid_num, exchange_name, leverage, user_id, 
                                    stop_loss, numbers_to_entry, exchange_instance, custom_stop, force_restart
                                )
                                if created_tasks:
                                    tasks.extend(created_tasks)
                                    print(f"Created and managed {len(created_tasks)} new tasks.")
                                else:
                                    print("No new tasks were created or all tasks completed.")
                            else:
                                print("No suitable new symbols found.")
                        except Exception as e:
                            print(f"An error occurred during task creation: {e}")
                            print(traceback.format_exc())
                    else:
                        print(f"Running symbols: {running_symbols}")
                        print(f"Completed symbols: {completed_symbols}")
                        print(f"Running tasks: {len(tasks)}")
                        print(f"Completed tasks: {len([task for task in tasks if task.done()])}")

                    try:
                        is_running = await get_user_data(exchange_name, user_id, "is_running")
                        if not is_running:
                            break
                        if len(running_symbols) <= enter_symbol_count:
                            potential_recovery_symbols = await get_top_symbols(user_id, exchange_name, direction, limit=32)
                            new_symbols = [s for s in potential_recovery_symbols if s not in completed_symbols and s not in running_symbols]
                            if new_symbols:
                                print(f"Attempting recovery with symbols: {new_symbols[:1]}")
                                tasks.extend(recovery_tasks)
                                running_symbols.update(new_symbols[:1])
                                print(f"Successfully created {len(recovery_tasks)} recovery tasks.")

                                await telegram_message.send_telegram_message(
                                    f"{user_id} :새로운 심볼 {new_symbols[:1]}로 재진입", exchange_name, user_id, debug=True
                                )
                                await redis.hset(user_key, 'running_symbols', json.dumps(list(running_symbols)))
                                recovery_tasks = await create_tasks(
                                    new_symbols[:1], symbol_queues, initial_investment, direction, timeframe, grid_num, exchange_name, leverage, user_id, 
                                    stop_loss=stop_loss, numbers_to_entry=numbers_to_entry, 
                                    exchange_instance=exchange_instance, custom_stop=custom_stop
                                )
                                if recovery_tasks:
                                    all_task_names = [task.get_name() for task in tasks]
                                    await redis.hset(user_key, 'tasks', json.dumps(all_task_names))
                                else:
                                    print(f" {user_id} : Recovery tasks were created but returned empty. This is unexpected.")
                            else:
                                print(f" {user_id} : No suitable recovery symbols found after exception.")
                                await asyncio.sleep(10)
                    except Exception as recovery_e:
                        print(f"Error during recovery: {recovery_e}")
                        print(traceback.format_exc())

                # 완료된 태스크 처리
                await handle_completed_tasks(tasks, exchange_name, user_id, completed_symbols, running_symbols, user_key, redis)

                await asyncio.sleep(3)  # 루프 사이에 짧은 대기 시간 추가
        except Exception as e:
            print(f"{user_id} : An error occurred during main loop: {e}")
            raise e

        # 모든 실행 중인 태스크 완료 대기
        try:
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            trading_success = True
            final_message = f"매매가 종료되었습니다"
        except Exception as e:
            print('exception! ')
            print(f"Unexpected error in run_task for {user_id}: {e}")
            print(traceback.format_exc())
            raise e
    except KeyboardInterrupt:
        print("Caught KeyboardInterrupt. Cleaning up...")
        print("is_running set to False")
        raise e
    except Exception as e:
        print('[START FEATURE EXCEPTION]', e)
        print(traceback.format_exc())
        raise e
    finally:
        from grid_process import stop_grid_main_process
        message = f"{user_id} : 매매가 종료되었습니다.\n모든 트레이딩이 종료되었습니다"
        await stop_grid_main_process(exchange_name, user_id)
        await telegram_message.send_telegram_message(f"{user_id} : 매매가 종료되었습니다", exchange_name, user_id)
        await add_user_log(user_id, message)
        await redis_database.update_user_running_status(exchange_name, user_id, is_running=False)
#==============================================================================
# ENDPOINT : SELL ALL
#==============================================================================

async def sell_all_coins(exchange_name, user_id):
    print('========================[SELL ALL COINS]========================')
    await retry_async(manually_close_positions, exchange_name, user_id)
    print('========================[SELL ALL COINS END]========================')
   

#==============================================================================
# ENDPOINT : CANCEL ALL TASKS
#==============================================================================

async def cancel_all_tasks(loop):
    tasks = [task for task in asyncio.all_tasks(loop) if task is not asyncio.current_task(loop)]
    list(map(lambda task: task.cancel(), tasks))
    await asyncio.gather(*tasks, return_exceptions=True)



#==============================================================================
# D E B U G O N L Y 
#==============================================================================
def start_feature():
    url = 'http://localhost:8000/feature/start'
    headers = {
        'accept': 'application/json',
        'Content-Type': 'application/json'
    }
    data = {
        "exchange_name": "upbit",
        "enter_strategy": "long",
        "enter_symbol_count": 5,
        "enter_symbol_amount_list": [50000],
        "grid_num": 20,
        "leverage": 1,
        "stop_loss": 3,
        "custom_stop": 240,
        "telegram_id": 1709556958,
        "user_id": 1234,
        "api_key": OKX_API_KEY,
        "api_secret": OKX_SECRET_KEY,
        "password": OKX_PASSPHRASE
    }
    response = requests.post(url, headers=headers, json=data)
    print(response.status_code, response.text)

if __name__ == "__main__":
    start_feature()
