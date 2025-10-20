#!/usr/bin/env python
# -*- coding: utf-8 -*-
# src/data_collector/polling_data_collector.py
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
import asyncio
import json
import logging
import threading
import time
from datetime import UTC, datetime

import ccxt
import pytz
import redis

from HYPERRSI.src.config import get_settings
from HYPERRSI.src.core.config import settings
from shared.indicators import compute_all_indicators
from shared.logging import get_logger

# 로깅 설정
logger = get_logger(__name__)
logging.basicConfig(level=logging.WARNING, format='%(asctime)s - %(levelname)s - %(message)s')

# 설정 및 상수
SYMBOLS = ["BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP"]
TIMEFRAMES = [1, 3, 5, 15, 30, 60, 240, 360, 720, 1440]  # 분 단위
TF_MAP = {1: '1m', 3: '3m', 5: '5m', 15: '15m', 30: '30m', 60: '1h', 240: '4h', 360: '6h', 720: '12h', 1440: '1d'}
MAX_CANDLE_LEN = 3000
POLLING_CANDLES = 100  # 한 번에 폴링할 캔들 수

# 역매핑 생성 (ex: '1m' -> 1)
REVERSE_TF_MAP = {v: k for k, v in TF_MAP.items()}

# Redis 클라이언트 설정 - Use shared sync Redis connection pool
from shared.database.redis import RedisConnectionManager

redis_manager = RedisConnectionManager(
    host=settings.REDIS_HOST,
    port=settings.REDIS_PORT,
    db=0,
    password=settings.REDIS_PASSWORD if settings.REDIS_PASSWORD else None
)
redis_client = redis_manager.get_connection()

# OKX API 설정 - 직접 settings에서 가져오기
OKX_API_KEY = settings.OKX_API_KEY
OKX_SECRET = settings.OKX_SECRET_KEY
OKX_PASSPHRASE = settings.OKX_PASSPHRASE

print("===============")
print(f"API KEY: {OKX_API_KEY[:5]}...{OKX_API_KEY[-5:] if len(OKX_API_KEY) > 10 else ''}")
print(f"SECRET: {OKX_SECRET[:5]}...{OKX_SECRET[-5:] if len(OKX_SECRET) > 10 else ''}")
print(f"PASSPHRASE: {'*' * min(len(OKX_PASSPHRASE), 10)}")
print("===============")

# API 키 유효성 검사
if not OKX_API_KEY or not OKX_SECRET or not OKX_PASSPHRASE:
    logger.error("OKX API 키가 설정되지 않았습니다. 환경 변수를 확인하세요.")
    raise ValueError("OKX API 키가 없습니다. OKX_API_KEY, OKX_SECRET, OKX_PASSPHRASE 환경 변수를 설정하세요.")

# ccxt.okx 인스턴스 생성 - 서명 관련 추가 옵션
exchange = ccxt.okx({
    'apiKey': OKX_API_KEY,
    'secret': OKX_SECRET,
    'password': OKX_PASSPHRASE,
    'enableRateLimit': True,
    'options': {
        'defaultType': 'swap',
        'adjustForTimeDifference': True,
        'recvWindow': 10000,
    },
    'timeout': 30000,
})

# API 키 유효성 미리 테스트
try:
    exchange.check_required_credentials()
    logger.info("OKX API 인증 정보가 설정되었습니다.")
except Exception as e:
    logger.error(f"OKX API 인증 정보가 유효하지 않습니다: {e}")
    raise ValueError(f"OKX API 인증 오류: {e}")

# 안전한 종료를 위한 이벤트 객체
shutdown_event = threading.Event()

# 마지막 캔들 타임스탬프 및 마지막 체크 시간 저장
last_candle_timestamps = {}
last_check_times = {}

from shared.utils.time_helpers import align_timestamp, calculate_update_interval, is_bar_end


def fetch_latest_candles(symbol, timeframe, limit=POLLING_CANDLES, include_current=False):
    """최신 캔들 데이터 가져오기"""
    tf_str = TF_MAP.get(timeframe, "1m")
    logger.debug(f"최신 캔들 폴링: {symbol} {tf_str} - {limit}개 요청 (현재 진행 캔들 포함: {include_current})")
    
    try:
        # 재시도 로직 (최대 5회 재시도, 지수 백오프)
        max_retries = 5
        attempt = 0
        
        while True:
            try:
                params = {'instType': 'SWAP'}
                # 디버깅용 요청 정보 출력
                logger.debug(f"API 요청 정보: symbol={symbol}, timeframe={tf_str.lower()}, limit={limit}, params={params}")
                
                ohlcvs = exchange.fetch_ohlcv(
                    symbol,
                    timeframe=tf_str.lower(),
                    limit=limit,
                    params=params
                )
                break  # 성공하면 반복문 탈출
            except ccxt.RateLimitExceeded as e:
                attempt += 1
                if attempt >= max_retries:
                    logger.error(f"최대 재시도 횟수 초과: {symbol} ({tf_str}). 오류: {e}")
                    raise e
                wait_time = 2 ** attempt  # 지수 백오프: 2, 4, 8, ... 초
                logger.warning(f"속도 제한 초과: {symbol} ({tf_str}). {wait_time}초 대기 후 재시도... (시도 {attempt}/{max_retries})")
                time.sleep(wait_time)
            except Exception as e:
                logger.error(f"OHLCV 데이터 가져오기 실패: {symbol} ({tf_str}). 오류: {e}")
                return []  # 오류 발생 시 빈 리스트 반환
        
        candles = []
        for row in ohlcvs:
            # None 값 체크 추가
            if row is None or len(row) < 6:
                logger.warning(f"잘못된 캔들 데이터 (None 또는 불완전): {symbol} {tf_str}")
                continue
                
            try:
                ts, o, h, l, c, v = row
                
                # None 값 타입 체크 및 처리
                if ts is None or o is None or h is None or l is None or c is None or v is None:
                    logger.warning(f"캔들 데이터에 None 값 포함: {symbol} {tf_str} - {row}")
                    continue
                    
                ts = int(ts) if ts is not None else 0
                aligned_ts = align_timestamp(ts, timeframe) // 1000
                
                # 볼륨이 0인 캔들 제외 (단, 현재 진행 중인 캔들은 허용)
                is_current_candle = (aligned_ts + timeframe * 60) > int(time.time())
                
                if v == 0 and not is_current_candle:
                    logger.warning(f"볼륨 0 캔들 제외: {symbol} {tf_str} at {datetime.fromtimestamp(aligned_ts)}")
                    continue
                    
                candles.append({
                    "timestamp": aligned_ts,
                    "open": float(o),
                    "high": float(h),
                    "low": float(l),
                    "close": float(c),
                    "volume": float(v),
                    "is_current": is_current_candle
                })
            except (TypeError, ValueError) as e:
                logger.warning(f"캔들 데이터 변환 오류: {symbol} {tf_str} - {row} - {e}")
                continue
        
        if candles:
            logger.info(f"{len(candles)}개 캔들 가져옴: {symbol} {tf_str}")
            
            # 캔들이 시간순 정렬되어 있는지 확인하고 정렬
            candles.sort(key=lambda x: x["timestamp"])
            
            # 마지막 완료된 캔들 시간 저장
            key = f"{symbol}:{tf_str}"
            
            completed_candles = [c for c in candles if not c.get("is_current", False)]
            if completed_candles:
                last_ts = completed_candles[-1]["timestamp"]
                old_last_ts = last_candle_timestamps.get(key, 0)
                
                if last_ts > old_last_ts:
                    last_candle_timestamps[key] = last_ts
                    logger.info(f"마지막 완료된 캔들 타임스탬프 업데이트: {key} - {datetime.fromtimestamp(last_ts)}")
        
        return candles
    
    except Exception as e:
        logger.error(f"캔들 데이터 가져오기 오류: {symbol} {tf_str} - {e}", exc_info=True)
        return []

def check_and_fill_gap(symbol, timeframe):
    """데이터 갭이 있는지 확인하고 채우기"""
    tf_str = TF_MAP.get(timeframe, "1m")
    key = f"{symbol}:{tf_str}"
    
    try:
        # Redis에서 기존 캔들 가져오기
        candle_key = f"candles:{symbol}:{tf_str}"
        existing_data = redis_client.lrange(candle_key, 0, -1)
        
        if not existing_data:
            logger.warning(f"기존 데이터 없음, 갭 체크 불가: {key}")
            return
        
        # 마지막 캔들 타임스탬프 확인
        latest_candles = fetch_latest_candles(symbol, timeframe, limit=1)
        if not latest_candles:
            logger.warning(f"최신 캔들 가져오기 실패, 갭 체크 불가: {key}")
            return
            
        latest_ts = latest_candles[0]["timestamp"]
        
        # 기존 데이터의 마지막 타임스탬프 찾기
        existing_map = {}
        for item in existing_data:
            parts = item.split(",")
            ts = int(parts[0])
            existing_map[ts] = parts
        
        existing_ts = sorted(existing_map.keys())
        last_existing_ts = existing_ts[-1] if existing_ts else 0
        
        # 갭 체크
        tf_minutes = timeframe
        expected_interval = tf_minutes * 60
        
        if (latest_ts - last_existing_ts) > expected_interval * 1.5:
            gap_size = latest_ts - last_existing_ts
            num_missing = int(gap_size / expected_interval)
            logger.info(
                f"캔들 갭 발견: {key} - "
                f"마지막 기존: {datetime.fromtimestamp(last_existing_ts)}, "
                f"최신: {datetime.fromtimestamp(latest_ts)}, "
                f"누락된 캔들 수: {num_missing}"
            )
            
            # 갭 채우기
            fill_gap(symbol, timeframe, last_existing_ts, latest_ts)
    
    except Exception as e:
        logger.error(f"갭 체크 중 오류: {key} - {e}", exc_info=True)

def fill_gap(symbol, timeframe, from_ts, to_ts):
    """데이터 갭 채우기"""
    tf_str = TF_MAP.get(timeframe, "1m")
    key = f"{symbol}:{tf_str}"
    
    try:
        logger.info(f"갭 채우기 시작: {key} - {datetime.fromtimestamp(from_ts)} ~ {datetime.fromtimestamp(to_ts)}")
        
        # 갭이 너무 큰 경우 제한
        tf_minutes = timeframe
        expected_candles = (to_ts - from_ts) // (tf_minutes * 60)
        
        if expected_candles > 1000:
            logger.warning(f"갭이 너무 큽니다 ({expected_candles}개 캔들), 최대 1000개만 요청: {key}")
            from_ts = to_ts - (1000 * tf_minutes * 60)
        
        # API로 갭 데이터 가져오기
        params = {'instType': 'SWAP'}
        ohlcvs = exchange.fetch_ohlcv(
            symbol, 
            timeframe=tf_str.lower(),
            since=(from_ts + 1) * 1000,  # +1초 해서 마지막 캔들 중복 방지
            limit=1000,
            params=params
        )
        
        gap_candles = []
        for row in ohlcvs:
            ts, o, h, l, c, v = row
            aligned_ts = align_timestamp(ts, timeframe) // 1000
            
            # 볼륨이 0인 캔들 제외
            if v == 0:
                continue
                
            gap_candles.append({
                "timestamp": aligned_ts,
                "open": float(o),
                "high": float(h),
                "low": float(l),
                "close": float(c),
                "volume": float(v)
            })
        
        if not gap_candles:
            logger.warning(f"갭 데이터 없음: {key}")
            return
            
        logger.info(f"{len(gap_candles)}개 갭 캔들 가져옴: {key}")
        
        # 기존 데이터와 병합하여 저장
        update_candle_data(symbol, timeframe, gap_candles)
        
    except Exception as e:
        logger.error(f"갭 채우기 중 오류: {key} - {e}", exc_info=True)

def update_candle_data(symbol, timeframe, new_candles):
    """캔들 데이터 업데이트"""
    tf_str = TF_MAP.get(timeframe, "1m")
    key = f"candles:{symbol}:{tf_str}"
    
    try:
        # 기존 캔들 데이터 가져오기
        existing = redis_client.lrange(key, 0, -1)
        candle_map = {}
        
        # 기존 데이터 파싱
        for item in existing:
            parts = item.split(",")
            ts = int(parts[0])
            candle_map[ts] = parts
        
        # 새 캔들 데이터 병합
        for candle in new_candles:
            ts = candle["timestamp"]
            cndl_str_list = [
                str(ts),
                str(candle["open"]),
                str(candle["high"]),
                str(candle["low"]),
                str(candle["close"]),
                str(candle["volume"]),
            ]
            candle_map[ts] = cndl_str_list
        
        # 정렬 후 저장 (최대 MAX_CANDLE_LEN개만 유지)
        sorted_ts = sorted(candle_map.keys())
        if len(sorted_ts) > MAX_CANDLE_LEN:
            sorted_ts = sorted_ts[-MAX_CANDLE_LEN:]
        
        final_list = [",".join(candle_map[ts]) for ts in sorted_ts]
        
        # Redis에 저장
        pipe = redis_client.pipeline()
        pipe.delete(key)
        for row_str in final_list:
            pipe.rpush(key, row_str)
        pipe.execute()
        
        # 인디케이터 계산 및 저장
        if len(sorted_ts) > 30:  # 최소한의 데이터가 있어야 계산 가능
            # 캔들 객체 리스트 생성
            candles = []
            for ts in sorted_ts:
                parts = candle_map[ts]
                candles.append({
                    "timestamp": int(parts[0]),
                    "open": float(parts[1]),
                    "high": float(parts[2]),
                    "low": float(parts[3]),
                    "close": float(parts[4]),
                    "volume": float(parts[5])
                })
            
            # 인디케이터 계산
            candles_with_ind = compute_all_indicators(candles, rsi_period=14, atr_period=14)
            
            # 한국 시간 추가
            for cndl in candles_with_ind:
                utc_dt = datetime.fromtimestamp(cndl["timestamp"], UTC)
                seoul_tz = pytz.timezone("Asia/Seoul")
                dt_seoul = utc_dt.replace(tzinfo=pytz.utc).astimezone(seoul_tz)
                cndl["human_time"] = utc_dt.strftime("%Y-%m-%d %H:%M:%S")
                cndl["human_time_kr"] = dt_seoul.strftime("%Y-%m-%d %H:%M:%S")
            
            # 인디케이터 포함 캔들 저장
            save_candles_with_indicators(symbol, tf_str, candles_with_ind)
            
            logger.info(f"캔들 데이터 업데이트 완료: {symbol} {tf_str} - 총 {len(sorted_ts)}개 캔들")
        else:
            logger.warning(f"인디케이터 계산에 필요한 충분한 데이터 없음: {symbol} {tf_str}")
    
    except Exception as e:
        logger.error(f"캔들 데이터 업데이트 중 오류: {symbol} {tf_str} - {e}", exc_info=True)

def save_candles_with_indicators(symbol, tf_str, candles_with_ind):
    """인디케이터가 포함된 캔들 데이터 저장"""
    key = f"candles_with_indicators:{symbol}:{tf_str}"
    
    try:
        # 기존 데이터 가져오기
        existing_list = redis_client.lrange(key, 0, -1)
        candle_map = {}
        
        for item in existing_list:
            try:
                obj = json.loads(item)
                if "timestamp" in obj:
                    candle_map[obj["timestamp"]] = obj
            except Exception as e:
                pass
        
        # 새 데이터 병합
        for cndl in candles_with_ind:
            ts = cndl["timestamp"]
            candle_map[ts] = cndl
        
        # 정렬 후 저장 (최대 MAX_CANDLE_LEN개만 유지)
        sorted_ts = sorted(candle_map.keys())
        if len(sorted_ts) > MAX_CANDLE_LEN:
            sorted_ts = sorted_ts[-MAX_CANDLE_LEN:]
        
        # Redis에 저장
        with redis_client.pipeline() as pipe:
            pipe.delete(key)
            for ts in sorted_ts:
                row_json = json.dumps(candle_map[ts])
                pipe.rpush(key, row_json)
            pipe.execute()
        
        # 최신 캔들 따로 저장
        latest_key = f"latest:{symbol}:{tf_str}"
        latest_ts = sorted_ts[-1]
        redis_client.set(latest_key, json.dumps(candle_map[latest_ts]))
    
    except Exception as e:
        logger.error(f"인디케이터 포함 캔들 저장 중 오류: {symbol} {tf_str} - {e}", exc_info=True)

def fetch_initial_data():
    """초기 데이터 로드"""
    logger.info("=== 초기 데이터 로드 시작 ===")
    
    for symbol in SYMBOLS:
        for timeframe in TIMEFRAMES:
            tf_str = TF_MAP.get(timeframe, "1m")
            key = f"{symbol}:{tf_str}"
            
            logger.info(f"초기 데이터 로드: {key}")
            
            # 초기 데이터는 최대 3000개까지 가져옴
            candles = fetch_latest_candles(symbol, timeframe, limit=MAX_CANDLE_LEN)
            if candles:
                update_candle_data(symbol, timeframe, candles)
                last_candle_timestamps[key] = candles[-1]["timestamp"]
            else:
                logger.warning(f"초기 데이터 로드 실패: {key}")
    
    logger.info("=== 초기 데이터 로드 완료 ===")

def update_current_candle(symbol, timeframe):
    """현재 진행 중인 캔들 업데이트"""
    tf_str = TF_MAP.get(timeframe, "1m")
    key = f"{symbol}:{tf_str}"
    
    try:
        # 현재 진행 중인 캔들 가져오기 (limit=2로 설정하여 현재 + 직전 캔들 확보)
        recent_candles = fetch_latest_candles(symbol, timeframe, limit=2, include_current=True)
        
        if not recent_candles:
            logger.warning(f"현재 캔들 가져오기 실패: {key}")
            return
        
        # 현재 진행 중인 캔들 찾기 (마지막 캔들이 현재 진행 중일 가능성이 높음)
        current_candle = None
        current_time = int(time.time())
        
        for candle in reversed(recent_candles):  # 최신 캔들부터 확인
            if (candle["timestamp"] + timeframe * 60) > current_time:
                current_candle = candle
                break
        
        if not current_candle:
            logger.warning(f"현재 진행 중인 캔들을 찾을 수 없음: {key}")
            return
        
        # 진행 중인 캔들 정보 Redis에 저장
        current_key = f"current_candle:{symbol}:{tf_str}"
        
        # 현재 시각 정보 추가
        utc_dt = datetime.now(UTC)
        seoul_tz = pytz.timezone("Asia/Seoul")
        dt_seoul = utc_dt.astimezone(seoul_tz)
        
        current_candle["update_time"] = utc_dt.strftime("%Y-%m-%d %H:%M:%S")
        current_candle["update_time_kr"] = dt_seoul.strftime("%Y-%m-%d %H:%M:%S")
        
        redis_client.set(current_key, json.dumps(current_candle))
        logger.debug(f"현재 진행 캔들 업데이트: {key} - O:{current_candle['open']} H:{current_candle['high']} L:{current_candle['low']} C:{current_candle['close']}")
        
        # 최신 캔들 키도 업데이트
        latest_key = f"latest:{symbol}:{tf_str}"
        redis_client.set(latest_key, json.dumps(current_candle))
        
        # 인디케이터 포함 버전도 업데이트
        update_current_candle_with_indicators(symbol, timeframe, current_candle)
    
    except Exception as e:
        logger.error(f"현재 캔들 업데이트 중 오류: {key} - {e}", exc_info=True)

def update_current_candle_with_indicators(symbol, timeframe, current_candle):
    """현재 진행 중인 캔들에 인디케이터 계산하여 업데이트"""
    tf_str = TF_MAP.get(timeframe, "1m")
    key = f"candles_with_indicators:{symbol}:{tf_str}"
    
    try:
        # 기존 캔들 데이터 가져오기
        candle_key = f"candles:{symbol}:{tf_str}"
        existing_data = redis_client.lrange(candle_key, 0, -1)
        
        if not existing_data or len(existing_data) < 30:
            logger.warning(f"인디케이터 계산에 필요한 충분한 데이터가 없음: {symbol} {tf_str}")
            return
        
        # 캔들 객체 리스트 생성
        candles = []
        for item in existing_data:
            parts = item.split(",")
            ts = int(parts[0])
            candles.append({
                "timestamp": ts,
                "open": float(parts[1]),
                "high": float(parts[2]),
                "low": float(parts[3]),
                "close": float(parts[4]),
                "volume": float(parts[5])
            })
        
        # 현재 캔들 추가 또는 업데이트
        current_ts = current_candle["timestamp"]
        found = False
        
        for i, candle in enumerate(candles):
            if candle["timestamp"] == current_ts:
                candles[i] = current_candle
                found = True
                break
        
        if not found:
            candles.append(current_candle)
            candles.sort(key=lambda x: x["timestamp"])
        
        # 인디케이터 계산
        candles_with_ind = compute_all_indicators(candles, rsi_period=14, atr_period=14)
        
        # 기존 인디케이터 데이터 로드
        existing_ind_list = redis_client.lrange(key, 0, -1)
        candle_ind_map = {}
        
        for item in existing_ind_list:
            try:
                obj = json.loads(item)
                if "timestamp" in obj:
                    candle_ind_map[obj["timestamp"]] = obj
            except Exception as e:
                pass
        
        # 새 인디케이터 데이터 병합
        for candle in candles_with_ind:
            ts = candle["timestamp"]
            
            # 한국 시간 추가
            utc_dt = datetime.fromtimestamp(ts, UTC)
            seoul_tz = pytz.timezone("Asia/Seoul")
            dt_seoul = utc_dt.replace(tzinfo=pytz.utc).astimezone(seoul_tz)
            candle["human_time"] = utc_dt.strftime("%Y-%m-%d %H:%M:%S")
            candle["human_time_kr"] = dt_seoul.strftime("%Y-%m-%d %H:%M:%S")
            
            # 현재 진행 중인 캔들인 경우 업데이트 시간 추가
            if ts == current_ts:
                utc_now = datetime.now(UTC)
                seoul_now = utc_now.astimezone(seoul_tz)
                candle["update_time"] = utc_now.strftime("%Y-%m-%d %H:%M:%S")
                candle["update_time_kr"] = seoul_now.strftime("%Y-%m-%d %H:%M:%S")
                candle["is_current"] = True
            
            candle_ind_map[ts] = candle
        
        # 정렬 후 저장 (최대 MAX_CANDLE_LEN개만 유지)
        sorted_ts = sorted(candle_ind_map.keys())
        if len(sorted_ts) > MAX_CANDLE_LEN:
            sorted_ts = sorted_ts[-MAX_CANDLE_LEN:]
        
        # Redis에 저장
        with redis_client.pipeline() as pipe:
            pipe.delete(key)
            for ts in sorted_ts:
                row_json = json.dumps(candle_ind_map[ts])
                pipe.rpush(key, row_json)
            pipe.execute()
        
        # 현재 캔들의 인디케이터 값 찾기
        current_with_ind = candle_ind_map.get(current_ts)
        
        if current_with_ind:
            # 현재 캔들 별도 저장
            current_ind_key = f"current_candle_with_indicators:{symbol}:{tf_str}"
            redis_client.set(current_ind_key, json.dumps(current_with_ind))
            
            # 최신 캔들 키도 업데이트
            latest_ind_key = f"latest_with_indicators:{symbol}:{tf_str}"
            redis_client.set(latest_ind_key, json.dumps(current_with_ind))
            
            logger.debug(f"현재 진행 캔들 인디케이터 업데이트 완료: {symbol} {tf_str}")
        else:
            logger.warning(f"현재 캔들의 인디케이터 계산 결과를 찾을 수 없음: {symbol} {tf_str}")
    
    except Exception as e:
        logger.error(f"현재 캔들 인디케이터 업데이트 중 오류: {symbol} {tf_str} - {e}", exc_info=True)

def polling_worker():
    """폴링 워커 함수"""
    logger.info("폴링 워커 시작")
    
    try:
        # 초기화
        for symbol in SYMBOLS:
            for timeframe in TIMEFRAMES:
                tf_str = TF_MAP.get(timeframe, "1m")
                key = f"{symbol}:{tf_str}"
                last_check_times[key] = 0
        
        while not shutdown_event.is_set():
            current_time = time.time()
            
            for symbol in SYMBOLS:
                for timeframe in TIMEFRAMES:
                    tf_str = TF_MAP.get(timeframe, "1m")
                    key = f"{symbol}:{tf_str}"
                    
                    # 각 타임프레임별 업데이트 주기 계산
                    update_interval = calculate_update_interval(timeframe)
                    
                    # 마지막 체크 시간 이후 충분한 시간이 지났는지 확인
                    last_check = last_check_times.get(key, 0)
                    
                    # 바 종료 시점 체크
                    if is_bar_end(current_time, timeframe):
                        # 바 종료 시점에는 완료된 캔들 업데이트 (5초 간격으로 체크)
                        if current_time - last_check >= 5:
                            logger.info(f"바 종료 감지: {key} - 데이터 폴링 시작")
                            
                            # 최신 캔들 100개 가져오기
                            candles = fetch_latest_candles(symbol, timeframe, limit=POLLING_CANDLES)
                            
                            if candles:
                                # 갭 체크 및 데이터 업데이트
                                check_and_fill_gap(symbol, timeframe)
                                update_candle_data(symbol, timeframe, candles)
                            
                            # 마지막 체크 시간 업데이트
                            last_check_times[key] = current_time
                    else:
                        # 일반 시점에는 타임프레임별 계산된 간격으로 현재 진행 중인 캔들 업데이트
                        if current_time - last_check >= update_interval:
                            logger.debug(f"현재 진행 캔들 업데이트 실행: {key} (간격: {update_interval}초)")
                            update_current_candle(symbol, timeframe)
                            
                            # 마지막 체크 시간 업데이트
                            last_check_times[key] = current_time
            
            # 잠시 대기 (CPU 사용량 줄이기)
            time.sleep(1)
    
    except Exception as e:
        logger.error(f"폴링 워커 오류: {e}", exc_info=True)
    finally:
        logger.info("폴링 워커 종료")

def main():
    """메인 함수"""
    try:
        logger.info("=== 폴링 기반 데이터 수집기 시작 ===")
        
        # 초기 데이터 로드
        fetch_initial_data()
        
        # 폴링 워커 스레드 시작
        polling_thread = threading.Thread(target=polling_worker, daemon=True)
        polling_thread.start()
        
        # 메인 스레드는 종료 신호 대기
        try:
            while polling_thread.is_alive():
                time.sleep(1)
                
                # 종료 체크
                if shutdown_event.is_set():
                    logger.info("종료 신호 감지")
                    break
        
        except KeyboardInterrupt:
            logger.info("키보드 인터럽트 감지, 안전하게 종료합니다...")
            shutdown_event.set()
        
        # 워커 스레드 종료 대기
        polling_thread.join(timeout=5)
        logger.info("폴링 워커 스레드 종료됨")
    
    except Exception as e:
        logger.error(f"메인 실행 오류: {e}", exc_info=True)
    
    finally:
        logger.info("=== 폴링 기반 데이터 수집기 종료 ===")

if __name__ == "__main__":
    main()