#!/usr/bin/env python3
"""
불일치 캔들 상세 디버깅 스크립트

특정 캔들의 모든 중간 계산값을 CSV와 비교하여 차이점을 찾습니다.
"""

import json
import pandas as pd
import redis
from datetime import datetime, timezone
from shared.config import get_settings
from shared.indicators._trend import compute_trend_state


settings = get_settings()


def load_csv_data(csv_path):
    """CSV 데이터 로드"""
    df = pd.read_csv(csv_path)
    df['timestamp'] = pd.to_datetime(df['time'])
    df['timestamp_utc'] = df['timestamp'].dt.tz_convert('UTC')
    df['timestamp_unix'] = df['timestamp_utc'].astype('int64') // 10**9
    return df


def load_redis_data(redis_key):
    """Redis 데이터 로드"""
    r = redis.Redis(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        db=0,
        decode_responses=True
    )
    data_list = r.lrange(redis_key, 0, -1)
    candles = [json.loads(item) for item in data_list]
    return candles


def prepare_candles(redis_candles):
    """compute_trend_state용 캔들 준비"""
    prepared = []
    for c in redis_candles:
        prepared.append({
            "timestamp": datetime.fromtimestamp(c["timestamp"]),
            "open": float(c["open"]),
            "high": float(c["high"]),
            "low": float(c["low"]),
            "close": float(c["close"]),
            "volume": float(c.get("volume", 0))
        })
    return prepared


def find_mismatch_index(csv_df, redis_candles, target_timestamp):
    """특정 타임스탬프의 인덱스 찾기"""
    # CSV 인덱스
    csv_idx = None
    for idx, row in csv_df.iterrows():
        if row['timestamp_unix'] == target_timestamp:
            csv_idx = idx
            break

    # Redis 인덱스
    redis_idx = None
    for idx, candle in enumerate(redis_candles):
        if candle['timestamp'] == target_timestamp:
            redis_idx = idx
            break

    return csv_idx, redis_idx


def debug_specific_candle(csv_df, redis_candles, target_timestamp):
    """특정 캔들의 상세 디버깅"""
    csv_idx, redis_idx = find_mismatch_index(csv_df, redis_candles, target_timestamp)

    if csv_idx is None or redis_idx is None:
        print(f"❌ 타임스탬프 {target_timestamp} 찾을 수 없음")
        return

    print("\n" + "="*80)
    print(f"🔍 상세 디버깅: {datetime.fromtimestamp(target_timestamp, tz=timezone.utc)}")
    print("="*80)

    # CSV 데이터
    csv_row = csv_df.iloc[csv_idx]
    print(f"\n📊 CSV 데이터:")
    print(f"  BB_State: {csv_row['BB_State']}")
    print(f"  trend_state: {csv_row['trend_state']}")
    print(f"  BBW: {csv_row['BBW']}")
    print(f"  BBR: {csv_row['BBR']}")
    print(f"  RSI: {csv_row['rsi']}")

    # Redis 데이터
    redis_candle = redis_candles[redis_idx]
    print(f"\n📊 Redis 데이터:")
    print(f"  BB_State: {redis_candle['BB_State']}")
    print(f"  trend_state: {redis_candle['trend_state']}")
    print(f"  CYCLE_Bull: {redis_candle.get('CYCLE_Bull', 'N/A')}")
    print(f"  CYCLE_Bear: {redis_candle.get('CYCLE_Bear', 'N/A')}")

    # 주변 캔들도 확인 (컨텍스트)
    print(f"\n📈 주변 캔들 (±5):")
    print(f"{'Index':<8} {'CSV BB':<10} {'Redis BB':<10} {'CSV trend':<12} {'Redis trend':<12}")
    print("-" * 80)

    for offset in range(-5, 6):
        csv_i = csv_idx + offset
        redis_i = redis_idx + offset

        if 0 <= csv_i < len(csv_df) and 0 <= redis_i < len(redis_candles):
            csv_r = csv_df.iloc[csv_i]
            redis_c = redis_candles[redis_i]

            marker = ">>>" if offset == 0 else "   "

            print(f"{marker} {redis_i:<5} {csv_r['BB_State']:<10} {redis_c['BB_State']:<10} "
                  f"{csv_r['trend_state']:<12} {redis_c['trend_state']:<12}")


def analyze_bb_state_mismatches(csv_df, redis_candles):
    """BB_State 불일치 패턴 분석"""
    print("\n" + "="*80)
    print("🔍 BB_State 불일치 패턴 분석")
    print("="*80)

    mismatches = []

    for idx, candle in enumerate(redis_candles):
        ts = candle['timestamp']

        # CSV에서 해당 timestamp 찾기
        csv_rows = csv_df[csv_df['timestamp_unix'] == ts]
        if csv_rows.empty:
            continue

        csv_row = csv_rows.iloc[0]

        if csv_row['BB_State'] != candle['BB_State']:
            mismatches.append({
                'timestamp': ts,
                'csv_bb': csv_row['BB_State'],
                'redis_bb': candle['BB_State'],
                'csv_bbw': csv_row['BBW'],
                'csv_bbr': csv_row['BBR']
            })

    # 패턴 분석
    pattern_counts = {}
    for m in mismatches:
        pattern = f"CSV={m['csv_bb']}, Redis={m['redis_bb']}"
        pattern_counts[pattern] = pattern_counts.get(pattern, 0) + 1

    print("\n📊 불일치 패턴 분포:")
    for pattern, count in sorted(pattern_counts.items(), key=lambda x: x[1], reverse=True):
        print(f"  {pattern}: {count}개")

    # 처음 3개 상세 분석
    print("\n🔍 처음 3개 불일치 상세:")
    for i, m in enumerate(mismatches[:3]):
        ts_str = datetime.fromtimestamp(m['timestamp'], tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
        print(f"\n  [{i+1}] {ts_str}")
        print(f"      CSV BB_State={m['csv_bb']}, BBW={m['csv_bbw']}, BBR={m['csv_bbr']}")
        print(f"      Redis BB_State={m['redis_bb']}")


def main():
    csv_path = "/Users/seunghyun/Downloads/OKX_BTCUSDT.P, 15_ba3e6.csv"
    redis_key = "candles_with_indicators:BTC-USDT-SWAP:15m"

    print("🔍 불일치 캔들 상세 디버깅")
    print("="*80)

    # 데이터 로드
    csv_df = load_csv_data(csv_path)
    redis_candles = load_redis_data(redis_key)

    print(f"✅ CSV: {len(csv_df)}행, Redis: {len(redis_candles)}개 로드")

    # BB_State 불일치 패턴 분석
    analyze_bb_state_mismatches(csv_df, redis_candles)

    # 첫 번째 불일치 캔들 상세 디버깅
    # 2025-11-01 03:15:00 UTC = 1730433300
    target_ts = 1730433300
    debug_specific_candle(csv_df, redis_candles, target_ts)

    # 두 번째 불일치 캔들
    # 2025-11-01 05:45:00 UTC = 1730442300
    target_ts2 = 1730442300
    debug_specific_candle(csv_df, redis_candles, target_ts2)


if __name__ == "__main__":
    main()
