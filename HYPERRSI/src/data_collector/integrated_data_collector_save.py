#2025년 3월 27일, data_collector v2가 잘 되어서, 이걸로 integrated_data_collector_save.py 대체. 그래서, 그 복사본을 백업으로 남겨둠. 
#현재 이 복사본의 버젼 역시, 작동은 잘 함. 그러나, 실제로 지표계산에서 오류가 있기에. 따라서 문제가 발생하면, 다시 이걸로 교체하면 됨.

#!/usr/bin/env python
# -*- coding: utf-8 -*-
# src/data_collector/integrated_data_collector.py

import asyncio
import json
import logging
import os
import ssl
import time
from datetime import datetime, UTC
import threading

import ccxt
import pytz
import redis
import websockets

from HYPERRSI.src.core.config import settings
from shared.logging import get_logger
from shared.indicators import compute_all_indicators
from HYPERRSI.src.config import get_settings

# 로깅 설정 - 기본 레벨을 INFO로 설정
logger = get_logger(__name__)
logging.basicConfig(level=logging.WARNING, format='%(asctime)s - %(levelname)s - %(message)s')

# 설정 및 상수
SYMBOLS = ["BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP"]
TIMEFRAMES = [1, 3, 5, 15, 30, 60, 240]  # 분 단위
TF_MAP = {1: '1m', 3: '3m', 5: '5m', 15: '15m', 30: '30m', 60: '1h', 240: '4h'}
MAX_CANDLE_LEN = 3000

# 역매핑도 생성 (ex: '1m' -> 1)
REVERSE_TF_MAP = {v: k for k, v in TF_MAP.items()}

# Redis 클라이언트 설정
if settings.REDIS_PASSWORD:
    redis_client = redis.Redis(
        host=settings.REDIS_HOST, 
        port=settings.REDIS_PORT, 
        db=0, 
        decode_responses=True, 
        password=settings.REDIS_PASSWORD
    )
else:
    redis_client = redis.Redis(
        host=settings.REDIS_HOST, 
        port=settings.REDIS_PORT, 
        db=0, 
        decode_responses=True
    )

# OKX API 자격 증명 - 직접 settings에서 가져오기
OKX_API_KEY = settings.OKX_API_KEY
OKX_SECRET = settings.OKX_SECRET_KEY
OKX_PASSPHRASE = settings.OKX_PASSPHRASE

# API 키 로깅 시 개인 정보 보호
logger.info(f"OKX API KEY: {OKX_API_KEY[:5]}...{OKX_API_KEY[-5:] if len(OKX_API_KEY) > 10 else ''}")
logger.info(f"OKX SECRET KEY: {OKX_SECRET[:5]}...{OKX_SECRET[-5:] if len(OKX_SECRET) > 10 else ''}")
logger.info(f"OKX PASSPHRASE: {'*' * min(len(OKX_PASSPHRASE), 10)}")

# ccxt.okx 인스턴스 생성 - 서명 관련 추가 옵션
exchange = ccxt.okx({
    'apiKey': OKX_API_KEY,
    'secret': OKX_SECRET,
    'password': OKX_PASSPHRASE,
    'enableRateLimit': True,
    'options': {
        'adjustForTimeDifference': True,
        'recvWindow': 10000,
    },
    'timeout': 30000,
})

# 마지막 연결 끊김 시간 저장
last_disconnect_time = {}

# 인디케이터 계산 간격 설정 (초 단위)
INDICATOR_CALC_INTERVAL = 5  # 5초마다만 인디케이터 재계산

# 주기적인 상태 로깅 간격 (초 단위)
STATUS_LOG_INTERVAL = 60  # 60초마다 상태 로깅

# 추가: 안전한 종료를 위한 이벤트 객체
shutdown_event = threading.Event()

# ============================================================================
# WebSocket 관련 함수 및 클래스 (from websocket.py)
# ============================================================================

def convert_symbol_format(symbol: str, to_okx_ws: bool = True) -> str:
    """심볼 형식을 웹소켓 양식으로 변환하는 헬퍼 함수"""
    from shared.utils.symbol_helpers import okx_to_ccxt_symbol, ccxt_to_okx_symbol
    if to_okx_ws:
        return okx_to_ccxt_symbol(symbol)
    else:
        return ccxt_to_okx_symbol(symbol)

class OKXMultiTimeframeWebSocket:
    def __init__(self):
        self.ws_url = "wss://ws.okx.com:8443/ws/v5/business"
        self.last_save = {}  # 마지막 저장 시간 추적
        self.last_indicator_calc = {}  # 마지막 인디케이터 계산 시간
        self.should_run = True 
        self.save_interval = 5  # 5초마다 저장
        self.ws = None
        self.connected = False
        self.last_candle_timestamp = {}  # 각 심볼/타임프레임별 마지막 캔들 타임스탬프
        self.timeframes = {
            "candle1m": "1m",
            "candle3m": "3m",
            "candle5m": "5m",
            "candle15m": "15m",
            "candle30m": "30m",
            "candle1H": "1h",
            "candle4H": "4h"
        }
        self.message_counts = {
            symbol: {channel: 0 for channel in self.timeframes.keys()} 
            for symbol in SYMBOLS
        }
        
        # 웹소켓 연결 끊김 시간 저장
        self.disconnect_times = {}
        # 마지막 상태 로깅 시간
        self.last_status_log = 0
        
        # 초기화 로깅
        logger.info(f"Initializing OKXMultiTimeframeWebSocket for symbols: {SYMBOLS}")
        logger.info(f"Timeframes: {list(self.timeframes.values())}")
        
        for symbol in SYMBOLS:
            for tf_str in self.timeframes.values():
                key = f"{symbol}:{tf_str}"
                self.disconnect_times[key] = 0
                self.last_candle_timestamp[key] = 0
                self.last_indicator_calc[key] = 0

        self.last_data_received = {}  # 각 심볼/타임프레임별 마지막 데이터 수신 시간
        self.data_timeout = 300  # 데이터 수신 타임아웃 (초) - 5분
        
        # 초기화
        for symbol in SYMBOLS:
            for tf_str in self.timeframes.values():
                key = f"{symbol}:{tf_str}"
                self.last_data_received[key] = 0

        self.shutdown_requested = False  # 종료 요청 플래그 추가
        
    async def connect(self):
        try:
            logger.debug(f"Connecting to OKX WebSocket at {self.ws_url}...")
            ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
            self.ws = await websockets.connect(self.ws_url, ssl=ssl_context)
            self.connected = True
            logger.debug("Successfully connected to OKX WebSocket")
            
            # 모든 심볼과 타임프레임에 대한 구독
            subscribe_args = []
            for symbol in SYMBOLS:
                for channel in self.timeframes.keys():
                    subscribe_args.append({
                        "channel": channel,
                        "instId": symbol
                    })
            
            subscribe_message = {
                "op": "subscribe",
                "args": subscribe_args
            }
            logger.debug(f"Subscribing to {len(subscribe_args)} channels...")
            await self.ws.send(json.dumps(subscribe_message))
            logger.debug("Subscription request sent")
            
        except Exception as e:
            logger.error(f"Connection error: {e}", exc_info=True)
            self.connected = False
            await self.handle_disconnect()
            
    async def log_status(self):
        """5분마다 구독 상태를 로깅"""
        while self.connected:
            try:
                await asyncio.sleep(300)  # 5분(300초) 대기
                now = datetime.now()
                logger.debug("=== Subscription Status Report ===")
                total_messages = 0
                for symbol in SYMBOLS:
                    for channel in self.timeframes.keys():
                        count = self.message_counts[symbol][channel]
                        total_messages += count
                        logger.debug(f"{symbol} {channel}: {count} messages received in last 5 minutes")
                        self.message_counts[symbol][channel] = 0  # 카운터 리셋
                logger.debug(f"Total messages in last 5 minutes: {total_messages}")
                logger.debug("================================")
            except Exception as e:
                logger.error(f"Error in status logging: {e}", exc_info=True)

    async def handle_message(self, message):
        try:
            data = json.loads(message)
            if "data" not in data:
                # 구독 확인 메시지인 경우
                if "event" in data and data.get("event") == "subscribe":
                    logger.debug(f"Successfully subscribed to: {data.get('arg', {})}")
                return

            channel = data["arg"]["channel"]
            symbol = data["arg"]["instId"]
            tf_str = self.timeframes.get(channel)
            
            if not tf_str:
                return
                
            key = f"{symbol}:{tf_str}"
            
            # 메시지 카운트 증가
            self.message_counts[symbol][channel] += 1

            # 현재 시간과 마지막 저장 시간 확인
            current_time = time.time()
            save_key = f"{symbol}"  # 심볼 단위로 저장 간격 체크
            last_save_time = self.last_save.get(save_key, 0)
            
            # 주기적인 상태 로깅
            if current_time - self.last_status_log >= STATUS_LOG_INTERVAL:
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                logger.debug(f"[{timestamp}] WebSocket활성상태: {self.connected}, 총 메시지 카운트: {sum(sum(counts.values()) for counts in self.message_counts.values())}")
                self.last_status_log = current_time
            
            # save_interval 초가 지났을 때만 저장
            if current_time - last_save_time >= self.save_interval:
                candle_data = data["data"][0]
                timestamp_ms = int(candle_data[0])
                timestamp_s = timestamp_ms // 1000
                dt_str = datetime.fromtimestamp(timestamp_s).strftime("%Y-%m-%d %H:%M:%S")
                dt_str_kr = datetime.fromtimestamp(timestamp_s).astimezone(pytz.timezone("Asia/Seoul")).strftime("%Y-%m-%d %H:%M:%S")
                # 새 캔들인지 확인
                is_new_candle = timestamp_s > self.last_candle_timestamp.get(key, 0)
                
                # 캔들 연속성 체크 - 새 캔들이 들어오면 이전 캔들과의 간격 확인
                if is_new_candle:
                    last_ts = self.last_candle_timestamp.get(key, 0)
                    
                    # 타임프레임의 분 단위 값 구하기
                    tf_minutes = REVERSE_TF_MAP.get(tf_str, 1)
                    expected_interval = tf_minutes * 60  # 초 단위로 변환
                    
                    # 캔들 사이에 갭이 있는지 확인
                    # 새 캔들이 첫 캔들이 아니고, 간격이 예상보다 클 경우
                    if last_ts > 0 and (timestamp_s - last_ts) > expected_interval * 1.5:
                        # 갭이 있는 경우
                        gap_size = timestamp_s - last_ts - expected_interval
                        num_missing_candles = int(gap_size / expected_interval)
                        logger.info(f"캔들 갭 발견: {symbol} {tf_str} - 마지막: {datetime.fromtimestamp(last_ts)}, 현재: {dt_str}, 누락된 캔들 수: {num_missing_candles}")
                        
                        # 갭 채우기 - 비동기로 실행하여 현재 처리를 차단하지 않음
                        asyncio.create_task(self.fill_candle_gap(symbol, tf_str, last_ts, timestamp_s))
                
                if is_new_candle:
                    self.last_candle_timestamp[key] = timestamp_s
                    logger.info(f"새로운 캔들 수신: {symbol} {tf_str} at {dt_str}")
                else:
                    logger.info(f"캔들 업데이트: {symbol} {tf_str} at {dt_str}")
                
                candle = {
                    "timestamp": timestamp_s,
                    "open": float(candle_data[1]),
                    "high": float(candle_data[2]),
                    "low": float(candle_data[3]),
                    "close": float(candle_data[4]),
                    "volume": float(candle_data[5]),
                    "current_time_kr": dt_str_kr
                }

                # Redis에 최신 캔들 저장
                latest_key = f"latest:{symbol}:{tf_str}"
                redis_client.set(latest_key, json.dumps(candle))
                #logger.debug(f"Redis에 저장 완료: {latest_key}")
                
                # 기존 캔들 데이터에 추가 (새 캔들 여부 전달)
                self.update_candle_data(symbol, tf_str, candle, is_new_candle)
                
                self.last_save[save_key] = current_time

            # 데이터 수신 시간 업데이트
            self.last_data_received[key] = time.time()

        except Exception as e:
            logger.error(f"Error handling message: {e}", exc_info=True)
    
    async def fill_candle_gap(self, symbol, tf_str, from_ts, to_ts):
        """새로 감지된 캔들 갭을 즉시 채우는 함수"""
        try:
            #logger.debug(f"캔들 갭 즉시 채우기 시작: {symbol} {tf_str} - {datetime.fromtimestamp(from_ts)} ~ {datetime.fromtimestamp(to_ts)}")
            
            # 갭이 매우 크면(예: 하루 이상) 너무 많은 데이터를 요청하지 않도록 제한
            tf_minutes = REVERSE_TF_MAP.get(tf_str, 1)
            expected_candles = (to_ts - from_ts) // (tf_minutes * 60)
            
            if expected_candles > 1000:
                logger.warning(f"갭이 너무 큽니다 ({expected_candles}개 캔들), 최대 1000개만 요청합니다: {symbol} {tf_str}")
                # 최신 1000개만 가져오기
                from_ts = to_ts - (1000 * tf_minutes * 60)
            
            # 갭 데이터 가져오기
            candles = await self.fetch_candles_for_gap(symbol, tf_str, from_ts, to_ts, max_candles=1000)
            
            if not candles:
                logger.warning(f"갭 채우기 실패: {symbol} {tf_str} - 가져온 캔들 없음")
                return
                
            #logger.debug(f"{len(candles)}개 캔들 가져옴 - 갭 채우기 진행 중: {symbol} {tf_str}")
            
            # 처리 속도를 위해 일괄 업데이트 대신 개별 캔들 처리
            key = f"candles:{symbol}:{tf_str}"
            pipe = redis_client.pipeline()
            
            # 기존 데이터 가져오기
            existing = redis_client.lrange(key, 0, -1)
            candle_map = {}
            
            # 기존 데이터 로드
            for item in existing:
                parts = item.split(",")
                ts = int(parts[0])
                candle_map[ts] = parts
            
            # 새 캔들 추가
            for candle in candles:
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
            
            # 정렬 후 저장
            sorted_ts = sorted(candle_map.keys())
            if len(sorted_ts) > MAX_CANDLE_LEN:
                sorted_ts = sorted_ts[-MAX_CANDLE_LEN:]
                
            final_list = [",".join(candle_map[ts]) for ts in sorted_ts]
            
            pipe.delete(key)
            for row_str in final_list:
                pipe.rpush(key, row_str)
            pipe.ltrim(key, -MAX_CANDLE_LEN, -1)
            pipe.execute()
            
            #logger.debug(f"갭 기본 캔들 데이터 저장 완료: {symbol} {tf_str}")
            
            # 인디케이터 계산
            calc_candles = []
            for ts in sorted_ts:
                parts = candle_map[ts]
                calc_candles.append({
                    "timestamp": int(parts[0]),
                    "open": float(parts[1]),
                    "high": float(parts[2]),
                    "low": float(parts[3]),
                    "close": float(parts[4]),
                    "volume": float(parts[5])
                })
            
            # 인디케이터 계산
            if len(calc_candles) > 30:  # 최소한 30개 캔들이 있어야 정확한 지표 계산 가능
                candles_with_ind = compute_all_indicators(calc_candles, rsi_period=14, atr_period=14)
                
                # 한국 시간 추가
                for cndl in candles_with_ind:
                    utc_dt = datetime.fromtimestamp(cndl["timestamp"], UTC)
                    seoul_tz = pytz.timezone("Asia/Seoul")
                    dt_seoul = utc_dt.replace(tzinfo=pytz.utc).astimezone(seoul_tz)
                    cndl["human_time"] = utc_dt.strftime("%Y-%m-%d %H:%M:%S")
                    cndl["human_time_kr"] = dt_seoul.strftime("%Y-%m-%d %H:%M:%S")
                
                # 인디케이터 저장
                self.save_candles_with_indicators(symbol, tf_str, candles_with_ind)
                #logger.debug(f"갭 채우기 완료: {symbol} {tf_str} - {len(candles)}개 캔들 + 인디케이터 계산 완료")
            else:
                logger.warning(f"인디케이터 계산에 필요한 충분한 캔들 데이터가 없습니다: {symbol} {tf_str}")
                
        except Exception as e:
            logger.error(f"캔들 갭 채우기 중 오류: {symbol} {tf_str} - {e}", exc_info=True)
    
    def update_candle_data(self, symbol, tf_str, candle, is_new_candle):
        """캔들 데이터를 Redis에 저장하고 인디케이터 계산"""
        try:
            #logger.debug(f"캔들 데이터 업데이트 시작: {symbol} {tf_str}")
            # 1. 기존 캔들 데이터 가져오기
            key = f"candles:{symbol}:{tf_str}"
            existing = redis_client.lrange(key, 0, -1)
            candle_map = {}
            
            # 기존 데이터 로드
            for item in existing:
                parts = item.split(",")
                ts = int(parts[0])
                candle_map[ts] = parts
            
            # 새 캔들 추가
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
            
            # 정렬 후 저장
            sorted_ts = sorted(candle_map.keys())
            if len(sorted_ts) > MAX_CANDLE_LEN:
                sorted_ts = sorted_ts[-MAX_CANDLE_LEN:]
                
            final_list = [",".join(candle_map[ts]) for ts in sorted_ts]
            
            with redis_client.pipeline() as pipe:
                pipe.delete(key)
                for row_str in final_list:
                    pipe.rpush(key, row_str)
                pipe.ltrim(key, -MAX_CANDLE_LEN, -1)
                pipe.execute()
            
            #logger.debug(f"기본 캔들 데이터 Redis 저장 완료: {key}, 캔들 개수: {len(sorted_ts)}")
            
            # 2. 인디케이터 계산 여부 결정
            combined_key = f"{symbol}:{tf_str}"
            current_time = time.time()
            last_calc_time = self.last_indicator_calc.get(combined_key, 0)
            
            # 다음 조건에 해당하면 인디케이터 계산 수행:
            # 1) 새 캔들이 추가된 경우, 또는
            # 2) 마지막 계산 후 INDICATOR_CALC_INTERVAL초 이상 지난 경우
            should_calc_indicators = is_new_candle or (current_time - last_calc_time >= INDICATOR_CALC_INTERVAL)
            
            if should_calc_indicators and len(sorted_ts) > 30:  # 최소한 30개 캔들이 있어야 정확한 지표 계산 가능
                #logger.debug(f"인디케이터 계산 시작: {symbol} {tf_str} - {'새 캔들' if is_new_candle else '업데이트 캔들'}")
                # 인디케이터 계산을 위한 캔들 데이터 준비
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
                
                # 3. 인디케이터 계산 (새 캔들일 때는 전체, 아닐 때는 마지막 값만 업데이트)
                calc_start_time = time.time()
                if is_new_candle:
                    # 새 캔들이 추가된 경우: 전체 인디케이터 계산
                    #logger.debug(f"전체 인디케이터 계산 시작: {symbol} {tf_str}")
                    candles_with_ind = compute_all_indicators(candles, rsi_period=14, atr_period=14)
                    log_msg = "전체 인디케이터 계산"
                else:
                    # 기존 캔들 업데이트인 경우: 기존 인디케이터 데이터를 불러온 후 마지막 값만 업데이트
                    #logger.debug(f"마지막 캔들 인디케이터만 업데이트: {symbol} {tf_str}")
                    candles_with_ind = self.update_last_candle_indicators(symbol, tf_str, candles)
                    log_msg = "마지막 캔들 인디케이터만 업데이트"
                
                calc_time = time.time() - calc_start_time
                logger.debug(f"인디케이터 계산 완료: {symbol} {tf_str} - {log_msg} (소요시간: {calc_time:.2f}초)")
                
                # 한국 시간 추가
                for cndl in candles_with_ind:
                    utc_dt = datetime.fromtimestamp(cndl["timestamp"], UTC)
                    seoul_tz = pytz.timezone("Asia/Seoul")
                    dt_seoul = utc_dt.replace(tzinfo=pytz.utc).astimezone(seoul_tz)
                    cndl["human_time"] = utc_dt.strftime("%Y-%m-%d %H:%M:%S")
                    cndl["human_time_kr"] = dt_seoul.strftime("%Y-%m-%d %H:%M:%S")
                
                # 4. 인디케이터가 포함된 캔들 데이터 저장
                self.save_candles_with_indicators(symbol, tf_str, candles_with_ind)
                
                # 마지막 계산 시간 업데이트
                self.last_indicator_calc[combined_key] = current_time
                logger.debug(f"{symbol} {tf_str}: {log_msg} 완료 및 저장 완료")
                
        except Exception as e:
            logger.error(f"Error updating candle data: {e}", exc_info=True)
    
    def update_last_candle_indicators(self, symbol, tf_str, candles):
        """기존 인디케이터 데이터를 가져와서 마지막 캔들의 인디케이터만 업데이트"""
        try:
            # 인디케이터가 포함된 기존 캔들 데이터 가져오기
            key = f"candles_with_indicators:{symbol}:{tf_str}"
            existing_list = redis_client.lrange(key, 0, -1)
            
            if not existing_list:
                logger.debug(f"기존 인디케이터 데이터 없음, 전체 계산 시작: {symbol} {tf_str}")
                # 기존 데이터가 없으면 전체 계산
                return compute_all_indicators(candles, rsi_period=14, atr_period=14)
            
            # 기존 데이터 로드
            candle_map = {}
            for item in existing_list:
                try:
                    obj = json.loads(item)
                    if "timestamp" in obj:
                        candle_map[obj["timestamp"]] = obj
                except:
                    pass
            
            # 마지막 캔들에 대해서만 인디케이터 재계산
            last_candle = candles[-1]
            last_ts = last_candle["timestamp"]
            
            # 필요한 캔들 데이터 준비 (마지막 캔들 + 인디케이터 계산에 필요한 이전 캔들들)
            # RSI는 14개 이전 캔들, ATR은 14개 이전 캔들이 필요하므로 최소 15개 준비
            calc_window = 30  # 충분한 여유를 두고 30개로 설정
            
            if len(candles) < calc_window:
                logger.debug(f"부분 계산에 필요한 데이터 부족, 전체 계산 시작: {symbol} {tf_str}")
                # 데이터가 부족하면 전체 계산
                return compute_all_indicators(candles, rsi_period=14, atr_period=14)
            
            # 마지막 캔들과 이전 캔들 추출
            recent_candles = candles[-calc_window:]
            
            # 이 캔들들에 대해서만 인디케이터 계산
            #logger.debug(f"최근 {calc_window}개 캔들에 대해 인디케이터 계산: {symbol} {tf_str}")
            recent_with_ind = compute_all_indicators(recent_candles, rsi_period=14, atr_period=14)
            
            # 마지막 캔들의 인디케이터 값만 업데이트
            if recent_with_ind:
                last_with_ind = recent_with_ind[-1]
                
                # 기존 캔들맵에 마지막 캔들의 인디케이터만 업데이트
                if last_ts in candle_map:
                    # 특정 필드만 업데이트 (OHLCV, 타임스탬프 등은 유지)
                    for key in last_with_ind:
                        if key not in ["timestamp", "open", "high", "low", "close", "volume"]:
                            candle_map[last_ts][key] = last_with_ind[key]
                else:
                    # 기존에 없던 캔들이면 추가
                    candle_map[last_ts] = last_with_ind
            
            # 타임스탬프로 정렬된 캔들 리스트 반환
            sorted_ts = sorted(candle_map.keys())
            #logger.debug(f"마지막 캔들 인디케이터 업데이트 완료: {symbol} {tf_str}")
            return [candle_map[ts] for ts in sorted_ts]
            
        except Exception as e:
            logger.error(f"Error updating last candle indicators: {e}", exc_info=True)
            # 오류 발생 시 전체 재계산
            logger.debug(f"인디케이터 업데이트 중 오류, 전체 계산 시도: {symbol} {tf_str}")
            return compute_all_indicators(candles, rsi_period=14, atr_period=14)
    
    def save_candles_with_indicators(self, symbol, tf_str, candles_with_ind):
        """인디케이터가 포함된 캔들 데이터를 Redis에 저장"""
        try:
            key = f"candles_with_indicators:{symbol}:{tf_str}"
            
            existing_list = redis_client.lrange(key, 0, -1)
            candle_map = {}
            
            for item in existing_list:
                try:
                    obj = json.loads(item)
                    if "timestamp" in obj:
                        candle_map[obj["timestamp"]] = obj
                except:
                    pass
            
            # 새 데이터 덮어쓰기
            for cndl in candles_with_ind:
                ts = cndl["timestamp"]
                candle_map[ts] = cndl
            
            # 정렬 후 저장
            sorted_ts = sorted(candle_map.keys())
            if len(sorted_ts) > MAX_CANDLE_LEN:
                sorted_ts = sorted_ts[-MAX_CANDLE_LEN:]
            
            with redis_client.pipeline() as pipe:
                pipe.delete(key)
                for ts in sorted_ts:
                    row_json = json.dumps(candle_map[ts])
                    pipe.rpush(key, row_json)
                pipe.execute()
            
            #(f"인디케이터 포함 캔들 데이터 저장 완료: {key}, 캔들 개수: {len(sorted_ts)}")
                
        except Exception as e:
            logger.error(f"Error saving candles with indicators: {e}", exc_info=True)

    async def heartbeat(self):
        """정기적으로 ping 을 보내어 연결 유지."""
        while self.connected:
            try:
                await self.ws.send("ping")
                logger.debug("Ping sent to server")
                await asyncio.sleep(20)  # 20초 간격
            except:
                logger.error("Heartbeat failed, connection lost", exc_info=True)
                self.connected = False
                await self.handle_disconnect()
                break
                
    async def receive_messages(self):
        """메시지 수신 루프."""
        #logger.debug("시작: 메시지 수신 루프")
        message_count = 0
        last_log_time = time.time()
        
        while self.connected:
            try:
                message = await self.ws.recv()
                message_count += 1
                
                # 100개 메시지마다 로그
                if message_count % 100 == 0:
                    current_time = time.time()
                    logger.debug(f"메시지 수신 중: 총 {message_count}개 (최근 100개 수신 시간: {current_time - last_log_time:.2f}초)")
                    last_log_time = current_time
                
                if message == "pong":
                    logger.debug("Pong received from server")
                    continue
                    
                await self.handle_message(message)
                
                # 주기적으로 종료 요청 확인
                if shutdown_event.is_set():
                    logger.debug("웹소켓 종료 요청 감지")
                    break
            except websockets.exceptions.ConnectionClosed:
                logger.warning("Connection closed unexpectedly", exc_info=True)
                await self.handle_disconnect()
                break
            except Exception as e:
                logger.error(f"Error receiving message: {e}", exc_info=True)
                await self.handle_disconnect()
                break
    
    async def handle_disconnect(self):
        """예기치 않은 연결 종료 처리"""
        logger.warning("WebSocket disconnected unexpectedly")
        self.connected = False
        
        # 연결 끊김 시간 기록
        current_time = int(time.time())
        for symbol in SYMBOLS:
            for tf_str in self.timeframes.values():
                key = f"{symbol}:{tf_str}"
                self.disconnect_times[key] = current_time
        
        await self.cleanup()
        
        # Redis에 연결 상태 업데이트
        try:
            redis_client.set("websocket_status", "disconnected")
            logger.debug("Redis에 연결 상태 업데이트: disconnected")
        except Exception as e:
            logger.error(f"Error updating Redis status: {e}", exc_info=True)
                
    async def cleanup(self):
        """웹소켓 연결 정리"""
        try:
            if self.ws:
                # 구독 해제 메시지 전송
                unsubscribe_message = {
                    "op": "unsubscribe",
                    "args": [
                        {"channel": channel, "instId": symbol}
                        for symbol in SYMBOLS
                        for channel in self.timeframes.keys()
                    ]
                }
                logger.debug("구독 해제 메시지 전송 중...")
                await self.ws.send(json.dumps(unsubscribe_message))
                await self.ws.close()
                logger.debug("WebSocket connection closed cleanly")
        except Exception as e:
            logger.error(f"Error during cleanup: {e}", exc_info=True)
        finally:
            self.connected = False
            self.ws = None
    
    async def fill_data_gaps(self):
        """연결이 끊긴 동안의 데이터 갭을 채우는 함수"""
        try:
            logger.debug("데이터 갭 확인 시작...")
            
            for symbol in SYMBOLS:
                for tf_str in self.timeframes.values():
                    key = f"{symbol}:{tf_str}"
                    
                    if self.disconnect_times[key] == 0:
                        logger.debug(f"{key}: 연결 끊김 이력 없음, 갭 채우기 불필요")
                        continue  # 이전에 연결 끊김이 없었으면 스킵
                    
                    # 해당 타임프레임의 분 단위 값 구하기
                    tf_minutes = REVERSE_TF_MAP.get(tf_str, 1)
                    
                    # 마지막 캔들 이후 현재까지의 갭 계산
                    last_candle_ts = self.last_candle_timestamp.get(key, 0)
                    current_time = int(time.time())
                    
                    #logger.debug(f"{key}: 마지막 캔들({datetime.fromtimestamp(last_candle_ts)}) 이후 갭 확인 중...")
                    
                    # 갭이 1개 타임프레임 이상인 경우에만 채움
                    if current_time - last_candle_ts > tf_minutes * 60:
                        logger.debug(f"데이터 갭 발견: {key} - {datetime.fromtimestamp(last_candle_ts)} 부터 {datetime.fromtimestamp(current_time)}까지")
                        
                        # gap 채우기 (최대 200개 캔들만)
                        candles = await self.fetch_candles_for_gap(symbol, tf_str, last_candle_ts, current_time, max_candles=200)
                        
                        if candles:
                            #logger.debug(f"{len(candles)}개 캔들 가져옴 - 갭 채우기 시작: {key}")
                            # 순차적으로 캔들 업데이트
                            for candle in candles:
                                # 새 캔들 여부 확인
                                is_new_candle = candle["timestamp"] > self.last_candle_timestamp.get(key, 0)
                                self.update_candle_data(symbol, tf_str, candle, is_new_candle)
                                if is_new_candle:
                                    self.last_candle_timestamp[key] = candle["timestamp"]
                            
                            logger.debug(f"갭 채우기 완료: {key} - {len(candles)}개 캔들")
                        else:
                            logger.warning(f"갭 채우기 실패: {key} - 가져온 캔들 없음")
                    else:
                        logger.debug(f"{key}: 갭 없음 (마지막 캔들 {datetime.fromtimestamp(last_candle_ts)})")
            
            # 갭 채우기 완료 후 연결 끊김 시간 초기화
            for key in self.disconnect_times:
                self.disconnect_times[key] = 0
            
            logger.debug("모든 데이터 갭 채우기 완료")
                
        except Exception as e:
            logger.error(f"Error filling data gaps: {e}", exc_info=True)
    
    async def fetch_candles_for_gap(self, symbol, tf_str, from_ts, to_ts, max_candles=200):
        """특정 기간의 캔들 데이터를 가져오는 함수"""
        try:
            logger.debug(f"캔들 갭 데이터 요청: {symbol} {tf_str} - {datetime.fromtimestamp(from_ts)} 부터 {datetime.fromtimestamp(to_ts)}까지")
            
            # API 호출을 위해 tf_str 형식 조정 ('1H' -> '1h')
            api_tf = tf_str.lower()
            
            params = {'instType': 'SWAP'}
            
            # 시작 시간과 종료 시간을 밀리초로 변환
            from_ms = (from_ts + 1) * 1000  # 마지막 캔들 바로 다음부터
            to_ms = to_ts * 1000
            
            logger.debug(f"API 호출: {symbol} {api_tf} - since {from_ms}, limit {max_candles}")
            
            # 캔들 가져오기 (최대 max_candles개)
            try:
                ohlcvs = exchange.fetch_ohlcv(
                    symbol,
                    timeframe=api_tf,
                    since=from_ms,
                    limit=max_candles,
                    params=params
                )
            except Exception as e:
                logger.error(f"캔들 갭 데이터 API 호출 오류: {symbol} {tf_str} - {e}")
                return []
            
            # 결과 변환
            candles = []
            for row in ohlcvs:
                # None 값 체크 및 오류 처리
                if row is None or len(row) < 6:
                    logger.warning(f"잘못된 캔들 데이터 (None 또는 불완전): {symbol} {tf_str}")
                    continue
                
                try:
                    ts, o, h, l, c, v = row
                    
                    # None 값 체크
                    if ts is None or o is None or h is None or l is None or c is None or v is None:
                        logger.warning(f"캔들 데이터에 None 값 포함: {symbol} {tf_str} - {row}")
                        continue
                    
                    candles.append({
                        "timestamp": int(ts) // 1000,
                        "open": float(o),
                        "high": float(h),
                        "low": float(l),
                        "close": float(c),
                        "volume": float(v)
                    })
                except (TypeError, ValueError) as e:
                    logger.warning(f"캔들 데이터 변환 오류: {symbol} {tf_str} - {row} - {e}")
                    continue
            
            logger.debug(f"API에서 {len(candles)}개 캔들 가져옴: {symbol} {tf_str}")
            if candles:
                earliest = datetime.fromtimestamp(candles[0]["timestamp"]).strftime("%Y-%m-%d %H:%M:%S")
                latest = datetime.fromtimestamp(candles[-1]["timestamp"]).strftime("%Y-%m-%d %H:%M:%S")
                logger.debug(f"캔들 기간: {earliest} ~ {latest}")
                
            return candles
            
        except Exception as e:
            logger.error(f"Error fetching candles for gap: {e}", exc_info=True)
            return []

    async def check_data_health(self):
        """각 종목별 데이터 수신 상태 확인"""
        while self.connected:
            try:
                await asyncio.sleep(60)  # 1분마다 확인
                current_time = time.time()
                
                # 모든 종목/타임프레임 확인
                for symbol in SYMBOLS:
                    for tf_str in self.timeframes.values():
                        key = f"{symbol}:{tf_str}"
                        last_received = self.last_data_received.get(key, 0)
                        
                        # 타임프레임에 따라 적절한 타임아웃 설정 (타임프레임의 최소 2배)
                        tf_minutes = REVERSE_TF_MAP.get(tf_str, 1)
                        timeout = max(tf_minutes * 120, self.data_timeout)  # 초 단위
                        
                        # 타임아웃 체크
                        if last_received > 0 and current_time - last_received > timeout:
                            logger.warning(f"{key}: {timeout}초 동안 데이터 수신 없음, 재구독 시도")
                            
                            # 해당 종목만 재구독
                            await self.resubscribe_symbol(symbol, tf_str)
                            
                            # 데이터 갭 채우기
                            last_ts = self.last_candle_timestamp.get(key, 0)
                            if last_ts > 0:
                                logger.info(f"{key}: 데이터 갭 채우기 시작")
                                candles = await self.fetch_candles_for_gap(
                                    symbol, tf_str, last_ts, current_time, max_candles=200
                                )
                                
                                if candles:
                                    for candle in candles:
                                        is_new_candle = candle["timestamp"] > self.last_candle_timestamp.get(key, 0)
                                        self.update_candle_data(symbol, tf_str, candle, is_new_candle)
                                        if is_new_candle:
                                            self.last_candle_timestamp[key] = candle["timestamp"]
                                    logger.info(f"{key}: 데이터 갭 채우기 완료 - {len(candles)}개 캔들")
            except Exception as e:
                logger.error(f"데이터 상태 확인 중 오류: {e}", exc_info=True)
                
    async def resubscribe_symbol(self, symbol, tf_str):
        """특정 종목/타임프레임만 재구독"""
        try:
            # 해당 타임프레임에 맞는 채널 찾기
            target_channel = None
            for channel, tf in self.timeframes.items():
                if tf == tf_str:
                    target_channel = channel
                    break
                    
            if not target_channel:
                logger.error(f"재구독 실패: {symbol} {tf_str} - 해당 채널 찾을 수 없음")
                return
                
            # 구독 취소 후 재구독
            unsubscribe_message = {
                "op": "unsubscribe",
                "args": [{
                    "channel": target_channel,
                    "instId": symbol
                }]
            }
            
            subscribe_message = {
                "op": "subscribe",
                "args": [{
                    "channel": target_channel,
                    "instId": symbol
                }]
            }
            
            logger.debug(f"{symbol} {tf_str} 구독 갱신 중...")
            await self.ws.send(json.dumps(unsubscribe_message))
            await asyncio.sleep(1)  # 잠시 대기
            await self.ws.send(json.dumps(subscribe_message))
            logger.debug(f"{symbol} {tf_str} 재구독 요청 완료")
            
        except Exception as e:
            logger.error(f"재구독 중 오류: {e}", exc_info=True)

    async def run(self):
        """메인 실행 루프"""
        reconnect_attempts = 0
        try:
            while self.should_run and not shutdown_event.is_set():
                if not self.connected:
                    try:
                        reconnect_attempts += 1
                        logger.debug(f"WebSocket 연결 시도 #{reconnect_attempts}...")
                        await self.connect()
                        if self.connected:
                            reconnect_attempts = 0
                            logger.debug("WebSocket 연결 성공, 데이터 갭 채우기 시작...")
                            # 연결되었으면 데이터 갭 채우기
                            await self.fill_data_gaps()
                            
                            logger.debug("모든 작업 시작: 메시지 수신, 하트비트, 상태 로깅, 데이터 상태 확인")
                            await asyncio.gather(
                                self.receive_messages(),
                                self.heartbeat(),
                                self.log_status(),
                                self.check_data_health()  # 데이터 건강 체크 추가
                            )
                    except Exception as e:
                        logger.error(f"Run error: {e}", exc_info=True)
                        # 백오프 지연 추가 (많은 실패 시 더 길게 대기)
                        wait_time = min(5 * reconnect_attempts, 60)
                        logger.debug(f"재연결 전 {wait_time}초 대기...")
                        await asyncio.sleep(wait_time)
                        continue
                await asyncio.sleep(5)  # 재연결 시도 전 대기
                
                # 주기적으로 종료 요청 확인
                if shutdown_event.is_set():
                    logger.debug("웹소켓 종료 요청 감지")
                    break
        except Exception as e:
            logger.error(f"웹소켓 실행 중 오류: {e}", exc_info=True)
        finally:
            if self.ws:
                await self.ws.close()
                logger.debug("웹소켓 연결 종료됨")
            self.connected = False

    async def request_shutdown(self):
        """안전한 종료를 위한 메서드"""
        logger.debug("웹소켓 안전 종료 요청...")
        self.should_run = False
        if self.ws:
            try:
                await self.ws.close()
                logger.debug("웹소켓 연결 종료 완료")
            except Exception as e:
                logger.error(f"웹소켓 종료 중 오류: {e}")

# ============================================================================
# 캔들 데이터 처리 함수 (from tasks.py)
# ============================================================================

def align_timestamp(ts_ms: int, timeframe: int) -> int:
    """타임스탬프를 캔들 마감시간에 맞춰 정렬"""
    minutes = timeframe
    ms_per_minute = 60 * 1000
    return (ts_ms // (minutes * ms_per_minute)) * (minutes * ms_per_minute)

def get_exchange_candles_full(symbol: str, timeframe: int, desired_count=3000):
    """거래소에서 캔들 데이터 불러오기 (초기 로드용)"""
    tf_str = TF_MAP.get(timeframe, "1m")
    key = f"candles:{symbol}:{tf_str}"
    params = {
        'instType': 'SWAP',  # SWAP은 영구선물을 의미
    }
    # 1. 현재 시간을 캔들 마감시간에 맞춤
    now_ms = align_timestamp(exchange.milliseconds(), timeframe)
    current_ts = now_ms // 1000
    ms_per_tf = timeframe * 60 * 1000
    
    logger.debug(f"캔들 데이터 불러오기: {symbol} {tf_str} - 목표 개수: {desired_count}")
    
    # 1. 기존 Redis 데이터 확인
    existing_candles = redis_client.lrange(key, 0, -1)
    existing_map = {}
    
    if existing_candles:
        logger.debug(f"Redis에서 {len(existing_candles)}개 기존 캔들 로드: {key}")
        for candle_str in existing_candles:
            ts, o, h, l, c, v = candle_str.split(',')
            ts_ms = int(ts) * 1000
            aligned_ts = align_timestamp(ts_ms, timeframe) // 1000
            existing_map[aligned_ts] = {
                "timestamp": aligned_ts,
                "open": float(o),
                "high": float(h),
                "low": float(l),
                "close": float(c),
                "volume": float(v)
            }
    
    # 갭 계산 시에도 정렬된 시간 사용
    gaps = []
    if existing_map:
        last_ts = max(existing_map.keys())
        first_ts = min(existing_map.keys())
        
        # 최신 데이터부터 현재까지의 갭
        if (current_ts - last_ts) > timeframe * 60:
            start_ms = (last_ts + timeframe * 60) * 1000
            gaps.append({
                'start': align_timestamp(start_ms, timeframe),
                'end': now_ms
            })
            logger.debug(f"최신 데이터 갭 발견: {datetime.fromtimestamp(last_ts)} ~ {datetime.fromtimestamp(current_ts)}")
        
        # 기존 데이터 내의 갭들 확인 (이미 정렬된 시간 사용)
        current_check_ts = first_ts
        gap_count = 0
        while current_check_ts < last_ts:
            next_expected_ts = current_check_ts + timeframe * 60
            if next_expected_ts not in existing_map:
                gap_start = next_expected_ts
                while next_expected_ts not in existing_map and next_expected_ts < last_ts:
                    next_expected_ts += timeframe * 60
                gaps.append({
                    'start': gap_start * 1000,
                    'end': next_expected_ts * 1000
                })
                gap_count += 1
            current_check_ts = next_expected_ts
            
        if gap_count > 0:
            logger.debug(f"기존 데이터 내 {gap_count}개 갭 발견")
    else:
        start_ms = now_ms - (ms_per_tf * desired_count)
        gaps.append({
            'start': align_timestamp(start_ms, timeframe),
            'end': now_ms
        })
        logger.debug(f"기존 데이터 없음, 전체 캔들 로드 필요: {datetime.fromtimestamp(start_ms/1000)} ~ {datetime.fromtimestamp(now_ms/1000)}")
    
    # 갭 채우기
    fetch_limit = 100
    total_fetched = 0
    
    for gap_idx, gap in enumerate(gaps):
        logger.debug(f"갭 #{gap_idx+1} 채우기 시작: {datetime.fromtimestamp(gap['start']/1000)} ~ {datetime.fromtimestamp(gap['end']/1000)}")
        current_end = gap['end']
        while current_end > gap['start']:
            try:
                current_start = max(gap['start'], current_end - (ms_per_tf * fetch_limit))
                
                # 시작과 끝 시간을 캔들 마감시간에 맞춤
                aligned_start = align_timestamp(current_start, timeframe)
                aligned_end = align_timestamp(current_end, timeframe)
                    
                # 재시도 로직 (최대 5회 재시도, 지수 백오프)
                max_retries = 5
                attempt = 0
                while True:
                    try:
                        logger.debug(f"API 호출: {symbol} {tf_str} - since {aligned_start}, end {aligned_end}")
                        ohlcvs = exchange.fetch_ohlcv(
                            symbol,
                            timeframe=tf_str,
                            since=aligned_start,
                            limit=fetch_limit,
                            params={'end': aligned_end, 'instType': 'SWAP'}
                        )
                        break  # 성공하면 반복문 탈출
                    except ccxt.RateLimitExceeded as e:
                        attempt += 1
                        if attempt >= max_retries:
                            logger.error(f"Max retries reached for rate limit on {symbol} ({tf_str}). Error: {e}")
                            raise e
                        wait_time = 2 ** attempt  # 지수 백오프: 2, 4, 8, ... 초
                        logger.warning(f"Rate limit exceeded for {symbol} ({tf_str}). Waiting {wait_time} seconds before retrying... (Attempt {attempt}/{max_retries})")
                        time.sleep(wait_time)
                    except Exception as e:
                        logger.error(f"Error fetching gap data for {symbol} ({tf_str}): {e}")
                        # 다른 예외의 경우 해당 구간은 건너뛰거나 적절히 처리할 수 있습니다.
                        ohlcvs = []
                        break

                #logger.debug(f"{symbol} {len(ohlcvs)}개 캔들 가져옴: {tf_str} 구간: {datetime.fromtimestamp(aligned_start/1000)} ~ {datetime.fromtimestamp(aligned_end/1000)}")
                total_fetched += len(ohlcvs)
                
                for row in ohlcvs:
                    ts, o, h, l, c, v = row
                    aligned_ts = align_timestamp(ts, timeframe) // 1000
                    existing_map[aligned_ts] = {
                        "timestamp": aligned_ts,
                        "open": float(o),
                        "high": float(h),
                        "low": float(l),
                        "close": float(c),
                        "volume": float(v)
                    }
                time.sleep(0.02)
                current_end = aligned_start
                
            except Exception as e:
                logger.error(f"Error fetching gap data: {e}", exc_info=True)
                break

    # 결과 정렬 및 반환
    sorted_ts = sorted(existing_map.keys())
    if len(sorted_ts) > desired_count:
        sorted_ts = sorted_ts[-desired_count:]
    
    results = [existing_map[ts] for ts in sorted_ts]
    logger.debug(f"캔들 데이터 로드 완료: {symbol} {tf_str} - {len(results)}개 캔들 (API에서 {total_fetched}개 가져옴)")
    
    return results

def save_candles_to_redis(symbol: str, timeframe: int, new_candles: list):
    """캔들 데이터를 Redis에 저장"""
    tf_str = TF_MAP.get(timeframe, "1m")
    key = f"candles:{symbol}:{tf_str}"
    existing = redis_client.lrange(key, 0, -1)
    candle_map = {}

    #logger.debug(f"캔들 데이터 Redis 저장 시작: {key} - 기존 {len(existing)}개, 새로운 {len(new_candles)}개")

    # 기존 데이터 로드
    for item in existing:
        # "ts,open,high,low,close,vol" 형태
        parts = item.split(",")
        ts = int(parts[0])
        candle_map[ts] = parts

    # 새 데이터 병합
    for cndl in new_candles:
        ts = cndl["timestamp"]
        # 직렬화
        cndl_str_list = [
            str(ts),
            str(cndl["open"]),
            str(cndl["high"]),
            str(cndl["low"]),
            str(cndl["close"]),
            str(cndl["volume"]),
        ]
        candle_map[ts] = cndl_str_list

    # 정렬 후 rpush
    sorted_ts = sorted(candle_map.keys())
    final_list = [",".join(candle_map[ts]) for ts in sorted_ts]

    # 시간 범위 로깅
    if sorted_ts:
        earliest = datetime.fromtimestamp(sorted_ts[0]).strftime("%Y-%m-%d %H:%M:%S")
        latest = datetime.fromtimestamp(sorted_ts[-1]).strftime("%Y-%m-%d %H:%M:%S")
        #logger.debug(f"저장할 캔들 범위: {earliest} ~ {latest}")

    pipe = redis_client.pipeline()
    pipe.delete(key)
    for row_str in final_list:
        pipe.rpush(key, row_str)
    pipe.ltrim(key, -MAX_CANDLE_LEN, -1)
    pipe.execute()
    
    #logger.debug(f"캔들 데이터 Redis 저장 완료: {key} - 총 {len(final_list)}개 캔들")

def save_candles_with_indicators_to_redis(symbol: str, timeframe: int, candles_with_ind: list):
    """인디케이터가 포함된 캔들 데이터를 Redis에 저장"""
    tf_str = TF_MAP.get(timeframe, "1m")
    key = f"candles_with_indicators:{symbol}:{tf_str}"

    logger.debug(f"인디케이터 포함 캔들 Redis 저장 시작: {key} - {len(candles_with_ind)}개")

    existing_list = redis_client.lrange(key, 0, -1)
    candle_map = {}

    for item in existing_list:
        try:
            obj = json.loads(item)
            if "timestamp" in obj:
                candle_map[obj["timestamp"]] = obj
        except:
            pass

    # 새 데이터 덮어쓰기
    for cndl in candles_with_ind:
        ts = cndl["timestamp"]
        # 한국 시간 추가
        utc_dt = datetime.fromtimestamp(ts, UTC)
        seoul_tz = pytz.timezone("Asia/Seoul")
        dt_seoul = utc_dt.replace(tzinfo=pytz.utc).astimezone(seoul_tz)
        cndl["human_time"] = utc_dt.strftime("%Y-%m-%d %H:%M:%S")
        cndl["human_time_kr"] = dt_seoul.strftime("%Y-%m-%d %H:%M:%S")
        candle_map[ts] = cndl

    # 정렬 후 저장
    sorted_ts = sorted(candle_map.keys())
    if len(sorted_ts) > MAX_CANDLE_LEN:
        sorted_ts = sorted_ts[-MAX_CANDLE_LEN:]

    # 시간 범위 로깅
    if sorted_ts:
        earliest = datetime.fromtimestamp(sorted_ts[0]).strftime("%Y-%m-%d %H:%M:%S")
        latest = datetime.fromtimestamp(sorted_ts[-1]).strftime("%Y-%m-%d %H:%M:%S")
        logger.debug(f"저장할 인디케이터 포함 캔들 범위: {earliest} ~ {latest}")

    pipe = redis_client.pipeline()
    pipe.delete(key)
    for ts in sorted_ts:
        row_json = json.dumps(candle_map[ts])
        pipe.rpush(key, row_json)
    pipe.execute()
    
    logger.debug(f"인디케이터 포함 캔들 Redis 저장 완료: {key} - 총 {len(sorted_ts)}개 캔들")

def fetch_and_process_all_candles():
    """모든 심볼과 타임프레임에 대해 캔들 데이터를 가져와 처리하는 함수 (초기 로드용)"""
    lock_key = "lock:fetch_all_candles"
    lock = redis_client.lock(lock_key, timeout=300)  # 초기 로드는 시간이 오래 걸릴 수 있으므로 타임아웃 증가
    
    if not lock.acquire(blocking=False):
        logger.debug("Another fetch_all_candles task is running")
        return
        
    start_ts = time.time()
    try:
        logger.debug("========= 모든 심볼/타임프레임 초기 데이터 로드 시작 =========")
        for symbol in SYMBOLS:
            for tf in TIMEFRAMES:
                tf_str = TF_MAP.get(tf, "1m")
                key = f"{symbol}:{tf_str}"
                
                logger.debug(f"[시작] 초기 데이터 로드: {key}")
                
                candles = get_exchange_candles_full(symbol, tf, desired_count=3000)
                save_candles_to_redis(symbol, tf, candles)
                
                # 마지막 캔들 타임스탬프 저장 (웹소켓 연결 후 사용)
                if candles:
                    # Redis에 마지막 캔들 타임스탬프 저장
                    redis_client.set(f"last_candle_ts:{key}", str(candles[-1]["timestamp"]))
                    logger.debug(f"마지막 캔들 타임스탬프 저장: {key} - {datetime.fromtimestamp(candles[-1]['timestamp'])}")
                
                #logger.debug(f"인디케이터 계산 시작: {key}")
                candles_with_ind = compute_all_indicators(candles, rsi_period=14, atr_period=14)
                for cndl in candles_with_ind:
                    utc_dt = datetime.fromtimestamp(cndl["timestamp"], UTC)
                    cndl["human_time"] = utc_dt.strftime("%Y-%m-%d %H:%M:%S")
                    
                    seoul_tz = pytz.timezone("Asia/Seoul")
                    dt_seoul = utc_dt.replace(tzinfo=pytz.utc).astimezone(seoul_tz)
                    cndl["human_time_kr"] = dt_seoul.strftime("%Y-%m-%d %H:%M:%S")

                save_candles_with_indicators_to_redis(symbol, tf, candles_with_ind)
                
                logger.debug(f"[완료] 초기 데이터 로드: {key} - {len(candles)}개 캔들")

        execution_time = time.time() - start_ts
        logger.debug(f"========= 모든 초기 데이터 로드 완료 (소요시간: {execution_time:.2f}초) =========")
        
        redis_client.hset(
            "task_status:fetch_all_candles",
            "last_execution",
            json.dumps({
                "timestamp": datetime.now(UTC).isoformat(),
                "status": "success",
                "execution_time": f"{execution_time:.2f}s"
            })
        )
    except Exception as e:
        logger.error(f"Error in fetch_and_process_all_candles: {e}", exc_info=True)
        redis_client.hset(
            "task_status:fetch_all_candles",
            "last_execution",
            json.dumps({
                "timestamp": datetime.now(UTC).isoformat(),
                "status": "error",
                "error": str(e)
            })
        )
    finally:
        lock.release()  # 항상 lock 해제
        logger.debug("Lock 해제 완료: fetch_all_candles")

# ============================================================================
# 메인 함수: 웹소켓 태스크만 실행 (초기 로드 이후 웹소켓만 사용)
# ============================================================================

async def websocket_task():
    """웹소켓 태스크"""
    logger.debug("웹소켓 태스크 시작...")
    ws_client = OKXMultiTimeframeWebSocket()
    
    # Redis에서 마지막 캔들 타임스탬프 로드
    for symbol in SYMBOLS:
        for tf_str in ws_client.timeframes.values():
            key = f"{symbol}:{tf_str}"
            last_ts = redis_client.get(f"last_candle_ts:{key}")
            if last_ts:
                ts_int = int(last_ts)
                ws_client.last_candle_timestamp[key] = ts_int
                logger.debug(f"마지막 캔들 타임스탬프 로드: {key} - {datetime.fromtimestamp(ts_int)}")
            else:
                logger.warning(f"마지막 캔들 타임스탬프 없음: {key}")
    
    logger.debug("웹소켓 클라이언트 실행 중...")
    await ws_client.run()

def start_websocket_task():
    """웹소켓 태스크를 비동기로 실행"""
    logger.debug("웹소켓 비동기 태스크 시작...")
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    # 웹소켓 클라이언트 인스턴스 생성
    ws_client = OKXMultiTimeframeWebSocket()
    
    # 전역 변수에 저장 (메인 스레드에서 접근 가능하도록)
    global current_ws_client, current_loop
    current_ws_client = ws_client
    current_loop = loop
    
    
    try:
        # 최대 재시도 횟수 설정
        max_retries = 5
        retry_count = 0
        
        while retry_count < max_retries and not shutdown_event.is_set():
            try:
                loop.run_until_complete(ws_client.run())
                # 정상 종료면 루프 탈출
                if not ws_client.should_run or shutdown_event.is_set():
                    break
                # 예외로 종료된 경우 재시도
                logger.warning(f"웹소켓 연결이 끊어짐. 재연결 시도 {retry_count+1}/{max_retries}")
                retry_count += 1
                # 지수 백오프 적용 (1초, 2초, 4초, 8초, 16초)
                time.sleep(2 ** retry_count)
            except Exception as e:
                logger.error(f"웹소켓 실행 중 오류, 재시도 중: {e}", exc_info=True)
                retry_count += 1
                time.sleep(2 ** retry_count)
    except Exception as e:
        logger.error(f"웹소켓 태스크 실행 중 오류: {e}", exc_info=True)
    finally:
        logger.debug("웹소켓 태스크 종료")
        # 루프 정리
        try:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.close()
        except Exception as e:
            logger.error(f"비동기 루프 정리 중 오류: {e}")

def main():
    """초기 데이터 로드 후 웹소켓만으로 데이터 유지"""
    try:
        logger.debug("=== 통합 데이터 수집기 시작 ===")
        # 전역 변수 추가
        global current_ws_client, current_loop
        current_ws_client = None
        current_loop = None
        
        # 초기 데이터 로드 (최초 1회만 실행)
        logger.warning("초기 데이터 로드 시작...")
        fetch_and_process_all_candles()
        logger.warning("초기 데이터 로드 완료")

        # 웹소켓 스레드 시작 (이후로는 웹소켓만으로 데이터 유지)
        logger.warning("웹소켓 스레드 시작...")
        ws_thread = threading.Thread(target=start_websocket_task, daemon=True)
        ws_thread.start()
        logger.warning("웹소켓 스레드 시작됨")

        # 메인 스레드는 웹소켓 상태 확인 및 주기적인 상태 로깅
        restart_count = 0
        try:
            while True:
                try:
                    time.sleep(60)
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    logger.debug(f"[{timestamp}] 메인 스레드 상태 확인 - 웹소켓 활성 상태: {ws_thread.is_alive()}")
                    
                    # 웹소켓 스레드 상태 확인
                    if not ws_thread.is_alive():
                        restart_count += 1
                        logger.error(f"웹소켓 스레드 죽음, 재시작 중... (재시작 횟수: {restart_count})")
                        
                        # 이전 스레드 정리 시도
                        if current_ws_client and current_loop:
                            try:
                                asyncio.run_coroutine_threadsafe(
                                    current_ws_client.request_shutdown(),
                                    current_loop
                                )
                            except Exception as e:
                                logger.error(f"웹소켓 종료 요청 중 오류: {e}")
                        
                        # 새 스레드 시작
                        ws_thread = threading.Thread(target=start_websocket_task, daemon=True)
                        ws_thread.start()
                        logger.debug("웹소켓 스레드 재시작됨")
                except Exception as e:
                    logger.error(f"메인 스레드 감시 중 오류: {e}", exc_info=True)
        except KeyboardInterrupt:
            logger.debug("키보드 인터럽트 감지, 종료 중...")
            # 안전한 종료 요청
            shutdown_event.set()
            # 현재 웹소켓 클라이언트 종료 요청
            if current_ws_client:
                try:
                    asyncio.run_coroutine_threadsafe(
                        current_ws_client.request_shutdown(),
                        asyncio.get_event_loop()
                    )
                except Exception as e:
                    logger.error(f"웹소켓 종료 요청 중 오류: {e}")
            # 웹소켓 스레드 종료 대기
            ws_thread.join(timeout=5)
            logger.warning("웹소켓 스레드 종료됨")

    except KeyboardInterrupt:
        logger.warning("키보드 인터럽트 감지, 종료 중...")
        shutdown_event.set()
    except Exception as e:
        logger.error(f"메인 실행 중 오류: {e}", exc_info=True)
    finally:
        logger.warning("=== 통합 데이터 수집기 종료 ===")

if __name__ == "__main__":
    logger.warning("===== 프로그램 시작 =====")
    main() 