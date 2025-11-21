#!/usr/bin/env python3
"""
Redis 데이터로 계산한 BBW와 CSV의 BBW 비교
"""

import redis
import json
import pandas as pd
import math
from datetime import datetime
from shared.config import get_settings
from shared.indicators._moving_averages import calc_sma
from shared.indicators._bollinger import calc_stddev


def main():
    # 1. CSV 로드
    csv_path = "/Users/seunghyun/Downloads/OKX_BTCUSDT.P, 15_ba3e6.csv"
    pine_df = pd.read_csv(csv_path)
    pine_df['datetime'] = pd.to_datetime(pine_df['time'], utc=True)

    # 2. Redis 데이터 로드
    settings = get_settings()
    r = redis.Redis(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        db=0,
        decode_responses=True
    )

    redis_key = "candles_with_indicators:BTC-USDT-SWAP:15m"
    data_list = r.lrange(redis_key, 0, -1)
    redis_candles = [json.loads(item) for item in data_list]

    # 캔들 변환
    all_candles = []
    for c in redis_candles:
        all_candles.append({
            "timestamp": datetime.fromtimestamp(c["timestamp"]),
            "open": float(c["open"]),
            "high": float(c["high"]),
            "low": float(c["low"]),
            "close": float(c["close"]),
            "volume": float(c.get("volume", 0))
        })

    # 3. BBW 계산
    closes = [c["close"] for c in all_candles]
    length_bb = 15
    mult_bb = 1.5

    basis_list = calc_sma(closes, length_bb)
    std_list = calc_stddev(closes, length_bb)
    bbw_list = []

    for i in range(len(closes)):
        basis_val = basis_list[i]
        std_val = std_list[i]
        if basis_val is None or std_val is None or math.isnan(basis_val) or math.isnan(std_val):
            bbw_list.append(math.nan)
            continue

        up = basis_val + mult_bb * std_val
        lo = basis_val - mult_bb * std_val

        if basis_val != 0:
            bbw_list.append((up - lo) * 10.0 / basis_val)
        else:
            bbw_list.append(math.nan)

    # 4. CSV와 비교
    csv_start_idx = 1358

    print("=" * 100)
    print("BBW 값 비교 (Redis 계산 vs CSV)")
    print("=" * 100)
    print()

    print(f"{'CSV':<5} {'Redis':<7} {'Timestamp':<20} {'Close':>10} {'Python BBW':>12} {'CSV BBW':>10} {'Diff':>10} {'Match':<6}")
    print("-" * 100)

    matches = 0
    mismatches = 0
    max_diff = 0
    mismatch_details = []

    for csv_idx in range(min(50, len(pine_df))):
        redis_idx = csv_start_idx + csv_idx

        if redis_idx >= len(all_candles):
            break

        row = pine_df.iloc[csv_idx]

        # Skip NaN
        if pd.isna(row['BBW']):
            continue

        csv_bbw = float(row['BBW'])
        python_bbw = bbw_list[redis_idx]

        if math.isnan(python_bbw):
            continue

        diff = abs(csv_bbw - python_bbw)
        match = "✅" if diff < 0.00001 else "❌"

        if diff >= 0.00001:
            mismatches += 1
            max_diff = max(max_diff, diff)
            if len(mismatch_details) < 20:
                mismatch_details.append({
                    'csv_idx': csv_idx,
                    'redis_idx': redis_idx,
                    'timestamp': all_candles[redis_idx]['timestamp'],
                    'close': all_candles[redis_idx]['close'],
                    'python_bbw': python_bbw,
                    'csv_bbw': csv_bbw,
                    'diff': diff
                })
        else:
            matches += 1

        print(f"{csv_idx:<5} {redis_idx:<7} {str(all_candles[redis_idx]['timestamp'])[:19]:<20} "
              f"{all_candles[redis_idx]['close']:>10.2f} {python_bbw:>12.6f} {csv_bbw:>10.6f} {diff:>10.6f} {match:<6}")

    total = matches + mismatches
    print()
    print("=" * 100)
    print(f"총 비교: {total}개")
    print(f"✅ 일치 (diff < 0.00001): {matches}개 ({matches/total*100:.2f}%)")
    print(f"❌ 불일치 (diff >= 0.00001): {mismatches}개 ({mismatches/total*100:.2f}%)")
    print(f"최대 차이: {max_diff:.6f}")
    print()

    if mismatch_details:
        print("=" * 100)
        print("불일치 상세 (처음 20개)")
        print("=" * 100)
        for detail in mismatch_details:
            print(f"CSV:{detail['csv_idx']} Redis:{detail['redis_idx']} {detail['timestamp']}")
            print(f"  Close: {detail['close']:.2f}")
            print(f"  Python BBW: {detail['python_bbw']:.6f}")
            print(f"  CSV BBW: {detail['csv_bbw']:.6f}")
            print(f"  Diff: {detail['diff']:.6f}")
            print()


if __name__ == "__main__":
    main()
