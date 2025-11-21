#!/usr/bin/env python3
"""
Redis:1351 주변의 pivot low 값들 확인
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

    # Redis:1341-1361 (1351 ± 10) pivot 값 확인
    print("=" * 140)
    print("Redis:1341-1361 Pivot Low 값 확인")
    print("=" * 140)
    print()

    print(f"{'Index':<7} {'Timestamp':<20} {'BBW':>10} {'BBW_MA':>10} {'bbw<ma':<8} {'Pivot Low':>12} {'Used at':<10}")
    print("-" * 140)

    for idx in range(1341, 1362):
        bbw_val = bbw_list[idx]
        ma_val = bbw_ma[idx]
        pl_val = pl_list[idx]
        bbw_lt_ma = (bbw_val < ma_val) if (not math.isnan(bbw_val) and ma_val is not None and not math.isnan(ma_val)) else False

        # 이 pivot이 어디서 사용되는지 (idx + 20)
        used_at = idx + pivot_left

        pl_str = f"{pl_val:.6f}" if pl_val is not None else "None"
        ma_str = f"{ma_val:.6f}" if ma_val is not None and not math.isnan(ma_val) else "NaN"

        print(f"{idx:<7} {str(all_candles[idx]['timestamp'])[:19]:<20} {bbw_val:>10.6f} {ma_str:>10} "
              f"{str(bbw_lt_ma):<8} {pl_str:>12} {used_at:<10}")

    print()
    print("=" * 140)
    print("Redis:1371에서 참조하는 pivot (pl_list[1351])")
    print("=" * 140)
    print()

    ref_idx = 1351
    pl_val_1351 = pl_list[ref_idx]
    print(f"pl_list[{ref_idx}] = {pl_val_1351 if pl_val_1351 is not None else 'None'}")
    print(f"BBW[{ref_idx}] = {bbw_list[ref_idx]:.6f}")
    ma_val_str = f"{bbw_ma[ref_idx]:.6f}" if bbw_ma[ref_idx] is not None and not math.isnan(bbw_ma[ref_idx]) else "NaN"
    print(f"BBW_MA[{ref_idx}] = {ma_val_str}")

    if pl_val_1351 is not None:
        print(f"\n✅ Redis:1371에서 recent_pl = {pl_val_1351:.6f} 사용")
    else:
        print(f"\n❌ Redis:1371에서 recent_pl = None (pivot 없음)")

    print()
    print("=" * 140)
    print("pl_array 업데이트 조건 확인 (Redis:1341-1371)")
    print("=" * 140)
    print()

    # pl_array 시뮬레이션
    array_size = 50
    pl_array = [math.nan] * array_size
    updates = []

    for i in range(1372):  # 1371까지
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
                pl_array.pop(0)
                pl_array.append(recent_pl)
                if i >= 1341:  # 1341부터 기록
                    updates.append({
                        'idx': i,
                        'timestamp': all_candles[i]['timestamp'],
                        'bbw': bbw_val,
                        'ma': ma_val,
                        'recent_pl': recent_pl,
                        'source_idx': i - pivot_left
                    })

    print(f"총 {len(updates)}개의 업데이트")
    print()

    if updates:
        print("최근 20개 업데이트:")
        print(f"{'Index':<7} {'Timestamp':<20} {'BBW':>10} {'MA':>10} {'recent_pl':>12} {'source_idx':<12}")
        print("-" * 140)
        for upd in updates[-20:]:
            print(f"{upd['idx']:<7} {str(upd['timestamp'])[:19]:<20} {upd['bbw']:>10.6f} {upd['ma']:>10.6f} "
                  f"{upd['recent_pl']:>12.6f} {upd['source_idx']:<12}")


if __name__ == "__main__":
    main()
