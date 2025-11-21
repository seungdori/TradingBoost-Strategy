"""
Pine Script CSV에서 5분봉이 어떻게 구성되는지 분석
"""

import pandas as pd
from datetime import datetime, timezone


def analyze_pine_candle_grouping():
    """Pine CSV 1분봉을 5분봉으로 어떻게 묶는지 분석"""

    print("=" * 100)
    print("Pine Script CSV - 5분봉 구성 분석")
    print("=" * 100)

    # Pine Script CSV 로드
    csv_path = "/Users/seunghyun/Downloads/OKX_BTCUSDT.P, 1_8f411.csv"
    df = pd.read_csv(csv_path)
    df['time'] = pd.to_datetime(df['time'], unit='s', utc=True)

    # 20:35 ~ 21:00 구간 분석 (20:40, 20:45, 20:50, 20:55, 21:00 포함하려면)
    start_time = datetime(2025, 11, 16, 20, 35, 0, tzinfo=timezone.utc)
    end_time = datetime(2025, 11, 16, 21, 0, 0, tzinfo=timezone.utc)

    mask = (df['time'] >= start_time) & (df['time'] <= end_time)
    df_range = df[mask].sort_values('time')

    print(f"\n📊 20:35~21:00 구간의 1분봉 ({len(df_range)}개):")
    print(f"{'Time':<20} {'Open':>10} {'High':>10} {'Low':>10} {'Close':>10} {'BB_MTF':>8}")
    print("-" * 85)

    for idx, row in df_range.iterrows():
        time = str(row['time'])[:19]
        open_price = float(row['open'])
        high = float(row['high'])
        low = float(row['low'])
        close = float(row['close'])
        bb_mtf = int(row['BB_state_MTF'])

        # 5분 경계 표시
        is_boundary = row['time'].minute % 5 == 0
        marker = " ← 5분 경계" if is_boundary else ""

        print(f"{time:<20} {open_price:>10.2f} {high:>10.2f} {low:>10.2f} {close:>10.2f} {bb_mtf:>8}{marker}")

    # 각 5분 경계별로 그룹핑 분석
    print("\n📊 5분 경계별 그룹 분석:")
    boundaries = [
        datetime(2025, 11, 16, 20, 40, 0, tzinfo=timezone.utc),
        datetime(2025, 11, 16, 20, 45, 0, tzinfo=timezone.utc),
        datetime(2025, 11, 16, 20, 50, 0, tzinfo=timezone.utc),
        datetime(2025, 11, 16, 20, 55, 0, tzinfo=timezone.utc),
        datetime(2025, 11, 16, 21, 0, 0, tzinfo=timezone.utc),
    ]

    for boundary in boundaries:
        print(f"\n{'='*50}")
        print(f"5분 경계: {str(boundary)[:19]}")
        print(f"{'='*50}")

        # 시도1: 경계 포함, 5개 (boundary-4 ~ boundary)
        start1 = boundary - pd.Timedelta(minutes=4)
        mask1 = (df['time'] > start1) & (df['time'] <= boundary)
        group1 = df[mask1].sort_values('time')

        print(f"\n시도1: ({str(start1)[:19]} < time <= {str(boundary)[:19]}) - {len(group1)}개")
        if len(group1) > 0:
            for idx, row in group1.iterrows():
                print(f"  {str(row['time'])[:19]} - close: {float(row['close']):>10.2f}")
            print(f"  ➡️ 집계 close: {float(group1.iloc[-1]['close']):>10.2f}")

        # 시도2: 경계 포함, 5개 (boundary-5 < time <= boundary-1 + boundary)
        start2 = boundary - pd.Timedelta(minutes=5)
        end2 = boundary - pd.Timedelta(minutes=1)
        mask2 = ((df['time'] > start2) & (df['time'] <= end2)) | (df['time'] == boundary)
        group2 = df[mask2].sort_values('time')

        print(f"\n시도2: (({str(start2)[:19]} < time <= {str(end2)[:19]}) OR time == boundary) - {len(group2)}개")
        if len(group2) > 0:
            for idx, row in group2.iterrows():
                print(f"  {str(row['time'])[:19]} - close: {float(row['close']):>10.2f}")
            print(f"  ➡️ 집계 close: {float(group2.iloc[-1]['close']):>10.2f}")

        # 시도3: boundary-5 <= time <= boundary
        start3 = boundary - pd.Timedelta(minutes=5)
        mask3 = (df['time'] >= start3) & (df['time'] <= boundary)
        group3 = df[mask3].sort_values('time')

        print(f"\n시도3: ({str(start3)[:19]} <= time <= {str(boundary)[:19]}) - {len(group3)}개")
        if len(group3) > 0:
            for idx, row in group3.iterrows():
                print(f"  {str(row['time'])[:19]} - close: {float(row['close']):>10.2f}")
            print(f"  ➡️ 집계 close: {float(group3.iloc[-1]['close']):>10.2f}")


if __name__ == "__main__":
    analyze_pine_candle_grouping()
