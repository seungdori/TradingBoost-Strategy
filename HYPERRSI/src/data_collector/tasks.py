# src/data_collector/tasks.py
import json
import os
import time
from datetime import UTC, datetime

import ccxt
import pytz
import redis
from celery import Celery

from HYPERRSI.src.config import get_settings
from HYPERRSI.src.core.config import settings
from HYPERRSI.src.trading.models import get_timeframe

# shared indicators에서 가져옴
from shared.indicators import compute_all_indicators
from shared.logging import get_logger

################################################################################
# 5) Celery Beat 스케줄 설정:
#    - 1초마다 check_and_fetch_candles() 실행
#    - (물론 실제 운영에선 1~2초 주기, 혹은 5초 주기로 해도 됩니다.)
#
#      celery -A src.data_collector.tasks beat -l warning
#  (터미널1. 스케쥴러)
#      celery -A src.data_collector.tasks worker -l info
#      (터미널2. 작업자)
################################################################################
###############################################################################
# 1) OKX + CCXT 설정 (API 키, etc.)
###############################################################################
logger = get_logger(__name__)

# OKX API 자격 증명
OKX_API_KEY = settings.OKX_API_KEY
OKX_SECRET = settings.OKX_SECRET_KEY
OKX_PASSPHRASE = settings.OKX_PASSPHRASE

# API 키 로깅 시 개인 정보 보호
logger.info(f"OKX API KEY: {OKX_API_KEY[:5]}...{OKX_API_KEY[-5:] if len(OKX_API_KEY) > 10 else ''}")
logger.info(f"OKX SECRET KEY: {OKX_SECRET[:5]}...{OKX_SECRET[-5:] if len(OKX_SECRET) > 10 else ''}")
logger.info(f"OKX PASSPHRASE: {'*' * min(len(OKX_PASSPHRASE), 10)}")

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

###############################################################################
# 2) Celery & Redis 설정
###############################################################################

    
BROKER_DB = 1
BACKEND_DB = 2
REDIS_PASSWORD = settings.REDIS_PASSWORD
REDIS_HOST = settings.REDIS_HOST
REDIS_PORT = settings.REDIS_PORT

if REDIS_PASSWORD:
    celery_app = Celery(
        "candle_fetcher",
        broker=f"redis://:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}/{BROKER_DB}",
        backend=f"redis://:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}/{BACKEND_DB}",
    )
else:
    celery_app = Celery(
        "candle_fetcher",
        broker=f"redis://{REDIS_HOST}:{REDIS_PORT}/{BROKER_DB}",
        backend=f"redis://{REDIS_HOST}:{REDIS_PORT}/{BACKEND_DB}",
    )

celery_app.conf.timezone = "UTC"
celery_app.conf.enable_utc = True
celery_app.conf.beat_schedule = {
    'fetch-candles-every-60s': {
        'task': 'src.data_collector.tasks.fetch_all_candles',
        'schedule': 60.0,
    }
}

celery_app.conf.broker_connection_retry_on_startup = True
if settings.REDIS_PASSWORD:
    redis_client = redis.Redis(host=settings.REDIS_HOST, port=settings.REDIS_PORT, db=0, decode_responses=True, password=settings.REDIS_PASSWORD)
else:
    redis_client = redis.Redis(host=settings.REDIS_HOST, port=settings.REDIS_PORT, db=0, decode_responses=True)
################################################################################
# 2) '마감 후 2~3초'인지 판단하는 함수
################################################################################
def is_time_to_update(now: datetime, timeframe: int, offset=2, window=3) -> bool:
    """
    - now: 현재 UTC 시각(또는 로컬 시각) 
    - timeframe: 분 단위 (1, 3, 5, 15, ...)
    - offset=2, window=3 => '마감 시점(초=0)으로부터 2~4초 지난 구간'이면 True
    - 로직:
      1) 총 분 = now.hour*60 + now.minute
      2) (총 분 % timeframe == 0) 이어야 '막 캔들이 마감된 시점' 
      3) now.second 가 offset <= second < offset+window 범위인지 확인
    """
    total_minutes = now.hour * 60 + now.minute
    if (total_minutes % timeframe) != 0:
        return False
    if offset <= now.second < (offset + window):
        return True
    return False
###############################################################################
# 3) 사용자 설정: 심볼, 타임프레임, 최대 캔들 수
###############################################################################
#SYMBOLS = ["BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP"]   # 선물 마켓용 심볼
SYMBOLS = ["BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP"]   # 선물 마켓용 심볼

TIMEFRAMES = [1, 3, 5, 15, 30, 60, 240]   # (분 단위)
MAX_CANDLE_LEN = 3000

TF_MAP = {1:'1m', 3:'3m', 5:'5m', 15:'15m', 30:'30m', 60:'1h', 240:'4h'}
################################################################################
# 3) 특정 타임프레임(tf)에 대해 캔들 가져오기 + Redis 저장 + 지표 계산
################################################################################
def fetch_candles_for_tf(symbol: str, tf: int) -> None:
    """
    - 본문에는 기존에 작성한 get_exchange_candles_full(), save_candles_to_redis() 등
      로직을 그대로 재사용
    """
    # 최대 3000개 가져오기
    candles = get_exchange_candles_full(symbol, tf, desired_count=3000)
    save_candles_to_redis(symbol, tf, candles)

    # 인디케이터 계산
    candles_with_ind = compute_all_indicators(candles, rsi_period=14, atr_period=14)
    save_candles_with_indicators_to_redis(symbol, tf, candles_with_ind)
    
################################################################################
# 4) 메인 태스크 (매초 실행) :
#    "각 타임프레임에 대해, 지금이 마감 후 2~4초 구간이면 fetch + indicator"
################################################################################
@celery_app.task
def check_and_fetch_candles():
    now = datetime.now(UTC)
    
    # 각 타임프레임 확인
    for tf in TIMEFRAMES:
        if is_time_to_update(now, tf, offset=2, window=3):
            # 해당 타임프레임의 캔들을 업데이트
            for symbol in SYMBOLS:
                lock_key = f"lock:{symbol}:{tf}"  # 예: loc
                lock = redis_client.lock(lock_key, timeout=30, blocking_timeout=5)
                if lock.acquire(blocking=True):
                    try:
                        # 실제 캔들 Fetch + 저장 + 인디케이터 계산
                        fetch_candles_for_tf(symbol, tf)
                    finally:
                        lock.release()
                else:
                    # 5초 안에 획득 실패하면, 이미 다른 워커가 가져갔다는 뜻이므로 skip
                    logger.info(f"Lock acquire failed. skip {symbol} {tf}")

    
    return True
###############################################################################
# 4) 여러 번 fetch_ohlcv 호출로 최대 3,000개 누적
###############################################################################

def align_timestamp(ts_ms: int, timeframe: int) -> int:
    """
    타임스탬프를 캔들 마감시간에 맞춰 정렬
    예: 
    - 1분봉: 매 분 00초
    - 5분봉: 00:00:00, 00:05:00, 00:10:00...
    """
    minutes = timeframe
    ms_per_minute = 60 * 1000
    return (ts_ms // (minutes * ms_per_minute)) * (minutes * ms_per_minute)

def get_latest_candle(symbol: str, timeframe: int) -> dict:
    """현재 진행 중인 캔들 정보를 가져오는 함수"""
    tf_str = get_timeframe(timeframe)
    params = {'instType': 'SWAP'}
    current_time_kr = datetime.now(pytz.timezone("Asia/Seoul")).strftime("%Y-%m-%d %H:%M:%S")
    try:
        # 가장 최근 캔들 1개만 요청
        latest = exchange.fetch_ohlcv(
            symbol,
            timeframe=tf_str,
            limit=1,
            params=params
        )
        
        if latest:
            ts, o, h, l, c, v = latest[0]
            return {
                "timestamp": ts // 1000,
                "open": float(o),
                "high": float(h),
                "low": float(l),
                "close": float(c),
                "volume": float(v),
                "is_completed": False,
                "current_time_kr": current_time_kr
            }
    except Exception as e:
        print(f"Error fetching latest candle: {e}")
    
    return None

def get_exchange_candles_full(symbol: str, timeframe: int, desired_count: int = 3000) -> list:
    tf_str = get_timeframe(timeframe)
    key = f"candles:{symbol}:{tf_str}"
    params = {
        'instType': 'SWAP',  # SWAP은 영구선물을 의미
    }
    # 1. 현재 시간을 캔들 마감시간에 맞춤
    now_ms = align_timestamp(exchange.milliseconds(), timeframe)
    current_ts = now_ms // 1000
    ms_per_tf = timeframe * 60 * 1000
    
    # 1. 기존 Redis 데이터 확인
    existing_candles = redis_client.lrange(key, 0, -1)
    existing_map = {}
    current_time_kr = datetime.now(pytz.timezone("Asia/Seoul")).strftime("%Y-%m-%d %H:%M:%S")
    if existing_candles:
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
                "volume": float(v),
                "current_time_kr": current_time_kr
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
        
        # 기존 데이터 내의 갭들 확인 (이미 정렬된 시간 사용)
        current_check_ts = first_ts
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
            current_check_ts = next_expected_ts
    else:
        start_ms = now_ms - (ms_per_tf * desired_count)
        gaps.append({
            'start': align_timestamp(start_ms, timeframe),
            'end': now_ms
        })
    
    # 갭 채우기
    fetch_limit = 100
    for gap in gaps:
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
                        # 디버깅용 API 호출 정보 출력
                        print(f"[DEBUG] API 호출: {symbol} {tf_str} - since {aligned_start}, end {aligned_end}")
                        
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
                            print(f"[ERROR] Max retries reached for rate limit on {symbol} ({tf_str}). Error: {e}")
                            raise e
                        wait_time = 2 ** attempt  # 지수 백오프: 2, 4, 8, 16, 32 초
                        print(f"[WARNING] Rate limit exceeded for {symbol} ({tf_str}). Waiting {wait_time} seconds before retrying... (Attempt {attempt}/{max_retries})")
                        time.sleep(wait_time)
                    except Exception as e:
                        print(f"[ERROR] Error fetching gap data for {symbol} ({tf_str}): {e}")
                        # 다른 예외의 경우 해당 구간은 건너뛰기
                        ohlcvs = []
                        break

                
                print(f"[DEBUG] {symbol} Fetched {len(ohlcvs)} candles for {tf_str} gap: {datetime.fromtimestamp(aligned_start/1000)} to {datetime.fromtimestamp(aligned_end/1000)}")
                
                for row in ohlcvs:
                    # None 값 체크
                    if row is None or len(row) < 6:
                        print(f"[WARNING] 잘못된 캔들 데이터 (None 또는 불완전): {symbol} {tf_str}")
                        continue
                        
                    try:
                        ts, o, h, l, c, v = row
                        
                        # None 값 체크
                        if ts is None or o is None or h is None or l is None or c is None or v is None:
                            print(f"[WARNING] 캔들 데이터에 None 값 포함: {symbol} {tf_str} - {row}")
                            continue
                            
                        aligned_ts = align_timestamp(ts, timeframe) // 1000
                        existing_map[aligned_ts] = {
                            "timestamp": aligned_ts,
                            "open": float(o),
                            "high": float(h),
                            "low": float(l),
                            "close": float(c),
                            "volume": float(v)
                        }
                    except (TypeError, ValueError) as e:
                        print(f"[WARNING] 캔들 데이터 변환 오류: {symbol} {tf_str} - {row} - {e}")
                        continue
                time.sleep(0.02)
                current_end = aligned_start
                
            except Exception as e:
                print(f"Error fetching gap data: {e}")
                break

    # 결과 정렬 및 반환
    sorted_ts = sorted(existing_map.keys())
    if len(sorted_ts) > desired_count:
        sorted_ts = sorted_ts[-desired_count:]
    
    results = [existing_map[ts] for ts in sorted_ts]
    return results
###############################################################################
# 5) Redis에 저장 (중복 timestamp는 덮어쓰기)
###############################################################################
def save_candles_to_redis(symbol: str, timeframe: int, new_candles: list) -> None:
    """
    - new_candles: [{timestamp, open, high, low, close, volume}, ...] (과거->현재)
    - 키: "candles:{symbol}:{tf}"
    - 1) Redis에서 기존 데이터 전부 가져옴
    - 2) {ts: [ts, open, high, ...]} dict로 변환해 중복 덮어쓰기
    - 3) timestamp 정렬 → rpush
    - 4) ltrim으로 3000개 유지
    """
    tf_str = get_timeframe(timeframe)
    key = f"candles:{symbol}:{tf_str}"
    existing = redis_client.lrange(key, 0, -1)
    candle_map = {}

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

    pipe = redis_client.pipeline()
    pipe.delete(key)
    for row_str in final_list:
        pipe.rpush(key, row_str)
    pipe.ltrim(key, -MAX_CANDLE_LEN, -1)
    pipe.execute()

################################################################################
# (B) Raw 캔들에 인디케이터를 합쳐서, 별도 key에 저장
################################################################################
def save_candles_with_indicators_to_redis(symbol: str, timeframe: int, candles_with_ind: list) -> None:
    """
    key = "candles_with_indicators:{symbol}:{tf}"
    'timestamp'가 동일하면 덮어쓰기
    """
    tf_str = get_timeframe(timeframe)
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

    pipe = redis_client.pipeline()
    pipe.delete(key)
    for ts in sorted_ts:
        row_json = json.dumps(candle_map[ts])
        pipe.rpush(key, row_json)
    pipe.execute()

###############################################################################
# 6) Celery 태스크: 최대 3000개까지 가져와 Redis에 저장
###############################################################################
@celery_app.task(ignore_result=True)
def fetch_all_candles():
    lock_key = "lock:fetch_all_candles"
    lock = redis_client.lock(lock_key, timeout=45)  # 60초 주기보다 약간 짧게 설정
    
    if not lock.acquire(blocking=False):
        logger.info("Another fetch_all_candles task is running")
        return
        
    start_ts = time.time()
    try:
        for symbol in SYMBOLS:
            for tf in TIMEFRAMES:
                candles = get_exchange_candles_full(symbol, tf, desired_count=3000)
                save_candles_to_redis(symbol, tf, candles)
                
                candles_with_ind = compute_all_indicators(candles, rsi_period=14, atr_period=14)
                for cndl in candles_with_ind:
                    utc_dt = datetime.utcfromtimestamp(cndl["timestamp"])
                    cndl["human_time"] = utc_dt.strftime("%Y-%m-%d %H:%M:%S")
                    
                    seoul_tz = pytz.timezone("Asia/Seoul")
                    dt_seoul = utc_dt.replace(tzinfo=pytz.utc).astimezone(seoul_tz)
                    cndl["human_time_kr"] = dt_seoul.strftime("%Y-%m-%d %H:%M:%S")

                save_candles_with_indicators_to_redis(symbol, tf, candles_with_ind)

        execution_time = time.time() - start_ts
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


@celery_app.task
def update_symbol_latest_candle(symbol):
    try:
        for tf in TIMEFRAMES:
            key = f"candles_with_indicators:{symbol}:{tf}"

            # 1. Redis에서 최근 200개(혹은 필요한 만큼) 불러오기
            old_data = redis_client.lrange(key, -200, -1)
            latest_candles = [json.loads(c) for c in old_data]
            old_len = len(latest_candles)

            if not latest_candles:
                continue

            # 2. 현재 진행 중인 캔들 가져오기
            latest = get_latest_candle(symbol, tf)
            if not latest:
                continue
            
            # 3. 마지막 캔들과 timestamp 비교 후 append or update
            if latest_candles[-1]["timestamp"] == latest["timestamp"]:
                # 기존 마지막 캔들을 덮어쓴다
                latest_candles[-1] = latest
            else:
                # 새로운 캔들이므로 append
                latest_candles.append(latest)

            # 4. 지표 계산
            updated_candles = compute_all_indicators(latest_candles, rsi_period=14, atr_period=14)
            
            # 5. Redis 저장
            pipe = redis_client.pipeline()
            new_len = len(updated_candles)

            # (a) 만약 기존 배열 대비 길이가 같으면 마지막 캔들만 갱신(lset)
            #     길이가 길어졌다면, = (새 캔들 추가), 그 새 캔들을 rpush.
            if new_len == old_len:
                # 기존 마지막 인덱스를 덮어쓰기
                pipe.lset(key, -1, json.dumps(updated_candles[-1]))
            else:
                # 새 캔들이 1개 이상 추가되었으니 rpush
                # (혹은 중간에 여러 개 캔들이 벌어져 있을 수도 있으니 반복문으로 추가 가능)
                for i in range(old_len, new_len):
                    pipe.rpush(key, json.dumps(updated_candles[i]))
                pipe.ltrim(key, -MAX_CANDLE_LEN, -1)

            pipe.execute()

        return True
        
    except Exception as e:
        logger.error(f"Error updating {symbol}: {str(e)}")
        return False

################################################################################
# 4) 메인 태스크 (매초 실행) :
#    "각 타임프레임에 대해, 지금이 마감 후 2~4초 구간이면 fetch + indicator"
################################################################################

################################################################################
# 5) Celery Beat 스케줄 설정:
#    - 1초마다 check_and_fetch_candles() 실행
#    - (물론 실제 운영에선 1~2초 주기, 혹은 5초 주기로 해도 됩니다.)
#
#      celery -A src.data_collector.tasks beat -l warning
#  (터미널1. 스케쥴러)
#      celery -A src.data_collector.tasks worker -l info
#      (터미널2. 작업자)
################################################################################
@celery_app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    """
    여기서 60초마다 fetch_all_candles를 스케줄링
    Celery Beat 사용 시:
      celery -A src.data_collector.tasks beat -l warning
  (터미널1. 스케쥴러)
      celery -A src.data_collector.tasks worker -l info
      (터미널2. 작업자)
    """
    #fetch_all_candles.delay()
    # 60초마다 전체 데이터 업데이트
    """Celery Beat 설정 완료 로그"""
    logger.info("=== Setup periodic tasks completed ===")
    
    
###############################################################################
# 7) 테스트 (__main__)
###############################################################################
if __name__ == "__main__":
    """
    python tasks.py 로 직접 실행 시:
      - BTC-USDT, ETH-USDT의 [1,3,5,15,30,60] 분봉 각각 최대 3000개를 가져와 Redis에 저장
      - 완료 후, BTC-USDT 1분봉의 총 길이와 일부 데이터를 출력
    """
    print("=== Test fetch_all_candles (desired 3000 bars) ===")
    fetch_all_candles()  # 동기로 한 번 실행
    print("=== Done ===")

    # Redis 결과 확인
    test_key = f"candles:BTC-USDT:1m"
    length = redis_client.llen(test_key)
    print(f"\n[Check Redis] key='{test_key}' length={length}")

    if length > 0:
        oldest = redis_client.lindex(test_key, 0)     # 가장 오래된
        newest = redis_client.lindex(test_key, -1)    # 가장 최근
        print("  Oldest:", oldest)
        print("  Newest:", newest)


#==============================================================================

# 미완성 캔들을 포함하여 데이터 가져오기
#all_candles = get_all_candles("BTC-USDT-SWAP", 5, include_latest=True)

# 완성된 캔들만 사용하고 싶을 때
#completed_candles = [c for c in all_candles if c["is_completed"]]

# 미완성 캔들 확인
#latest_candle = next((c for c in all_candles if not c["is_completed"]), None)

#==============================================================================