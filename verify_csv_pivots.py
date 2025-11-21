#!/usr/bin/env python3
"""
CSV 파일에서 BBW 값들과 pivot을 확인
"""

import pandas as pd
import math

# CSV 로드
csv_path = "/Users/seunghyun/Downloads/OKX_BTCUSDT.P, 15_ba3e6.csv"
df = pd.read_csv(csv_path)

# BBW 컬럼이 있는지 확인
print("컬럼 목록:", df.columns.tolist())
print()

# 처음 20개 행의 BBW 값 확인
print("CSV 처음 20개 캔들:")
print(f"{'Index':<6} {'BBW':<15} {'BB_State':<10}")
print("=" * 35)
for i in range(min(20, len(df))):
    bbw = df.iloc[i]['BBW']
    bb_state = df.iloc[i]['BB_State']
    print(f"{i:<6} {bbw:<15.6f} {bb_state:<10.0f}")
