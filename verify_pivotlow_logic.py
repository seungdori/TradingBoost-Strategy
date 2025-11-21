#!/usr/bin/env python3
"""
PineScript ta.pivotlow 동작 검증

PineScript: ta.pivotlow(source, leftbars, rightbars)
- leftbars 이전의 바를 pivot 후보로 설정
- 그 바의 좌측 leftbars개와 우측 rightbars개를 비교
- 후보가 가장 작으면 그 값을 반환, 아니면 na

예: ta.pivotlow(bbw, 20, 10)
- 현재 바가 i라면
- i-20 바를 pivot 후보로 봄
- 좌측 비교: i-40 ~ i-21 (20개)
- 우측 비교: i-19 ~ i-10 (10개)  <- 과거 데이터!
- i-20이 가장 작으면 bbw[i-20] 반환
"""

import pandas as pd

def pivotlow_pine_style(series, left_bars, right_bars):
    """
    PineScript ta.pivotlow를 정확히 구현

    인덱스 i에서 호출 시:
    - pivot 후보: series[i - left_bars]
    - 좌측 비교: series[i - left_bars - left_bars] ~ series[i - left_bars - 1]
    - 우측 비교: series[i - left_bars + 1] ~ series[i - left_bars + right_bars]

    pivot이 확정되려면 i >= left_bars + right_bars 필요
    """
    result = [None] * len(series)

    # i는 현재 인덱스 (PineScript의 bar_index)
    for i in range(left_bars + right_bars, len(series)):
        # pivot 후보: i - left_bars
        pivot_idx = i - left_bars
        current = series[pivot_idx]

        # NaN 체크
        if pd.isna(current):
            continue

        # 좌측 비교: pivot_idx - left_bars ~ pivot_idx - 1
        is_pivot = True
        for j in range(pivot_idx - left_bars, pivot_idx):
            if j < 0:
                break
            if pd.isna(series[j]):
                continue
            if series[j] <= current:  # 좌측이 작거나 같으면 pivot 아님
                is_pivot = False
                break

        if not is_pivot:
            continue

        # 우측 비교: pivot_idx + 1 ~ pivot_idx + right_bars
        for j in range(pivot_idx + 1, min(pivot_idx + right_bars + 1, len(series))):
            if pd.isna(series[j]):
                continue
            if series[j] <= current:  # 우측이 작거나 같으면 pivot 아님
                is_pivot = False
                break

        if is_pivot:
            result[i] = current  # i 위치에 pivot 값 저장 (pivot_idx의 값)

    return result


def main():
    # CSV 로드
    csv_path = "/Users/seunghyun/Downloads/OKX_BTCUSDT.P, 15_ba3e6.csv"
    df = pd.read_csv(csv_path)

    # BBW 값 추출
    bbw_values = df['BBW'].tolist()

    # 두 가지 방식으로 pivot 계산
    from shared.indicators._core import pivotlow as pivotlow_python

    pivot_pine = pivotlow_pine_style(bbw_values, 20, 10)
    pivot_python = pivotlow_python(bbw_values, 20, 10)

    # 비교
    print("=" * 100)
    print("PineScript 스타일 vs Python 기존 구현 비교")
    print("=" * 100)
    print()

    differences = []
    for i in range(len(bbw_values)):
        pine_val = pivot_pine[i]
        python_val = pivot_python[i]

        if (pine_val is None) != (python_val is None):
            differences.append({
                'idx': i,
                'pine': pine_val,
                'python': python_val,
                'bbw': bbw_values[i]
            })
        elif pine_val is not None and python_val is not None:
            if abs(pine_val - python_val) > 0.000001:
                differences.append({
                    'idx': i,
                    'pine': pine_val,
                    'python': python_val,
                    'bbw': bbw_values[i]
                })

    print(f"총 {len(differences)}개의 차이점 발견")
    print()

    if differences:
        print("처음 20개 차이점:")
        print(f"{'CSV Index':<12} {'Pine Pivot':<15} {'Python Pivot':<15} {'BBW':<12}")
        print("-" * 100)

        for diff in differences[:20]:
            pine_str = f"{diff['pine']:.6f}" if diff['pine'] is not None else "None"
            python_str = f"{diff['python']:.6f}" if diff['python'] is not None else "None"
            print(f"{diff['idx']:<12} {pine_str:<15} {python_str:<15} {diff['bbw']:<12.6f}")
    else:
        print("✅ 두 구현이 동일합니다!")


if __name__ == "__main__":
    main()
