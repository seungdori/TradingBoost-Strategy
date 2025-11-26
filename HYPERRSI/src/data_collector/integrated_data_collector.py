#!/usr/bin/env python
# -*- coding: utf-8 -*-
# src/data_collector/polling_data_collector.py

import json
import logging
import threading
import time
from datetime import UTC, datetime

import ccxt
import pytz
import redis

from HYPERRSI.src.config import OKX_API_KEY, OKX_PASSPHRASE, OKX_SECRET_KEY
from HYPERRSI.src.core.config import settings
from HYPERRSI.src.trading.models import get_auto_trend_timeframe
from shared.indicators import compute_all_indicators, add_auto_trend_state_to_candles
from shared.logging import get_logger

# 로깅 설정
logger = get_logger(__name__)
logging.basicConfig(level=logging.WARNING, format='%(asctime)s - %(levelname)s - %(message)s')

# 설정 및 상수
SYMBOLS = ["BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP"]
TIMEFRAMES = [1, 3, 5, 15, 30, 60, 240]  # 분 단위
TF_MAP = {1: '1m', 3: '3m', 5: '5m', 15: '15m', 30: '30m', 60: '1h', 240: '4h'}
MAX_CANDLE_LEN = 3000
POLLING_CANDLES = 10  # 한 번에 폴링할 캔들 수 (바 종료 시점에 최신 몇 개만 확인)
MIN_CANDLES_FOR_INDICATORS = 199  # 지표 계산에 필요한 최소 캔들 수 (SMA200은 인덱스 199부터 정확하게 계산됨)

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

# OKX API 설정
OKX_API_KEY = OKX_API_KEY
OKX_SECRET = OKX_SECRET_KEY
OKX_PASSPHRASE = OKX_PASSPHRASE

exchange = ccxt.okx({
    'apiKey': OKX_API_KEY,
    'secret': OKX_SECRET,
    'password': OKX_PASSPHRASE,
    'enableRateLimit': True,
    'timeout': 30000,  # 30초 타임아웃 (네트워크 지연 대응)
    'options': {
        'defaultType': 'swap',
        'adjustForTimeDifference': True,  # 서버 시간 차이 자동 조정
        'recvWindow': 10000,  # 요청 수신 윈도우 10초
    }
})






# 안전한 종료를 위한 이벤트 객체
shutdown_event = threading.Event()

# 초기 데이터 로드 완료 플래그
initial_data_loaded = threading.Event()

# 마지막 캔들 타임스탬프 및 마지막 체크 시간 저장
last_candle_timestamps: dict[str, int] = {}
last_check_times: dict[str, float] = {}

from shared.utils.time_helpers import align_timestamp, calculate_update_interval, is_bar_end

# CandlesDB Writer
from HYPERRSI.src.data_collector.candlesdb_writer import get_candlesdb_writer
candlesdb_writer = get_candlesdb_writer()


def _get_candles_from_redis_for_auto_trend(symbol: str, tf_str: str) -> list:
    """
    Redis에서 auto_trend_state 계산용 캔들 데이터 가져오기

    Args:
        symbol: 심볼 (예: "BTC-USDT-SWAP")
        tf_str: 타임프레임 문자열 (예: "30m", "1h")

    Returns:
        캔들 리스트 (timestamp, close 포함)
    """
    key = f"candles_with_indicators:{symbol}:{tf_str}"
    try:
        existing_list = redis_client.lrange(key, 0, -1)
        candles = []
        for item in existing_list:
            try:
                item_str = item.decode('utf-8') if isinstance(item, bytes) else item
                obj = json.loads(item_str)
                if "timestamp" in obj and "close" in obj:
                    candles.append(obj)
            except Exception:
                pass
        return candles
    except Exception as e:
        logger.warning(f"Redis에서 auto_trend 캔들 가져오기 실패: {symbol} {tf_str} - {e}")
        return []


def fetch_latest_candles(symbol, timeframe, limit=POLLING_CANDLES, include_current=False):
    """
    최신 캔들 데이터 가져오기
    OKX API는 최대 300개까지만 반환하므로, limit이 300보다 크면 여러 번 요청
    """
    tf_str = TF_MAP.get(timeframe, "1m")
    logger.debug(f"최신 캔들 폴링: {symbol} {tf_str} - {limit}개 요청 (현재 진행 캔들 포함: {include_current})")

    try:
        OKX_MAX_LIMIT = 300  # OKX API 최대 limit
        all_candles = []

        # limit이 300 이하면 한 번만 요청
        if limit <= OKX_MAX_LIMIT:
            ohlcvs = _fetch_ohlcv_with_retry(symbol, tf_str, limit, None)
            if not ohlcvs:
                return []
            all_candles = _parse_ohlcv_data(symbol, tf_str, timeframe, ohlcvs, include_current)
        else:
            # limit이 300보다 크면 여러 번 요청
            # OKX API는 since를 기준으로 이후 데이터를 반환하므로, 과거로 가려면 다른 방식 필요
            total_batches = (limit + OKX_MAX_LIMIT - 1) // OKX_MAX_LIMIT  # ceil division
            logger.info(f"총 {total_batches}번의 배치 요청 예정: {symbol} {tf_str}")

            for batch_num in range(total_batches):
                batch_limit = min(limit - len(all_candles), OKX_MAX_LIMIT)
                if batch_limit <= 0:
                    break

                # since 계산: 이미 가진 가장 오래된 캔들보다 더 과거
                if all_candles:
                    # 가장 오래된 캔들의 timestamp (초 단위)
                    oldest_ts = min(c["timestamp"] for c in all_candles)
                    # 타임프레임 길이를 고려해서 그 이전 시점 계산
                    tf_seconds = timeframe * 60
                    since = (oldest_ts - batch_limit * tf_seconds) * 1000  # milliseconds
                    logger.info(f"캔들 배치 #{batch_num+1} 요청: {symbol} {tf_str} - {batch_limit}개 (since: {datetime.fromtimestamp(since/1000)})")
                else:
                    # 첫 요청은 최신부터
                    since = None
                    logger.info(f"캔들 배치 #{batch_num+1} 요청: {symbol} {tf_str} - {batch_limit}개 (최신부터)")

                ohlcvs = _fetch_ohlcv_with_retry(symbol, tf_str, batch_limit, since)
                if not ohlcvs:
                    logger.warning(f"캔들 배치 요청 실패: {symbol} {tf_str}")
                    break

                batch_candles = _parse_ohlcv_data(symbol, tf_str, timeframe, ohlcvs, include_current)
                if not batch_candles:
                    logger.warning(f"파싱된 캔들 없음: {symbol} {tf_str}")
                    break

                # 중복 제거하면서 병합
                added_count = 0
                for candle in batch_candles:
                    if not any(c["timestamp"] == candle["timestamp"] for c in all_candles):
                        all_candles.append(candle)
                        added_count += 1

                logger.info(f"배치 #{batch_num+1} 완료: {added_count}개 새 캔들 추가 (총 {len(all_candles)}개)")

                # 새로 추가된 캔들이 없으면 중단 (더 이상 과거 데이터 없음)
                if added_count == 0:
                    logger.info(f"더 이상 가져올 캔들 없음: {symbol} {tf_str}")
                    break

                # 목표 개수 달성하면 중단
                if len(all_candles) >= limit:
                    logger.info(f"목표 개수 달성: {symbol} {tf_str} - {len(all_candles)}개")
                    break

                # API rate limit 고려
                time.sleep(0.5)

            # 시간순 정렬
            all_candles.sort(key=lambda x: x["timestamp"])
            logger.info(f"총 {len(all_candles)}개 캔들 수집 완료: {symbol} {tf_str}")

        return all_candles

    except Exception as e:
        logger.error(f"캔들 데이터 가져오기 오류: {symbol} {tf_str} - {e}", exc_info=True)
        # errordb 로깅
        from HYPERRSI.src.utils.error_logger import log_error_to_db
        log_error_to_db(
            error=e,
            error_type="CandleDataFetchError",
            severity="ERROR",
            symbol=symbol,
            metadata={"timeframe": tf_str, "component": "integrated_data_collector.fetch_latest_candles"}
        )
        return []


def _fetch_ohlcv_with_retry(symbol, tf_str, limit, since):
    """OHLCV 데이터 가져오기 (재시도 로직 포함)"""
    max_retries = 5
    attempt = 0

    while True:
        try:
            params = {'instType': 'SWAP'}
            logger.debug(f"API 요청: symbol={symbol}, timeframe={tf_str.lower()}, limit={limit}, since={since}")

            if since is None:
                ohlcvs = exchange.fetch_ohlcv(
                    symbol,
                    timeframe=tf_str.lower(),
                    limit=limit,
                    params=params
                )
            else:
                ohlcvs = exchange.fetch_ohlcv(
                    symbol,
                    timeframe=tf_str.lower(),
                    since=since,
                    limit=limit,
                    params=params
                )
            return ohlcvs

        except ccxt.RateLimitExceeded as e:
            attempt += 1
            if attempt >= max_retries:
                logger.error(f"최대 재시도 횟수 초과: {symbol} ({tf_str}). 오류: {e}")
                raise e
            wait_time = 2 ** attempt
            logger.warning(f"속도 제한 초과: {symbol} ({tf_str}). {wait_time}초 대기 후 재시도... (시도 {attempt}/{max_retries})")
            time.sleep(wait_time)
        except Exception as e:
            logger.error(f"OHLCV 데이터 가져오기 실패: {symbol} ({tf_str}). 오류: {e}")
            # errordb 로깅
            from HYPERRSI.src.utils.error_logger import log_error_to_db
            log_error_to_db(
                error=e,
                error_type="OHLCVFetchError",
                severity="WARNING",
                symbol=symbol,
                metadata={"timeframe": tf_str, "limit": limit, "since": since, "component": "integrated_data_collector._fetch_ohlcv_with_retry"}
            )
            return []


def _parse_ohlcv_data(symbol, tf_str, timeframe, ohlcvs, include_current):
    """OHLCV 데이터 파싱"""
    candles = []
    for row in ohlcvs:
        # None 값 체크 추가
        if row is None or len(row) < 6:
            logger.warning(f"잘못된 캔들 데이터 (None 또는 불완전): {symbol} {tf_str}")
            continue

        try:
            ts, o, h, l, c, v = row
            # None 값 타입 체크 및 변환
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
            # Redis returns bytes, decode to string first
            item_str = item.decode('utf-8') if isinstance(item, bytes) else item
            parts = item_str.split(",")
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
        # errordb 로깅
        from HYPERRSI.src.utils.error_logger import log_error_to_db
        log_error_to_db(
            error=e,
            error_type="CandleGapCheckError",
            severity="WARNING",
            symbol=symbol,
            metadata={"timeframe": tf_str, "component": "integrated_data_collector.check_and_fill_gap"}
        )

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
        # errordb 로깅
        from HYPERRSI.src.utils.error_logger import log_error_to_db
        log_error_to_db(
            error=e,
            error_type="CandleGapFillError",
            severity="WARNING",
            symbol=symbol,
            metadata={"timeframe": tf_str, "from_ts": from_ts, "to_ts": to_ts, "component": "integrated_data_collector.fill_gap"}
        )

def update_candle_data(symbol, timeframe, new_candles, warm_up_count=0):
    """
    캔들 데이터 업데이트

    Args:
        symbol: 심볼
        timeframe: 타임프레임
        new_candles: 새 캔들 리스트
        warm_up_count: 지표 계산용 warm-up 캔들 개수 (이 개수만큼은 저장하지 않음)
    """
    tf_str = TF_MAP.get(timeframe, "1m")
    key = f"candles:{symbol}:{tf_str}"

    try:
        # 기존 캔들 데이터 가져오기
        existing = redis_client.lrange(key, 0, -1)
        candle_map = {}

        # 기존 데이터 파싱
        for item in existing:
            # Redis returns bytes, decode to string first
            item_str = item.decode('utf-8') if isinstance(item, bytes) else item
            parts = item_str.split(",")
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

        # 정렬
        sorted_ts = sorted(candle_map.keys())

        # warm_up_count가 지정된 경우, 처음 해당 개수만큼 제외 (지표 계산용으로만 사용)
        if warm_up_count > 0 and len(sorted_ts) > warm_up_count:
            logger.info(f"Warm-up 데이터 제외: {symbol} {tf_str} - 처음 {warm_up_count}개 캔들은 지표 계산용으로만 사용")
            # 나중에 지표 계산 후 제외할 것이므로 여기서는 전체 유지

        # 최대 MAX_CANDLE_LEN개만 유지 (warm_up 제외하기 전)
        if len(sorted_ts) > MAX_CANDLE_LEN + warm_up_count:
            sorted_ts = sorted_ts[-(MAX_CANDLE_LEN + warm_up_count):]

        final_list = [",".join(candle_map[ts]) for ts in sorted_ts]

        # Redis에 저장
        pipe = redis_client.pipeline()
        pipe.delete(key)
        for row_str in final_list:
            pipe.rpush(key, row_str)
        pipe.execute()
        
        # 인디케이터 계산 및 저장
        # 병합 후 데이터가 부족하면 API에서 추가로 가져오기
        if len(sorted_ts) < MIN_CANDLES_FOR_INDICATORS:
            logger.info(f"병합 후 데이터 부족, API에서 추가 캔들 로드: {symbol} {tf_str} (현재: {len(sorted_ts)}개, 필요: {MIN_CANDLES_FOR_INDICATORS}개)")

            # API에서 충분한 캔들 가져오기
            api_candles = fetch_latest_candles(symbol, timeframe, limit=MIN_CANDLES_FOR_INDICATORS)

            if api_candles and len(api_candles) >= MIN_CANDLES_FOR_INDICATORS:
                # 새로 가져온 캔들 병합
                for candle in api_candles:
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

                # 다시 정렬
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

                logger.info(f"API에서 추가 캔들 로드 완료: {symbol} {tf_str} (총 {len(sorted_ts)}개)")
            else:
                logger.warning(f"API에서도 충분한 캔들을 가져올 수 없음: {symbol} {tf_str} (API: {len(api_candles) if api_candles else 0}개)")
                return

        # 이제 충분한 데이터가 있으므로 지표 계산
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

        # 인디케이터 계산 (전체 데이터로 계산)
        candles_with_ind = compute_all_indicators(candles, rsi_period=14, atr_period=14)

        # auto_trend_state 추가 (Pine Script '자동' 모드용)
        auto_trend_tf_str = get_auto_trend_timeframe(tf_str)
        auto_trend_candles = _get_candles_from_redis_for_auto_trend(symbol, auto_trend_tf_str)
        if auto_trend_candles and len(auto_trend_candles) >= 30:
            candles_with_ind = add_auto_trend_state_to_candles(
                candles_with_ind,
                auto_trend_candles,
                current_timeframe_minutes=timeframe
            )
            logger.debug(f"auto_trend_state 계산 완료: {symbol} {tf_str} (auto_trend_tf: {auto_trend_tf_str})")
        else:
            # auto_trend 캔들이 부족하면 0으로 설정
            for cndl in candles_with_ind:
                cndl["auto_trend_state"] = 0
            logger.debug(f"auto_trend 캔들 부족, auto_trend_state=0으로 설정: {symbol} {tf_str}")

        # warm_up_count가 지정된 경우, 처음 해당 개수만큼 제외
        if warm_up_count > 0 and len(candles_with_ind) > warm_up_count:
            logger.info(f"Warm-up 캔들 제외: {symbol} {tf_str} - 처음 {warm_up_count}개 제외, {len(candles_with_ind) - warm_up_count}개 저장")
            candles_with_ind = candles_with_ind[warm_up_count:]  # 처음 warm_up_count개 제외

        # 한국 시간 추가
        for cndl in candles_with_ind:
            utc_dt = datetime.fromtimestamp(cndl["timestamp"], UTC)
            seoul_tz = pytz.timezone("Asia/Seoul")
            dt_seoul = utc_dt.replace(tzinfo=pytz.utc).astimezone(seoul_tz)
            cndl["human_time"] = utc_dt.strftime("%Y-%m-%d %H:%M:%S")
            cndl["human_time_kr"] = dt_seoul.strftime("%Y-%m-%d %H:%M:%S")

        # 인디케이터 포함 캔들 저장
        save_candles_with_indicators(symbol, tf_str, candles_with_ind)

        logger.debug(f"캔들 데이터 업데이트 완료: {symbol} {tf_str} - 총 {len(candles_with_ind)}개 캔들 (warm-up {warm_up_count}개 제외)")
    
    except Exception as e:
        logger.error(f"캔들 데이터 업데이트 중 오류: {symbol} {tf_str} - {e}", exc_info=True)
        # errordb 로깅
        from HYPERRSI.src.utils.error_logger import log_error_to_db
        log_error_to_db(
            error=e,
            error_type="CandleDataUpdateError",
            severity="ERROR",
            symbol=symbol,
            metadata={"timeframe": tf_str, "component": "integrated_data_collector.update_candle_data"}
        )

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

        # 새 데이터 병합 (기존 데이터는 덮어쓰지 않음 - warm-up으로 계산된 정확한 데이터 보존)
        for cndl in candles_with_ind:
            ts = cndl["timestamp"]
            if ts not in candle_map:  # 새로운 timestamp만 추가
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

        # CandlesDB에도 저장 (비동기적으로, 실패해도 Redis는 영향 없음)
        if candlesdb_writer.enabled:
            try:
                # timeframe 변환 (tf_str: "1m", "15m", "1h" 등 → minutes)
                timeframe_minutes = REVERSE_TF_MAP.get(tf_str, 1)  # 기본값 1분

                # 새로 추가된 캔들만 CandlesDB에 저장
                new_candles = [candle_map[ts] for ts in sorted_ts]
                candlesdb_writer.upsert_candles(symbol, timeframe_minutes, new_candles)
            except Exception as db_e:
                logger.warning(f"CandlesDB 저장 실패 (Redis는 성공): {symbol} {tf_str} - {db_e}")

        ## 최신 캔들 따로 저장 #<-- 이건, 지표를 계산하니 필요할지 모르겠다. 그러나, 일단은, latest는 웹소켓에서만 다루는걸로.
        #latest_key = f"latest:{symbol}:{tf_str}"
        #latest_ts = sorted_ts[-1]
        #redis_client.set(latest_key, json.dumps(candle_map[latest_ts]))

    except Exception as e:
        logger.error(f"인디케이터 포함 캔들 저장 중 오류: {symbol} {tf_str} - {e}", exc_info=True)
        # errordb 로깅
        from HYPERRSI.src.utils.error_logger import log_error_to_db
        log_error_to_db(
            error=e,
            error_type="CandleIndicatorSaveError",
            severity="ERROR",
            symbol=symbol,
            metadata={"timeframe": tf_str, "component": "integrated_data_collector.save_candles_with_indicators"}
        )

def fetch_initial_data():
    """초기 데이터 로드"""
    logger.info("=== 초기 데이터 로드 시작 ===")

    # 1단계: 큰 타임프레임부터 로드 (auto_trend_state 계산을 위해)
    # 예: 5m은 30m의 auto_trend_state가 필요하므로, 30m을 먼저 로드
    sorted_timeframes = sorted(TIMEFRAMES, reverse=True)  # [240, 60, 30, 15, 5, 3, 1]

    for symbol in SYMBOLS:
        for timeframe in sorted_timeframes:
            tf_str = TF_MAP.get(timeframe, "1m")
            key = f"{symbol}:{tf_str}"

            logger.info(f"초기 데이터 로드: {key}")

            # 정확한 지표 계산을 위해 추가 200개를 더 요청 (warm-up 데이터)
            requested_candles = MAX_CANDLE_LEN + MIN_CANDLES_FOR_INDICATORS  # 3000 + 200 = 3200
            candles = fetch_latest_candles(symbol, timeframe, limit=requested_candles)

            if candles:
                # 지표 계산은 전체 데이터로, 저장은 최신 MAX_CANDLE_LEN개만
                update_candle_data(symbol, timeframe, candles, warm_up_count=MIN_CANDLES_FOR_INDICATORS)
                last_candle_timestamps[key] = candles[-1]["timestamp"]
                logger.info(f"초기 데이터 로드 성공: {key} - {len(candles)}개 캔들 (warm-up: {MIN_CANDLES_FOR_INDICATORS}개)")
            else:
                logger.warning(f"초기 데이터 로드 실패: {key}")

    # 2단계: auto_trend_state 재계산 (이제 모든 타임프레임 데이터가 Redis에 있음)
    logger.info("=== auto_trend_state 재계산 시작 ===")
    for symbol in SYMBOLS:
        for timeframe in TIMEFRAMES:
            tf_str = TF_MAP.get(timeframe, "1m")
            key = f"{symbol}:{tf_str}"

            # 현재 캔들 데이터 가져오기
            candles_key = f"candles_with_indicators:{symbol}:{tf_str}"
            existing_list = redis_client.lrange(candles_key, 0, -1)

            if not existing_list:
                continue

            # 캔들 파싱
            candles = []
            for item in existing_list:
                try:
                    item_str = item.decode('utf-8') if isinstance(item, bytes) else item
                    obj = json.loads(item_str)
                    candles.append(obj)
                except Exception:
                    pass

            if not candles:
                continue

            # auto_trend_state 계산
            auto_trend_tf_str = get_auto_trend_timeframe(tf_str)
            auto_trend_candles = _get_candles_from_redis_for_auto_trend(symbol, auto_trend_tf_str)

            if auto_trend_candles and len(auto_trend_candles) >= 30:
                candles = add_auto_trend_state_to_candles(
                    candles,
                    auto_trend_candles,
                    current_timeframe_minutes=timeframe
                )
                logger.info(f"auto_trend_state 재계산 완료: {key} (auto_trend_tf: {auto_trend_tf_str})")

                # Redis에 업데이트
                with redis_client.pipeline() as pipe:
                    pipe.delete(candles_key)
                    for cndl in candles:
                        pipe.rpush(candles_key, json.dumps(cndl))
                    pipe.execute()

                # CandlesDB에도 업데이트
                if candlesdb_writer.enabled:
                    try:
                        candlesdb_writer.upsert_candles(symbol, timeframe, candles)
                    except Exception as db_e:
                        logger.warning(f"CandlesDB auto_trend_state 업데이트 실패: {key} - {db_e}")
            else:
                logger.warning(f"auto_trend 캔들 부족, 재계산 불가: {key} (필요: {auto_trend_tf_str})")

    logger.info("=== auto_trend_state 재계산 완료 ===")

    # 초기 로드 완료 플래그 설정
    initial_data_loaded.set()
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
        # errordb 로깅
        from HYPERRSI.src.utils.error_logger import log_error_to_db
        log_error_to_db(
            error=e,
            error_type="CurrentCandleUpdateError",
            severity="WARNING",
            symbol=symbol,
            metadata={"timeframe": tf_str, "component": "integrated_data_collector.update_current_candle"}
        )

def update_current_candle_with_indicators(symbol, timeframe, current_candle):
    """현재 진행 중인 캔들에 인디케이터 계산하여 업데이트"""
    tf_str = TF_MAP.get(timeframe, "1m")
    key = f"candles_with_indicators:{symbol}:{tf_str}"

    try:
        # 기존 캔들 데이터 가져오기
        candle_key = f"candles:{symbol}:{tf_str}"
        existing_data = redis_client.lrange(candle_key, 0, -1)
        existing_count = len(existing_data) if existing_data else 0

        # Redis에 데이터가 부족하면 API에서 추가로 가져오기
        if existing_count < MIN_CANDLES_FOR_INDICATORS:
            logger.info(f"Redis 데이터 부족, API에서 추가 캔들 로드: {symbol} {tf_str} (현재: {existing_count}개, 목표: {MIN_CANDLES_FOR_INDICATORS}개)")

            # API에서 충분한 캔들 가져오기
            api_candles = fetch_latest_candles(symbol, timeframe, limit=MIN_CANDLES_FOR_INDICATORS)

            if not api_candles or len(api_candles) < MIN_CANDLES_FOR_INDICATORS:
                logger.warning(f"API에서도 충분한 캔들을 가져올 수 없음: {symbol} {tf_str} (API: {len(api_candles) if api_candles else 0}개)")
                return

            # API에서 가져온 데이터를 Redis에 저장 (지표는 나중에 계산)
            update_candle_data(symbol, timeframe, api_candles)

            # Redis에서 다시 가져오기
            existing_data = redis_client.lrange(candle_key, 0, -1)
            existing_count = len(existing_data) if existing_data else 0

            if existing_count < MIN_CANDLES_FOR_INDICATORS:
                logger.warning(f"Redis 업데이트 후에도 데이터 부족: {symbol} {tf_str} (현재: {existing_count}개)")
                return

            logger.info(f"API에서 캔들 로드 완료: {symbol} {tf_str} ({existing_count}개)")
        
        # 캔들 객체 리스트 생성
        candles = []
        for item in existing_data:
            # Redis returns bytes, decode to string first
            item_str = item.decode('utf-8') if isinstance(item, bytes) else item
            parts = item_str.split(",")
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

        # auto_trend_state 추가 (Pine Script '자동' 모드용)
        auto_trend_tf_str = get_auto_trend_timeframe(tf_str)
        auto_trend_candles = _get_candles_from_redis_for_auto_trend(symbol, auto_trend_tf_str)
        if auto_trend_candles and len(auto_trend_candles) >= 30:
            candles_with_ind = add_auto_trend_state_to_candles(
                candles_with_ind,
                auto_trend_candles,
                current_timeframe_minutes=timeframe
            )
        else:
            # auto_trend 캔들이 부족하면 0으로 설정
            for cndl in candles_with_ind:
                cndl["auto_trend_state"] = 0

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

            # CandlesDB에도 현재 캔들 업데이트 (실시간 upsert)
            if candlesdb_writer.enabled:
                try:
                    timeframe_minutes = REVERSE_TF_MAP.get(tf_str, 1)
                    candlesdb_writer.upsert_single_candle(symbol, timeframe_minutes, current_with_ind)
                except Exception as db_e:
                    logger.debug(f"CandlesDB 현재 캔들 업데이트 실패: {symbol} {tf_str} - {db_e}")

            logger.debug(f"현재 진행 캔들 인디케이터 업데이트 완료: {symbol} {tf_str}")
        else:
            logger.warning(f"현재 캔들의 인디케이터 계산 결과를 찾을 수 없음: {symbol} {tf_str}")
    
    except Exception as e:
        logger.error(f"현재 캔들 인디케이터 업데이트 중 오류: {symbol} {tf_str} - {e}", exc_info=True)
        # errordb 로깅
        from HYPERRSI.src.utils.error_logger import log_error_to_db
        log_error_to_db(
            error=e,
            error_type="CurrentCandleIndicatorUpdateError",
            severity="WARNING",
            symbol=symbol,
            metadata={"timeframe": tf_str, "component": "integrated_data_collector.update_current_candle_with_indicators"}
        )


def polling_worker():
    """폴링 워커 함수"""
    logger.info("폴링 워커 시작")

    try:
        # 초기 데이터 로드 완료 대기
        logger.info("초기 데이터 로드 완료 대기 중...")
        initial_data_loaded.wait()
        logger.info("초기 데이터 로드 완료 확인, 폴링 시작")

        # 초기화
        for symbol in SYMBOLS:
            for timeframe in TIMEFRAMES:
                tf_str = TF_MAP.get(timeframe, "1m")
                key = f"{symbol}:{tf_str}"
                last_check_times[key] = 0

        # Health Check 타이머
        last_health_check = time.time()
        health_check_interval = 300  # 5분마다 health check
        stats_log_interval = 600  # 10분마다 통계 로그

        # Redis 모니터링 카운터
        redis_success_count = 0
        redis_failure_count = 0
        redis_last_failure_time = None

        while not shutdown_event.is_set():
            current_time = time.time()

            # Health Check (5분마다)
            if current_time - last_health_check >= health_check_interval:
                # CandlesDB Health Check
                logger.debug("🏥 CandlesDB health check 실행...")
                candlesdb_writer.health_check()

                # Redis Health Check
                logger.debug("🏥 Redis health check 실행...")
                try:
                    if redis_manager.ping_sync():
                        redis_success_count += 1
                        logger.debug("✅ Redis health check: OK")
                    else:
                        redis_failure_count += 1
                        redis_last_failure_time = current_time
                        logger.warning("⚠️ Redis health check failed: ping returned False")
                        # 재연결 시도
                        logger.info("🔄 Redis 재연결 시도...")
                        global redis_client
                        redis_client = redis_manager.get_connection()
                except Exception as e:
                    redis_failure_count += 1
                    redis_last_failure_time = current_time
                    logger.error(f"❌ Redis health check failed: {e}")
                    # 재연결 시도
                    try:
                        logger.info("🔄 Redis 재연결 시도...")
                        redis_client = redis_manager.get_connection()
                        if redis_manager.ping_sync():
                            logger.info("✅ Redis 재연결 성공!")
                    except Exception as reconnect_e:
                        logger.error(f"❌ Redis 재연결 실패: {reconnect_e}")

                last_health_check = current_time

                # 통계 로그 (10분마다)
                if current_time % stats_log_interval < health_check_interval:
                    candlesdb_writer.log_stats()

                    # Redis 통계 로그
                    total_checks = redis_success_count + redis_failure_count
                    success_rate = (redis_success_count / total_checks * 100) if total_checks > 0 else 0.0
                    logger.info(
                        f"📊 Redis Stats: "
                        f"success={redis_success_count}, "
                        f"failure={redis_failure_count}, "
                        f"rate={success_rate:.1f}%"
                    )
            
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
                            logger.debug(f"바 종료 감지: {key} - 데이터 폴링 시작")
                            
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
        # errordb 로깅
        from HYPERRSI.src.utils.error_logger import log_error_to_db
        log_error_to_db(
            error=e,
            error_type="PollingWorkerError",
            severity="CRITICAL",
            metadata={"component": "integrated_data_collector.polling_worker"}
        )
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