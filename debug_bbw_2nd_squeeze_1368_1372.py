#!/usr/bin/env python3
"""
Redis:1368-1372의 bbw_2nd_squeeze 상태 추적
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

    # BBW 2nd 계산
    length_2nd = 60
    mult_bb = 1.5
    mult_plph = 0.7

    basis_2nd_list = calc_sma(closes, length_2nd)
    stdev_2nd_list = calc_stddev(closes, length_2nd)
    bbw_2nd_list = []

    for i in range(len(closes)):
        basis_val = basis_2nd_list[i]
        stdev_val = stdev_2nd_list[i]
        if basis_val is None or stdev_val is None or math.isnan(basis_val) or math.isnan(stdev_val):
            bbw_2nd_list.append(math.nan)
        else:
            upper_2nd = basis_val + mult_bb * stdev_val
            lower_2nd = basis_val - mult_bb * stdev_val
            if basis_val != 0:
                bbw_2nd_list.append((upper_2nd - lower_2nd) * 10.0 / basis_val)
            else:
                bbw_2nd_list.append(math.nan)

    # Pivot Low for BBW_2nd
    pl_2nd_list = pivotlow(bbw_2nd_list, 30, 10)

    # pl_array_2nd 구축 및 bbw_2nd_squeeze 계산
    array_size = 50
    use_bbw_2nd = True

    results = {}

    for target_idx in range(1368, 1373):
        pl_array_2nd = [math.nan] * array_size
        bbw_2nd_squeeze_history = []

        for i in range(target_idx + 1):
            bbw_2nd_val = bbw_2nd_list[i]

            # Pivot low 2nd (leftbars=30)
            recent_pl_2nd = None
            if i >= 30:
                if pl_2nd_list[i - 30] is not None:
                    recent_pl_2nd = pl_2nd_list[i - 30]

            # Update array
            if not math.isnan(bbw_2nd_val) and bbw_2nd_val < 1 and recent_pl_2nd is not None:
                pl_array_2nd.pop(0)
                pl_array_2nd.append(recent_pl_2nd)

            # pl_avg_2nd 계산
            valid_pl_2nd = [v for v in pl_array_2nd if not math.isnan(v)]
            if len(valid_pl_2nd) > 0:
                pl_avg_2nd = sum(valid_pl_2nd) / len(valid_pl_2nd)
            else:
                pl_avg_2nd = min(bbw_2nd_val if not math.isnan(bbw_2nd_val) else 999, 5)

            squeeze_2nd = pl_avg_2nd * (1 / mult_plph)

            # bbw_2nd_squeeze 상태 업데이트
            prev_squeeze = bbw_2nd_squeeze_history[-1] if bbw_2nd_squeeze_history else True
            current_squeeze = prev_squeeze

            if use_bbw_2nd:
                if not math.isnan(bbw_2nd_val):
                    if bbw_2nd_val > squeeze_2nd:
                        current_squeeze = False
                    elif bbw_2nd_val < squeeze_2nd:
                        current_squeeze = True
                    # else: current_squeeze 유지
            else:
                current_squeeze = True

            bbw_2nd_squeeze_history.append(current_squeeze)

        # 최종 상태 저장
        results[target_idx] = {
            'bbw_2nd': bbw_2nd_list[target_idx],
            'pl_avg_2nd': pl_avg_2nd,
            'squeeze_2nd': squeeze_2nd,
            'bbw_2nd_squeeze': current_squeeze,
            'bbw_2nd_gt_squeeze': bbw_2nd_list[target_idx] > squeeze_2nd if not math.isnan(bbw_2nd_list[target_idx]) else False,
            'bbw_2nd_lt_squeeze': bbw_2nd_list[target_idx] < squeeze_2nd if not math.isnan(bbw_2nd_list[target_idx]) else False
        }

    # 결과 출력
    print("=" * 120)
    print("Redis:1368-1372 bbw_2nd_squeeze 상태 추적")
    print("=" * 120)
    print()

    print(f"{'Index':<7} {'Timestamp':<20} {'BBW_2nd':>10} {'Squeeze_2nd':>12} {'bbw>sq':<8} {'bbw<sq':<8} {'bbw_2nd_squeeze':<17}")
    print("-" * 120)

    for idx in range(1368, 1373):
        r = results[idx]
        bbw_2nd_str = f"{r['bbw_2nd']:.6f}" if not math.isnan(r['bbw_2nd']) else "NaN"
        print(f"{idx:<7} {str(all_candles[idx]['timestamp'])[:19]:<20} {bbw_2nd_str:>10} {r['squeeze_2nd']:>12.6f} "
              f"{str(r['bbw_2nd_gt_squeeze']):<8} {str(r['bbw_2nd_lt_squeeze']):<8} {str(r['bbw_2nd_squeeze']):<17}")

    print()
    print("=" * 120)
    print("bbw_2nd_squeeze 상태 전환 분석")
    print("=" * 120)
    print()

    for idx in range(1368, 1373):
        r = results[idx]
        print(f"=== Redis:{idx} ===")
        print(f"BBW_2nd: {r['bbw_2nd']:.6f}" if not math.isnan(r['bbw_2nd']) else f"BBW_2nd: NaN")
        print(f"Squeeze_2nd: {r['squeeze_2nd']:.6f}")
        print(f"bbw_2nd_squeeze: {r['bbw_2nd_squeeze']}")
        print()

        if r['bbw_2nd_gt_squeeze']:
            print(f"→ BBW_2nd > Squeeze_2nd: bbw_2nd_squeeze = False")
        elif r['bbw_2nd_lt_squeeze']:
            print(f"→ BBW_2nd < Squeeze_2nd: bbw_2nd_squeeze = True")
        else:
            print(f"→ BBW_2nd == Squeeze_2nd 또는 NaN: bbw_2nd_squeeze 유지")

        print()


if __name__ == "__main__":
    main()
