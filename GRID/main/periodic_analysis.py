# -*- coding: utf-8 -*-

import os
import sys
from datetime import datetime, timedelta
import pandas as pd
import asyncio
import pytz  # type: ignore[import-untyped]
import ccxt.async_support as ccxt  # noqa: E402
import random
import traceback
import numpy as np
from pathlib import Path
import time
import logging
from concurrent.futures import ProcessPoolExecutor
from GRID.trading.instance_manager import get_exchange_instance
from dateutil import parser  # type: ignore[import-untyped]
from collections import defaultdict
from GRID.database.redis_database import RedisConnectionManager
import json
import redis
from shared.config import settings  # settings 추가

# Import from new modular structure
from shared.indicators import (
    calculate_adx,
    compute_mama_fama,
)
from GRID.indicators import (
    get_indicator_state,
    map_4h_adx_to_15m,
    update_adx_state,
    atr,
    crossover,
    crossunder,
)
from GRID.data import (
    get_cache,
    set_cache,
    get_ttl_for_timeframe,
    get_last_timestamp,
    get_all_okx_usdt_swap_symbols,
    get_all_okx_usdt_spot_symbols,
    get_all_binance_usdt_symbols,
    get_all_binance_usdt_spot_symbols,
    get_all_upbit_krw_symbols
)
from GRID.utils import (
    parse_timeframe_to_ms,
)
from GRID.analysis import (
    calculate_ohlcv,
    is_data_valid,
    refetch_data,
    summarize_trading_results,
    initialize_orders,
    calculate_grid_levels,
    execute_trading_logic,
)

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
symbol_semaphores: defaultdict[str, asyncio.Semaphore] = defaultdict(lambda: asyncio.Semaphore(10))  # 각 심볼당 최대 5개의 동시 요청


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

PI = 2 * np.arcsin(1)

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

# enter_position, is_data_valid, and refetch_data now imported from GRID.analysis

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
                    _, fama = compute_mama_fama(ohlcv_data['close'], length=20)
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

async def handle_symbol(exchange_instance, symbol, exchange_name, semaphore, executor):
    # 대기 시간 감소
    await asyncio.sleep(0.5)  # 2초에서 0.5초로 감소

    async with semaphore:
        need_update = False

        try:
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
                    _, _ = await calculate_ohlcv(exchange_name, symbol, ohlcv_data, ohlcv_data_4h)

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
    exchange_instance = await get_exchange_instance(exchange_name, user_id='999999999')
    # 프로세스 풀 크기 증가
    executor = ProcessPoolExecutor(max_workers=8)  # 4에서 8로 증가
    # 세마포어 값 증가
    semaphore_okx = asyncio.Semaphore(5)  # 3에서 5로 증가
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

if __name__ == "__main__":
    asyncio.run(main())