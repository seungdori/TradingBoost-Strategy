#!/usr/bin/env python3
"""
Redis:1559 시점의 ph_array 상세 추적
각 pivot이 언제 추가되었는지, 어떤 값인지 상세히 출력
"""

import redis
import json
import math
from datetime import datetime
from shared.config import get_settings
from shared.indicators._moving_averages import calc_sma
from shared.indicators._bollinger import calc_stddev
from shared.indicators._core import pivothigh, pivotlow


def track_ph_array_population(candle_data, target_idx=1559, length_bb=15, mult_bb=1.5, ma_length=100):
    """
    target_idx까지의 ph_array 구성 과정을 상세히 추적
    """
    closes = [c["close"] for c in candle_data]

    # BBW 계산
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

    # Pivot High/Low 계산
    ph_list = pivothigh(bbw_list, 20, 10)

    # ph_array 동적 추적
    array_size = 50
    ph_array = []
    ph_array_history = []  # 각 시점의 ph_array 상태 저장

    print(f"🔍 ph_array 구성 추적 (target: Redis:{target_idx})\n")
    print(f"{'Index':<8} {'BBW':<12} {'BBW_MA':<12} {'Pivot':<12} {'Condition':<15} {'Action':<30} {'Array Size':<12}")
    print("=" * 120)

    for i in range(target_idx + 1):
        bbw_val = bbw_list[i]
        ma_val = bbw_ma[i]
        pivot_val = ph_list[i]

        condition_met = False
        action = "No action"

        # ph_array 업데이트 조건
        if ma_val is not None and not math.isnan(ma_val) and not math.isnan(bbw_val):
            if bbw_val > ma_val and pivot_val is not None:
                condition_met = True

                # 배열 크기 관리
                if len(ph_array) >= array_size:
                    removed = ph_array.pop(0)
                    action = f"Pop {removed:.6f}, Append {pivot_val:.6f}"
                else:
                    action = f"Append {pivot_val:.6f}"

                ph_array.append(pivot_val)

        # 상태 저장
        ph_array_history.append(ph_array.copy())

        # 출력 (pivot이 추가된 경우만)
        if condition_met:
            bbw_str = f"{bbw_val:.6f}" if not math.isnan(bbw_val) else "NaN"
            ma_str = f"{ma_val:.6f}" if ma_val is not None and not math.isnan(ma_val) else "NaN"
            pivot_str = f"{pivot_val:.6f}" if pivot_val is not None else "None"
            cond_str = f"BBW>{ma_str[:6]}" if condition_met else ""

            print(f"{i:<8} {bbw_str:<12} {ma_str:<12} {pivot_str:<12} {cond_str:<15} {action:<30} {len(ph_array):<12}")

    print("=" * 120)
    print(f"\n📊 Redis:{target_idx} 시점 ph_array 최종 상태:")
    print(f"   Size: {len(ph_array)}")

    if len(ph_array) > 0:
        ph_avg = sum(ph_array) / len(ph_array)
        buzz = ph_avg * 0.7

        print(f"   ph_avg: {ph_avg:.6f}")
        print(f"   buzz: {buzz:.6f}")
        print(f"\n   최근 10개 pivot 값:")
        for j, val in enumerate(ph_array[-10:]):
            print(f"      [{len(ph_array)-10+j}]: {val:.6f}")

        print(f"\n   가장 오래된 10개 pivot 값:")
        for j, val in enumerate(ph_array[:10]):
            print(f"      [{j}]: {val:.6f}")

        print(f"\n   통계:")
        print(f"      Min: {min(ph_array):.6f}")
        print(f"      Max: {max(ph_array):.6f}")
        print(f"      Mean: {ph_avg:.6f}")
        print(f"      Median: {sorted(ph_array)[len(ph_array)//2]:.6f}")
    else:
        print(f"   (Empty)")


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

    track_ph_array_population(all_candles, target_idx=1559)


if __name__ == "__main__":
    main()
