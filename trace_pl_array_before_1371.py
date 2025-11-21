#!/usr/bin/env python3
"""
Redis:1371 이전의 pl_array 업데이트만 추적
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

    # pl_array 시뮬레이션 (Redis:1372까지만)
    array_size = 50
    pl_array = [math.nan] * array_size

    # Redis:1372까지의 업데이트 기록
    updates_before_1372 = []

    for i in range(1373):  # 0 ~ 1372
        bbw_val = bbw_list[i]
        ma_val = bbw_ma[i]

        # Pivot low
        recent_pl = None
        if i >= pivot_left:
            if pl_list[i - pivot_left] is not None:
                recent_pl = pl_list[i - pivot_left]

        # Update array (PineScript 로직: shift → push)
        if ma_val is not None and not math.isnan(ma_val) and not math.isnan(bbw_val):
            if bbw_val < ma_val and recent_pl is not None:
                # 업데이트 발생!
                pl_array.pop(0)  # shift
                pl_array.append(recent_pl)  # push

                # pl_avg 계산
                valid_pl = [v for v in pl_array if not math.isnan(v)]
                if len(valid_pl) > 0:
                    pl_avg = sum(valid_pl) / len(valid_pl)
                else:
                    pl_avg = min(bbw_val if not math.isnan(bbw_val) else 999, 5)

                updates_before_1372.append({
                    'idx': i,
                    'timestamp': all_candles[i]['timestamp'],
                    'bbw': bbw_val,
                    'ma': ma_val,
                    'recent_pl': recent_pl,
                    'source_idx': i - pivot_left,
                    'pl_avg_after': pl_avg,
                    'valid_count': len(valid_pl)
                })

    print("=" * 140)
    print("Redis:1372 이전의 모든 pl_array 업데이트")
    print("=" * 140)
    print()

    print(f"총 {len(updates_before_1372)}개의 업데이트")
    print()

    # 모든 업데이트 출력
    print(f"{'Index':<7} {'Timestamp':<20} {'BBW':>10} {'MA':>10} {'recent_pl':>12} {'source_idx':<12} {'pl_avg':>12} {'count':<6}")
    print("-" * 140)

    for upd in updates_before_1372:
        print(f"{upd['idx']:<7} {str(upd['timestamp'])[:19]:<20} {upd['bbw']:>10.6f} {upd['ma']:>10.6f} "
              f"{upd['recent_pl']:>12.6f} {upd['source_idx']:<12} {upd['pl_avg_after']:>12.6f} {upd['valid_count']:<6}")

    print()

    # Redis:1371과 1372에서의 pl_avg
    print("=" * 140)
    print("Redis:1371과 1372에서의 pl_avg")
    print("=" * 140)
    print()

    # 1371까지의 업데이트로 pl_array 구성
    pl_array_1371 = [math.nan] * array_size
    for upd in updates_before_1372:
        if upd['idx'] <= 1371:
            pl_array_1371.pop(0)
            pl_array_1371.append(upd['recent_pl'])

    valid_pl_1371 = [v for v in pl_array_1371 if not math.isnan(v)]
    if len(valid_pl_1371) > 0:
        pl_avg_1371 = sum(valid_pl_1371) / len(valid_pl_1371)
    else:
        bbw_1371 = bbw_list[1371]
        pl_avg_1371 = min(bbw_1371 if not math.isnan(bbw_1371) else 999, 5)

    print(f"Redis:1371 pl_avg = {pl_avg_1371:.6f} (유효 개수: {len(valid_pl_1371)})")
    print(f"Redis:1371 BBW    = {bbw_list[1371]:.6f}")
    print(f"리셋 조건 (bbw > pl_avg): {bbw_list[1371] > pl_avg_1371}")
    print()

    # 1372까지의 업데이트로 pl_array 구성
    pl_array_1372 = [math.nan] * array_size
    for upd in updates_before_1372:
        pl_array_1372.pop(0)
        pl_array_1372.append(upd['recent_pl'])

    valid_pl_1372 = [v for v in pl_array_1372 if not math.isnan(v)]
    if len(valid_pl_1372) > 0:
        pl_avg_1372 = sum(valid_pl_1372) / len(valid_pl_1372)
    else:
        bbw_1372 = bbw_list[1372]
        pl_avg_1372 = min(bbw_1372 if not math.isnan(bbw_1372) else 999, 5)

    print(f"Redis:1372 pl_avg = {pl_avg_1372:.6f} (유효 개수: {len(valid_pl_1372)})")
    print(f"Redis:1372 BBW    = {bbw_list[1372]:.6f}")
    print(f"리셋 조건 (bbw > pl_avg): {bbw_list[1372] > pl_avg_1372}")
    print()

    # pl_array 내용
    print("=" * 140)
    print("pl_array 내용 (Redis:1371 시점)")
    print("=" * 140)
    print()

    for i, val in enumerate(pl_array_1371):
        if not math.isnan(val):
            print(f"  [{i:2d}]: {val:.6f}")
    print()


if __name__ == "__main__":
    main()
