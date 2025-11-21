#!/usr/bin/env python3
"""
Redis:1559 (CSV:201) 지점 상세 디버깅
"""

import redis
import json
import math
from datetime import datetime
from shared.config import get_settings
from fixed_calc_bb_state import _calc_bb_state_fixed

# 디버그용으로 수정된 버전
def _calc_bb_state_debug(candle_data, target_idx=1559, length_bb=15, mult_bb=1.5, ma_length=100):
    from shared.indicators._moving_averages import calc_sma
    from shared.indicators._bollinger import calc_stddev
    from shared.indicators._core import pivothigh, pivotlow

    closes = [c["close"] for c in candle_data]

    # BBW 계산
    basis_list = calc_sma(closes, length_bb)
    std_list = calc_stddev(closes, length_bb)
    bbw_list = []
    bbr_list = []

    for i in range(len(closes)):
        basis_val = basis_list[i]
        std_val = std_list[i]
        if basis_val is None or std_val is None or math.isnan(basis_val) or math.isnan(std_val):
            bbw_list.append(math.nan)
            bbr_list.append(math.nan)
            continue

        up = basis_val + mult_bb * std_val
        lo = basis_val - mult_bb * std_val

        if basis_val != 0:
            bbw_list.append((up - lo) * 10.0 / basis_val)
        else:
            bbw_list.append(math.nan)

        if (up - lo) != 0:
            bbr_list.append((closes[i] - lo) / (up - lo))
        else:
            bbr_list.append(math.nan)

    # BBW MA
    bbw_ma = calc_sma(bbw_list, ma_length)

    # Pivot
    ph_list = pivothigh(bbw_list, 20, 10)
    pl_list = pivotlow(bbw_list, 20, 10)

    # Pivot arrays 동적 업데이트
    array_size = 50
    ph_array = []
    pl_array = []
    mult_plph = 0.7

    for i in range(target_idx + 1):
        bbw_val = bbw_list[i]
        ma_val = bbw_ma[i]

        # ph_array 업데이트
        if ma_val is not None and not math.isnan(ma_val) and not math.isnan(bbw_val):
            if bbw_val > ma_val and ph_list[i] is not None:
                if len(ph_array) >= array_size:
                    ph_array.pop(0)
                ph_array.append(ph_list[i])

        # pl_array 업데이트
        if ma_val is not None and not math.isnan(ma_val) and not math.isnan(bbw_val):
            if bbw_val < ma_val and pl_list[i] is not None:
                if len(pl_array) >= array_size:
                    pl_array.pop(0)
                pl_array.append(pl_list[i])

    # target_idx에서의 avg 계산
    if len(ph_array) > 0:
        ph_avg = sum(ph_array) / len(ph_array)
    else:
        bbw_val = bbw_list[target_idx]
        ph_avg = max(bbw_val if not math.isnan(bbw_val) else 0, 5)

    if len(pl_array) > 0:
        pl_avg = sum(pl_array) / len(pl_array)
    else:
        bbw_val = bbw_list[target_idx]
        pl_avg = min(bbw_val if not math.isnan(bbw_val) else 999, 5)

    buzz = ph_avg * mult_plph
    squeeze = pl_avg * (1 / mult_plph)

    print(f"Redis:{target_idx} 중간 계산값:")
    print(f"  close[{target_idx-1}] = {closes[target_idx-1]:.2f}")
    print(f"  close[{target_idx}] = {closes[target_idx]:.2f}")
    print(f"  BBW[{target_idx-1}] = {bbw_list[target_idx-1]:.6f}")
    print(f"  BBW[{target_idx}] = {bbw_list[target_idx]:.6f}")
    print(f"  BBR[{target_idx}] = {bbr_list[target_idx]:.6f}")
    print(f"  BBW_MA[{target_idx}] = {bbw_ma[target_idx]:.6f}")
    print(f"\n  ph_array size = {len(ph_array)}")
    print(f"  pl_array size = {len(pl_array)}")
    print(f"  ph_avg = {ph_avg:.6f}")
    print(f"  pl_avg = {pl_avg:.6f}")
    print(f"  buzz = {buzz:.6f}")
    print(f"  squeeze = {squeeze:.6f}")
    
    # Crossover 체크
    bbw_prev = bbw_list[target_idx-1]
    bbw_curr = bbw_list[target_idx]
    bbr_curr = bbr_list[target_idx]

    print(f"\n  Crossover check:")
    print(f"    bbw_prev ({bbw_prev:.6f}) <= buzz ({buzz:.6f})? {bbw_prev <= buzz}")
    print(f"    bbw_curr ({bbw_curr:.6f}) > buzz ({buzz:.6f})? {bbw_curr > buzz}")
    print(f"    bbr_curr ({bbr_curr:.6f}) < 0.5? {bbr_curr < 0.5}")
    
    if bbw_prev <= buzz and bbw_curr > buzz:
        print(f"  ✅ CROSSOVER 발생!")
        if bbr_curr < 0.5:
            print(f"  → BB_State should be -2")
        elif bbr_curr > 0.5:
            print(f"  → BB_State should be 2")
        else:
            print(f"  → BB_State should remain (bbr == 0.5)")
    else:
        print(f"  ❌ NO CROSSOVER")


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

    print("🔍 Redis:1559 (CSV:201) 상세 디버깅\n")
    _calc_bb_state_debug(all_candles, target_idx=1559)


if __name__ == "__main__":
    main()
