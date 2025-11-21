#!/usr/bin/env python3
"""
pl_avg 계산 방식 검증: Pine(50으로 나누기) vs Python(유효 개수로 나누기)
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

    for i in range(1372):  # 0 ~ 1371
        bbw_val = bbw_list[i]
        ma_val = bbw_ma[i]

        # Pivot low
        recent_pl = None
        if i >= pivot_left + pivot_right:
            if pl_list[i] is not None:
                recent_pl = pl_list[i]

        # Update array
        if ma_val is not None and not math.isnan(ma_val) and not math.isnan(bbw_val):
            if bbw_val < ma_val and recent_pl is not None:
                pl_array.pop(0)
                pl_array.append(recent_pl)

    # Redis:1371에서의 pl_avg 계산 - 두 가지 방식
    valid_pl = [v for v in pl_array if not math.isnan(v)]

    # Python 현재 방식: 유효한 개수로 나누기
    pl_avg_python = sum(valid_pl) / len(valid_pl) if len(valid_pl) > 0 else math.nan

    # Pine 방식: 항상 50으로 나누기 (na는 0으로 처리)
    pl_avg_pine = sum(valid_pl) / 50 if len(valid_pl) > 0 else math.nan

    # BBW at 1371
    bbw_1371 = bbw_list[1371]

    print("=" * 120)
    print("Redis:1371 시점의 pl_avg 계산 방식 비교")
    print("=" * 120)
    print()

    print(f"pl_array 상태:")
    print(f"  전체 크기: {len(pl_array)}")
    print(f"  유효 값 개수: {len(valid_pl)}")
    print(f"  유효 값 합계: {sum(valid_pl):.6f}")
    print()

    print(f"pl_avg 계산 결과:")
    print(f"  Python 방식 (유효 개수로 나누기): {sum(valid_pl):.6f} / {len(valid_pl)} = {pl_avg_python:.6f}")
    print(f"  Pine 방식   (50으로 나누기):      {sum(valid_pl):.6f} / 50 = {pl_avg_pine:.6f}")
    print()

    print(f"BBW at Redis:1371: {bbw_1371:.6f}")
    print()

    print(f"리셋 조건 검증 (bbw > pl_avg):")
    print(f"  Python 방식: {bbw_1371:.6f} > {pl_avg_python:.6f} = {bbw_1371 > pl_avg_python}")
    print(f"  Pine 방식:   {bbw_1371:.6f} > {pl_avg_pine:.6f} = {bbw_1371 > pl_avg_pine}")
    print()

    print("=" * 120)
    print("결론")
    print("=" * 120)
    print()

    if bbw_1371 > pl_avg_pine and not (bbw_1371 > pl_avg_python):
        print("✅ Pine 방식(50으로 나누기)이 정답입니다!")
        print(f"   Pine 방식으로 계산하면 bbw > pl_avg 조건이 True가 되어 리셋됩니다.")
        print(f"   Python 방식으로는 False가 되어 리셋되지 않습니다.")
        print()
        print(f"   Pine BB_State at 1371: 0 (리셋됨)")
        print(f"   Python BB_State at 1371: -1 (리셋 안됨)")
        print()
        print(f"   차이: {pl_avg_python - pl_avg_pine:.6f} ({(pl_avg_python - pl_avg_pine) / pl_avg_pine * 100:.2f}%)")
    elif bbw_1371 > pl_avg_python:
        print("❌ 두 방식 모두 리셋 조건을 만족합니다. 다른 문제가 있습니다.")
    else:
        print("❌ 두 방식 모두 리셋 조건을 만족하지 않습니다. 다른 문제가 있습니다.")

    print()
    print("pl_array 내용 (처음 10개와 마지막 10개):")
    print()
    print("처음 10개:")
    for i in range(min(10, len(pl_array))):
        val_str = f"{pl_array[i]:.6f}" if not math.isnan(pl_array[i]) else "NaN"
        print(f"  [{i:2d}]: {val_str}")
    print()
    print("마지막 10개:")
    for i in range(max(0, len(pl_array) - 10), len(pl_array)):
        val_str = f"{pl_array[i]:.6f}" if not math.isnan(pl_array[i]) else "NaN"
        print(f"  [{i:2d}]: {val_str}")


if __name__ == "__main__":
    main()
