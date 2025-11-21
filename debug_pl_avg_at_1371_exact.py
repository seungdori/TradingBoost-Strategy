#!/usr/bin/env python3
"""
Redis:1371 시점의 정확한 pl_avg 계산
"""

import redis
import json
import math
from datetime import datetime
from shared.config import get_settings
from shared.indicators._moving_averages import calc_sma
from shared.indicators._bollinger import calc_stddev
from shared.indicators._core import pivotlow

def main():
    # Redis 데이터 로드
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

    all_candles = []
    for c in redis_candles:
        all_candles.append({
            "timestamp": datetime.fromtimestamp(c["timestamp"]),
            "close": float(c["close"])
        })

    closes = [c["close"] for c in all_candles]

    # BBW 계산
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

    # Pivot Low 계산
    pivot_left = 20
    pivot_right = 10
    pl_list = pivotlow(bbw_list, pivot_left, pivot_right)

    # BBW MA
    ma_length = 100
    bbw_ma = calc_sma(bbw_list, ma_length)

    # pl_array 시뮬레이션 (Redis:1371까지)
    array_size = 50
    pl_array = [math.nan] * array_size

    last_pl_avg = None

    for i in range(1372):  # 0 ~ 1371
        bbw_val = bbw_list[i]
        ma_val = bbw_ma[i]

        # Pivot low (새 로직)
        recent_pl = None
        if i >= pivot_left + pivot_right:  # i >= 30
            if pl_list[i] is not None:
                recent_pl = pl_list[i]

        # Update array
        if ma_val is not None and not math.isnan(ma_val) and not math.isnan(bbw_val):
            if bbw_val < ma_val and recent_pl is not None:
                pl_array.pop(0)
                pl_array.append(recent_pl)

                # pl_avg 계산
                valid_pl = [v for v in pl_array if not math.isnan(v)]
                if len(valid_pl) > 0:
                    last_pl_avg = sum(valid_pl) / len(valid_pl)
                else:
                    last_pl_avg = min(bbw_val if not math.isnan(bbw_val) else 999, 5)

    print("=" * 100)
    print("Redis:1371 시점의 pl_avg (정확한 계산)")
    print("=" * 100)
    print()

    print(f"Redis:1371까지 계산:")
    print(f"  pl_avg = {last_pl_avg:.6f}")
    print(f"  BBW at 1371 = {bbw_list[1371]:.6f}")
    print(f"  리셋 조건 (bbw > pl_avg): {bbw_list[1371] > last_pl_avg}")
    print()

    # pl_array 내용
    valid_pl = [v for v in pl_array if not math.isnan(v)]
    print(f"pl_array 유효 개수: {len(valid_pl)}")
    print()

    print("pl_array 내용:")
    for i, val in enumerate(pl_array):
        if not math.isnan(val):
            print(f"  [{i:2d}]: {val:.6f}")
    print()

    # Pine 필요 조건
    bbw_1371 = bbw_list[1371]
    print(f"Pine이 Redis:1371에서 리셋하려면:")
    print(f"  pl_avg < {bbw_1371:.6f}")
    print(f"  현재 pl_avg = {last_pl_avg:.6f}")
    print(f"  차이 = {last_pl_avg - bbw_1371:.6f} ({(last_pl_avg - bbw_1371) / bbw_1371 * 100:.2f}%)")


if __name__ == "__main__":
    main()
