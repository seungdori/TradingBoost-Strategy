#!/usr/bin/env python3
"""
Redis:1371의 모든 중간 계산 값 출력
"""

import redis
import json
import math
from datetime import datetime
from shared.config import get_settings
from shared.indicators._moving_averages import calc_sma
from shared.indicators._bollinger import calc_stddev
from shared.indicators._core import pivothigh, pivotlow


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
            "open": float(c["open"]),
            "high": float(c["high"]),
            "low": float(c["low"]),
            "close": float(c["close"]),
            "volume": float(c.get("volume", 0))
        })

    closes = [c["close"] for c in all_candles]

    # BBW 1st 계산
    length_bb = 15
    mult_bb = 1.5
    ma_length = 100

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

    # BBW MA
    bbw_ma = calc_sma(bbw_list, ma_length)

    # Pivot
    pivot_left = 20
    pivot_right = 10
    pl_list = pivotlow(bbw_list, pivot_left, pivot_right)

    # Pivot array 구축 (Redis:1371까지)
    array_size = 50
    mult_plph = 0.7
    pl_array = [math.nan] * array_size

    # 여러 캔들의 pl_avg를 계산 (1369, 1370, 1371)
    targets = [1369, 1370, 1371]
    results = {}

    for target_idx in targets:
        pl_array_tmp = [math.nan] * array_size

        for i in range(target_idx + 1):
            bbw_val = bbw_list[i]
            ma_val = bbw_ma[i]

            # Pivot low
            recent_pl = None
            if i >= pivot_left:
                if pl_list[i - pivot_left] is not None:
                    recent_pl = pl_list[i - pivot_left]

            # Update array
            if ma_val is not None and not math.isnan(ma_val) and not math.isnan(bbw_val):
                if bbw_val < ma_val and recent_pl is not None:
                    pl_array_tmp.pop(0)
                    pl_array_tmp.append(recent_pl)

        # pl_avg 계산
        valid_pl = [v for v in pl_array_tmp if not math.isnan(v)]
        if len(valid_pl) > 0:
            pl_avg_tmp = sum(valid_pl) / len(valid_pl)
        else:
            pl_avg_tmp = min(bbw_list[target_idx] if not math.isnan(bbw_list[target_idx]) else 999, 5)

        squeeze_tmp = pl_avg_tmp * (1 / mult_plph)

        # BBW rising/falling
        bbw_rising_tmp = False
        bbw_falling_tmp = False
        if target_idx >= 2:
            if not math.isnan(bbw_list[target_idx-1]) and not math.isnan(bbw_list[target_idx-2]):
                bbw_rising_tmp = (bbw_list[target_idx] > bbw_list[target_idx-1])
                bbw_falling_tmp = (bbw_list[target_idx] < bbw_list[target_idx-1] and bbw_list[target_idx-1] < bbw_list[target_idx-2])

        results[target_idx] = {
            'bbw': bbw_list[target_idx],
            'pl_avg': pl_avg_tmp,
            'squeeze': squeeze_tmp,
            'bbw_rising': bbw_rising_tmp,
            'bbw_falling': bbw_falling_tmp,
            'bbw_gt_pl_avg': bbw_list[target_idx] > pl_avg_tmp,
            'bbw_lt_squeeze': bbw_list[target_idx] < squeeze_tmp
        }

    target_idx = 1371
    pl_avg = results[target_idx]['pl_avg']
    squeeze = results[target_idx]['squeeze']

    # BBW rising/falling
    bbw_rising = False
    bbw_falling = False
    if target_idx >= 2:
        if not math.isnan(bbw_list[target_idx-1]) and not math.isnan(bbw_list[target_idx-2]):
            bbw_rising = (bbw_list[target_idx] > bbw_list[target_idx-1])
            bbw_falling = (bbw_list[target_idx] < bbw_list[target_idx-1] and bbw_list[target_idx-1] < bbw_list[target_idx-2])

    # 결과 출력
    print("=" * 120)
    print(f"Redis:1369-1371 상세 비교")
    print("=" * 120)
    print()

    print(f"{'Index':<7} {'Timestamp':<20} {'BBW':>10} {'PL_avg':>10} {'Squeeze':>10} {'bbw>pl_avg':<12} {'bbw<squeeze':<12} {'bbw_rising':<12}")
    print("-" * 120)

    for idx in targets:
        r = results[idx]
        print(f"{idx:<7} {str(all_candles[idx]['timestamp'])[:19]:<20} {r['bbw']:>10.6f} {r['pl_avg']:>10.6f} {r['squeeze']:>10.6f} "
              f"{str(r['bbw_gt_pl_avg']):<12} {str(r['bbw_lt_squeeze']):<12} {str(r['bbw_rising']):<12}")

    print()
    print("=" * 120)
    print("Redis:1369-1371 BB_State 로직 분석")
    print("=" * 120)
    print()

    for idx in targets:
        r = results[idx]
        print(f"=== Redis:{idx} ===")
        print(f"BBW: {r['bbw']:.6f}")
        print(f"PL_avg: {r['pl_avg']:.6f}")
        print(f"Squeeze: {r['squeeze']:.6f}")
        print()

        # Squeeze 조건
        if r['bbw_lt_squeeze']:
            print(f"✓ bbw < squeeze ({r['bbw']:.6f} < {r['squeeze']:.6f}) → BB_State = -1 설정 시도")
        else:
            print(f"✗ bbw >= squeeze ({r['bbw']:.6f} >= {r['squeeze']:.6f}) → squeeze 조건 불만족")

        # 리셋 조건
        if r['bbw_gt_pl_avg'] and r['bbw_rising']:
            print(f"✓ 리셋 조건: bbw > pl_avg ({r['bbw']:.6f} > {r['pl_avg']:.6f}) and bbw_rising → BB_State = 0")
        else:
            if not r['bbw_gt_pl_avg']:
                print(f"✗ 리셋 조건 불만족: bbw <= pl_avg ({r['bbw']:.6f} <= {r['pl_avg']:.6f})")
            if not r['bbw_rising']:
                print(f"✗ 리셋 조건 불만족: bbw_rising = False")

        print()


if __name__ == "__main__":
    main()
