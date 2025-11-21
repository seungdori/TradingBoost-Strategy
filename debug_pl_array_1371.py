#!/usr/bin/env python3
"""
Redis:1358~1371 범위에서 pl_array 구성 추적
PineScript와 비교하여 어떤 pivot이 다른지 확인
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
        else:
            up = basis_val + mult_bb * std_val
            lo = basis_val - mult_bb * std_val
            if basis_val != 0:
                bbw_list.append((up - lo) * 10.0 / basis_val)
            else:
                bbw_list.append(math.nan)

    # BBW MA
    bbw_ma = calc_sma(bbw_list, 100)

    # Pivot Low
    pl_list = pivotlow(bbw_list, 20, 10)

    # pl_array 추적 (전체 범위 0-1371)
    target_idx = 1371
    array_size = 50
    pivot_left = 20
    pl_array = []
    pl_array_history = []

    print("🔍 pl_array 구성 추적 (전체 범위, 1300-1371 출력)\n")
    print(f"{'Redis':<6} {'CSV':<5} {'BBW':<12} {'MA':<12} {'Pivot':<12} {'bbw<ma':<8} {'Action':<40} {'Size':<5}")
    print("=" * 120)

    for i in range(target_idx + 1):
        csv_idx = i - 1358
        bbw_val = bbw_list[i]
        ma_val = bbw_ma[i]

        # leftbars=20 offset 적용
        recent_pl = None
        pivot_idx = None
        if i >= pivot_left:
            if pl_list[i - pivot_left] is not None:
                recent_pl = pl_list[i - pivot_left]
                pivot_idx = i - pivot_left

        condition_met = False
        action = ""

        if ma_val is not None and not math.isnan(ma_val) and not math.isnan(bbw_val):
            if bbw_val < ma_val and recent_pl is not None:
                condition_met = True
                if len(pl_array) >= array_size:
                    removed = pl_array.pop(0)
                    action = f"Pop {removed:.6f}, Append pivot[{pivot_idx}]={recent_pl:.6f}"
                else:
                    action = f"Append pivot[{pivot_idx}]={recent_pl:.6f}"
                pl_array.append(recent_pl)

        pl_array_history.append(pl_array.copy())

        # 출력 (1300 이후만)
        if i >= 1300:
            bbw_str = f"{bbw_val:.6f}" if not math.isnan(bbw_val) else "NaN"
            ma_str = f"{ma_val:.6f}" if ma_val is not None and not math.isnan(ma_val) else "NaN"
            pivot_str = f"{recent_pl:.6f}" if recent_pl is not None else "None"
            cond_str = "True" if condition_met else "False"

            if condition_met or i in [1370, 1371]:  # Redis:1370, 1371은 항상 출력
                print(f"{i:<6} {csv_idx:<5} {bbw_str:<12} {ma_str:<12} {pivot_str:<12} {cond_str:<8} {action:<40} {len(pl_array):<5}")

    print("=" * 120)

    # CSV:13 (Redis:1371) 시점의 pl_avg 계산
    target_pl_array = pl_array_history[target_idx]

    if len(target_pl_array) > 0:
        pl_avg = sum(target_pl_array) / len(target_pl_array)
    else:
        pl_avg = min(bbw_list[target_idx] if not math.isnan(bbw_list[target_idx]) else 999, 5)

    print(f"\n📊 Redis:1371 (CSV:13) 시점 pl_array:")
    print(f"   Size: {len(target_pl_array)}")
    print(f"   pl_avg: {pl_avg:.6f}")
    print(f"   BBW: {bbw_list[target_idx]:.6f}")
    print(f"   BBW > pl_avg? {bbw_list[target_idx] > pl_avg}")
    print()

    # pl_array 전체 값 출력
    if len(target_pl_array) > 0:
        print(f"📋 pl_array 전체 값 ({len(target_pl_array)}개):")
        for idx, val in enumerate(target_pl_array):
            print(f"   [{idx:2d}]: {val:.6f}")
        print(f"   최소값: {min(target_pl_array):.6f}")
        print(f"   최대값: {max(target_pl_array):.6f}")
        print(f"   평균값: {pl_avg:.6f}")
    print()

    print(f"💡 CSV(PineScript) 추정:")
    print(f"   pl_avg < 0.040815 (CSV:13에서 reset 조건 충족)")
    print(f"   → PineScript pl_avg는 약 0.040 이하")
    print()
    print(f"⚠️  Python vs PineScript:")
    print(f"   Python pl_avg: {pl_avg:.6f}")
    print(f"   PineScript pl_avg (추정): < 0.040815")
    print(f"   차이: ≥ {pl_avg - 0.040815:.6f}")


if __name__ == "__main__":
    main()
