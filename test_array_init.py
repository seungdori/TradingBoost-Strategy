#!/usr/bin/env python3
"""
배열 초기화 테스트 - PineScript 방식 vs 기존 방식
"""

import math

# 기존 방식: 빈 배열
old_array = []
for i in range(5):
    if len(old_array) >= 3:
        old_array.pop(0)
    old_array.append(i)
print(f"기존 방식 (빈 배열 시작): {old_array}")  # [2, 3, 4]

# PineScript 방식: nan으로 초기화
new_array = [math.nan] * 3
for i in range(5):
    new_array.pop(0)  # 항상 shift
    new_array.append(i)
print(f"PineScript 방식 (nan 초기화): {new_array}")  # [2, 3, 4]

# 유효한 값만 필터링
valid_new = [v for v in new_array if not math.isnan(v)]
print(f"유효한 값: {valid_new}")  # [2, 3, 4]
