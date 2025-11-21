#!/usr/bin/env python3
"""
Redis:1371 (CSV:13) 지점 squeeze 상태 디버깅
CSV=0, Python=-1 차이 원인 분석
"""

import redis
import json
import math
from datetime import datetime
from shared.config import get_settings
from fixed_calc_bb_state import _calc_bb_state_fixed


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

    print("🔍 Redis:1371 (CSV:13) Squeeze 상태 디버깅\n")

    # BB_State 계산
    bb_state_results = _calc_bb_state_fixed(all_candles, is_confirmed_only=False)

    target_idx = 1371
    print(f"📊 Redis:{target_idx} BB_State = {bb_state_results[target_idx]}")
    print(f"   CSV 기대값: 0")
    print(f"   Python 계산: {bb_state_results[target_idx]}")
    print()

    # 상세 디버깅을 위해 중간 값들 출력하도록 수정된 버전 실행
    from shared.indicators._moving_averages import calc_sma
    from shared.indicators._bollinger import calc_stddev
    from shared.indicators._core import pivothigh, pivotlow

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

    # Pivot
    pl_list = pivotlow(bbw_list, 20, 10)

    # BBW 2nd
    length_2nd = 60
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

    # pl_array 구성 (target_idx까지)
    array_size = 50
    pl_array = []
    pivot_left = 20

    for i in range(target_idx + 1):
        bbw_val = bbw_list[i]
        ma_val = bbw_ma[i]

        # leftbars=20 지연
        recent_pl = None
        if i >= pivot_left:
            if pl_list[i - pivot_left] is not None:
                recent_pl = pl_list[i - pivot_left]

        if ma_val is not None and not math.isnan(ma_val) and not math.isnan(bbw_val):
            if bbw_val < ma_val and recent_pl is not None:
                if len(pl_array) >= array_size:
                    pl_array.pop(0)
                pl_array.append(recent_pl)

    # pl_avg, squeeze 계산
    if len(pl_array) > 0:
        pl_avg = sum(pl_array) / len(pl_array)
    else:
        bbw_val = bbw_list[target_idx]
        pl_avg = min(bbw_val if not math.isnan(bbw_val) else 999, 5)

    squeeze = pl_avg * (1 / 0.7)

    print(f"📈 Squeeze 관련 값:")
    print(f"   BBW[{target_idx}] = {bbw_list[target_idx]:.6f}")
    print(f"   pl_array size = {len(pl_array)}")
    print(f"   pl_avg = {pl_avg:.6f}")
    print(f"   squeeze = {squeeze:.6f}")
    print(f"   BBW < squeeze? {bbw_list[target_idx] < squeeze}")
    print()

    print(f"📉 BBW 2nd 관련 값:")
    print(f"   BBW_2nd[{target_idx}] = {bbw_2nd_list[target_idx]:.6f}")
    print()

    # bbw_2nd_squeeze 상태 추적은 복잡하므로 간단히 확인
    print(f"⚠️ Line 342-343 조건:")
    print(f"   if bbw < squeeze and bbw_2nd_squeeze:")
    print(f"       BB_State := -1")
    print()
    print(f"   bbw ({bbw_list[target_idx]:.6f}) < squeeze ({squeeze:.6f})? {bbw_list[target_idx] < squeeze}")
    print(f"   → Python은 -1로 판단")
    print(f"   → CSV(PineScript)는 0으로 판단")
    print()
    print(f"💡 가능한 원인:")
    print(f"   1. pl_avg 계산이 다름 (pl_array 내용이 다름)")
    print(f"   2. bbw_2nd_squeeze 상태가 다름")
    print(f"   3. Line 342-343에 barstate.isconfirmed 조건이 있는지 확인 필요")


if __name__ == "__main__":
    main()
