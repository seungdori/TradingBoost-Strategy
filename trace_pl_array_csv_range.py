#!/usr/bin/env python3
"""
CSV 범위 (Redis:1358~) pl_array 업데이트 추적
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

    # CSV 시작점
    csv_start = 1358

    # pl_array 시뮬레이션
    array_size = 50
    pl_array = [math.nan] * array_size

    # 전체 업데이트 기록
    all_updates = []

    for i in range(len(bbw_list)):
        bbw_val = bbw_list[i]
        ma_val = bbw_ma[i]

        # Pivot low (새 로직: pl_list[i] 사용)
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
                    pl_avg = sum(valid_pl) / len(valid_pl)
                else:
                    pl_avg = min(bbw_val if not math.isnan(bbw_val) else 999, 5)

                all_updates.append({
                    'idx': i,
                    'timestamp': all_candles[i]['timestamp'],
                    'bbw': bbw_val,
                    'ma': ma_val,
                    'recent_pl': recent_pl,
                    'pl_avg_after': pl_avg,
                    'valid_count': len(valid_pl)
                })

    print("=" * 140)
    print(f"CSV 범위 (Redis:{csv_start}~) pl_array 업데이트")
    print("=" * 140)
    print()

    # CSV 범위 내 업데이트만 필터링
    updates_in_csv = [upd for upd in all_updates if upd['idx'] >= csv_start]

    print(f"CSV 범위 내 총 {len(updates_in_csv)}개의 업데이트")
    print()

    if updates_in_csv:
        print(f"{'Redis Idx':<10} {'CSV Idx':<10} {'Timestamp':<20} {'BBW':>10} {'MA':>10} {'recent_pl':>12} {'pl_avg':>12}")
        print("-" * 140)

        for upd in updates_in_csv:
            csv_idx = upd['idx'] - csv_start
            print(f"{upd['idx']:<10} {csv_idx:<10} {str(upd['timestamp'])[:19]:<20} {upd['bbw']:>10.6f} {upd['ma']:>10.6f} "
                  f"{upd['recent_pl']:>12.6f} {upd['pl_avg_after']:>12.6f}")
    else:
        print("CSV 범위 내에는 업데이트가 없습니다.")

    print()
    print("=" * 140)
    print("Redis:1301~1400 업데이트 확인")
    print("=" * 140)
    print()

    updates_1300s = [upd for upd in all_updates if 1301 <= upd['idx'] <= 1400]
    print(f"총 {len(updates_1300s)}개의 업데이트")

    if updates_1300s:
        print()
        print(f"{'Redis Idx':<10} {'Timestamp':<20} {'BBW':>10} {'MA':>10} {'recent_pl':>12} {'pl_avg':>12}")
        print("-" * 140)
        for upd in updates_1300s:
            print(f"{upd['idx']:<10} {str(upd['timestamp'])[:19]:<20} {upd['bbw']:>10.6f} {upd['ma']:>10.6f} "
                  f"{upd['recent_pl']:>12.6f} {upd['pl_avg_after']:>12.6f}")


if __name__ == "__main__":
    main()
