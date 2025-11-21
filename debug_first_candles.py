#!/usr/bin/env python3
"""
첫 번째 캔들들의 상세 디버깅
"""

import pandas as pd
import math
from shared.indicators._moving_averages import calc_sma
from shared.indicators._bollinger import calc_stddev
from shared.indicators._core import pivothigh, pivotlow


def main():
    csv_path = "/Users/seunghyun/Downloads/OKX_BTCUSDT.P, 15_ba3e6.csv"
    df = pd.read_csv(csv_path)

    # 캔들 준비
    candles = []
    for _, row in df.iterrows():
        candles.append({
            "timestamp": pd.to_datetime(row["time"]),
            "open": row["open"],
            "high": row["high"],
            "low": row["low"],
            "close": row["close"],
            "volume": 0.0
        })

    closes = [c["close"] for c in candles]

    # BBW 계산
    basis_list = calc_sma(closes, 15)
    std_list = calc_stddev(closes, 15)

    print("첫 20개 캔들의 BBW 계산:")
    print(f"{'Index':<6} {'Close':<12} {'Basis':<12} {'StdDev':<12} {'BBW':<12}")
    print("-" * 72)

    for i in range(min(20, len(closes))):
        basis_val = basis_list[i]
        std_val = std_list[i]

        bbw = "nan"
        if basis_val is not None and std_val is not None and not math.isnan(basis_val) and not math.isnan(std_val):
            up = basis_val + 1.5 * std_val
            lo = basis_val - 1.5 * std_val
            if basis_val != 0:
                bbw = f"{(up - lo) * 10.0 / basis_val:.6f}"

        b_str = f"{basis_val:.2f}" if basis_val is not None and not math.isnan(basis_val) else "nan"
        s_str = f"{std_val:.2f}" if std_val is not None and not math.isnan(std_val) else "nan"

        print(f"{i:<6} {closes[i]:<12.2f} {b_str:<12} {s_str:<12} {bbw:<12}")

    # Pivot 계산
    print("\n\nPivot 계산 (모든 캔들):")

    bbw_list = []
    for i in range(len(closes)):
        basis_val = basis_list[i]
        std_val = std_list[i]
        if basis_val is None or std_val is None or math.isnan(basis_val) or math.isnan(std_val):
            bbw_list.append(math.nan)
        else:
            up = basis_val + 1.5 * std_val
            lo = basis_val - 1.5 * std_val
            if basis_val != 0:
                bbw_list.append((up - lo) * 10.0 / basis_val)
            else:
                bbw_list.append(math.nan)

    ph_list = pivothigh(bbw_list, 20, 10)
    pl_list = pivotlow(bbw_list, 20, 10)

    pivot_count = sum(1 for p in ph_list if p is not None)
    print(f"Pivot High 개수: {pivot_count}")
    pivot_count = sum(1 for p in pl_list if p is not None)
    print(f"Pivot Low 개수: {pivot_count}")

    # 처음 pivot이 발견되는 지점 찾기
    for i in range(len(closes)):
        if ph_list[i] is not None:
            print(f"\n첫 Pivot High at index {i}: {ph_list[i]:.6f}, BBW={bbw_list[i]:.6f}")
            break

    for i in range(len(closes)):
        if pl_list[i] is not None:
            print(f"첫 Pivot Low at index {i}: {pl_list[i]:.6f}, BBW={bbw_list[i]:.6f}")
            break


if __name__ == "__main__":
    main()
