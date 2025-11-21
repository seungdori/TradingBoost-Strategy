#!/usr/bin/env python3
"""
CSV의 BB_State 전환 시점으로 PineScript의 pl_avg 역계산
"""

import pandas as pd

def main():
    csv_path = "/Users/seunghyun/Downloads/OKX_BTCUSDT.P, 15_ba3e6.csv"
    pine_df = pd.read_csv(csv_path)

    # CSV:13 (Redis:1371)에서 Pine BB_State = 0으로 전환
    # 이 시점에 리셋 조건이 충족되었음: bbw > pl_avg and bbw_rising

    print("=" * 100)
    print("Pine Script pl_avg 역계산")
    print("=" * 100)
    print()

    # CSV:10-15 (Redis:1368-1373)
    csv_start_idx = 1358
    mult_plph = 0.7

    print(f"{'CSV':<5} {'Redis':<7} {'BBW':>10} {'Pine BB_State':>14} {'Notes':<50}")
    print("-" * 100)

    for csv_idx in range(10, 16):
        redis_idx = csv_start_idx + csv_idx
        row = pine_df.iloc[csv_idx]
        bbw = row['BBW']
        bb_state = int(row['BB_State'])

        notes = ""
        if csv_idx == 13:  # Redis:1371
            # 이 시점에 리셋 조건 충족: bbw > pl_avg
            # bbw = 0.040815 (Python 계산에서 확인)
            # 리셋 조건: bbw > pl_avg
            # 따라서: pl_avg < 0.040815
            # Python pl_avg = 0.045386
            # Pine pl_avg < 0.040815 (추정)
            notes = "리셋 조건 충족! pl_avg < BBW"

        print(f"{csv_idx:<5} {redis_idx:<7} {bbw:>10.6f} {bb_state:>14} {notes:<50}")

    print()
    print("=" * 100)
    print("분석")
    print("=" * 100)
    print()

    # CSV:13 (Redis:1371)에서 리셋
    bbw_1371 = pine_df.iloc[13]['BBW']
    bbw_1370 = pine_df.iloc[12]['BBW']

    print(f"Redis:1371 (CSV:13):")
    print(f"  BBW: {bbw_1371:.6f}")
    print(f"  BBW_prev: {bbw_1370:.6f}")
    print(f"  bbw_rising: {bbw_1371 > bbw_1370} ({bbw_1371:.6f} > {bbw_1370:.6f})")
    print(f"  Pine BB_State: 0 (리셋됨)")
    print()
    print(f"리셋 조건: bbw > pl_avg and bbw_rising")
    print(f"bbw_rising = True이므로, bbw > pl_avg 조건도 충족되어야 함")
    print(f"따라서: Pine의 pl_avg < {bbw_1371:.6f}")
    print()
    print(f"Python 계산:")
    print(f"  pl_avg = 0.045386")
    print(f"  bbw = 0.040815")
    print(f"  bbw > pl_avg? {0.040815 > 0.045386} (False)")
    print(f"  → Python은 리셋 조건 불만족")
    print()
    print(f"결론:")
    print(f"  Pine의 pl_avg는 0.040815보다 작아야 함")
    print(f"  Python의 pl_avg는 0.045386")
    print(f"  차이: {0.045386 - 0.040815:.6f}")
    print(f"  차이율: {(0.045386 - 0.040815) / 0.040815 * 100:.2f}%")


if __name__ == "__main__":
    main()
