#!/usr/bin/env python3
"""
PineScript와 Python Trend Indicator 결과 비교 검증 스크립트

TradingView CSV 데이터와 Python 구현체의 결과를 비교하여 정확도를 검증합니다.
"""

import pandas as pd
import sys
from datetime import datetime

# Python 구현체 import
from shared.indicators._trend import compute_trend_state


def load_csv_data(csv_path):
    """TradingView CSV 데이터 로드"""
    try:
        df = pd.read_csv(csv_path)
        print(f"✅ CSV 로드 성공: {len(df)} 행")
        print(f"📊 컬럼: {list(df.columns)}")
        print(f"🕐 기간: {df['time'].iloc[0]} ~ {df['time'].iloc[-1]}")
        return df
    except Exception as e:
        print(f"❌ CSV 로드 실패: {e}")
        sys.exit(1)


def prepare_candles(df):
    """DataFrame을 candles 형식으로 변환"""
    candles = []
    for _, row in df.iterrows():
        candles.append({
            "timestamp": pd.to_datetime(row["time"]),
            "open": row["open"],
            "high": row["high"],
            "low": row["low"],
            "close": row["close"],
            "volume": 0.0  # CSV에 volume이 없으므로 0으로 설정
        })
    return candles


def compare_results(df_csv, python_results):
    """CSV와 Python 결과 비교"""
    print("\n" + "="*80)
    print("📊 결과 비교 분석")
    print("="*80)

    # BB_State와 trend_state를 Python 결과에서 추출
    # python_results는 candles 리스트 (각 candle에 BB_State, trend_state 포함)
    bb_states_python = [c.get("BB_State", 0) for c in python_results]
    trend_states_python = [c.get("trend_state", 0) for c in python_results]

    if not bb_states_python or not trend_states_python:
        print("❌ Python 계산 결과가 비어있습니다.")
        return False

    # CSV 데이터 준비
    bb_states_csv = df_csv["BB_State"].values if "BB_State" in df_csv.columns else []
    trend_states_csv = df_csv["trend_state"].values if "trend_state" in df_csv.columns else []

    # 길이 확인
    min_len = min(len(bb_states_csv), len(bb_states_python),
                  len(trend_states_csv), len(trend_states_python))

    print(f"\n📏 데이터 길이:")
    print(f"  - CSV: BB_State={len(bb_states_csv)}, trend_state={len(trend_states_csv)}")
    print(f"  - Python: BB_State={len(bb_states_python)}, trend_state={len(trend_states_python)}")
    print(f"  - 비교 범위: {min_len} 캔들")

    # BB_State 비교
    bb_matches = 0
    bb_mismatches = []

    for i in range(min_len):
        csv_val = bb_states_csv[i]
        py_val = bb_states_python[i]

        if csv_val == py_val:
            bb_matches += 1
        else:
            bb_mismatches.append({
                "index": i,
                "time": df_csv["time"].iloc[i],
                "csv": csv_val,
                "python": py_val
            })

    bb_accuracy = (bb_matches / min_len * 100) if min_len > 0 else 0

    print(f"\n🎯 BB_State 정확도: {bb_accuracy:.2f}% ({bb_matches}/{min_len})")

    if bb_mismatches:
        print(f"⚠️  불일치 발견: {len(bb_mismatches)}개")
        print("\n처음 10개 불일치 샘플:")
        for mismatch in bb_mismatches[:10]:
            print(f"  [{mismatch['index']}] {mismatch['time']}: CSV={mismatch['csv']}, Python={mismatch['python']}")

    # trend_state 비교
    trend_matches = 0
    trend_mismatches = []

    for i in range(min_len):
        csv_val = trend_states_csv[i]
        py_val = trend_states_python[i]

        if csv_val == py_val:
            trend_matches += 1
        else:
            trend_mismatches.append({
                "index": i,
                "time": df_csv["time"].iloc[i],
                "csv": csv_val,
                "python": py_val
            })

    trend_accuracy = (trend_matches / min_len * 100) if min_len > 0 else 0

    print(f"\n🎯 trend_state 정확도: {trend_accuracy:.2f}% ({trend_matches}/{min_len})")

    if trend_mismatches:
        print(f"⚠️  불일치 발견: {len(trend_mismatches)}개")
        print("\n처음 10개 불일치 샘플:")
        for mismatch in trend_mismatches[:10]:
            print(f"  [{mismatch['index']}] {mismatch['time']}: CSV={mismatch['csv']}, Python={mismatch['python']}")

    # 주요 전환점 검증
    print("\n" + "="*80)
    print("🔍 주요 전환점 검증")
    print("="*80)

    # BB_State 전환점 찾기
    print("\n📈 BB_State 전환점 (CSV 기준):")
    for i in range(1, min_len):
        if bb_states_csv[i] != bb_states_csv[i-1]:
            csv_val = bb_states_csv[i]
            py_val = bb_states_python[i]
            match = "✅" if csv_val == py_val else "❌"
            print(f"  {match} [{i}] {df_csv['time'].iloc[i]}: {bb_states_csv[i-1]} → {csv_val} (Python: {py_val})")

    # trend_state 전환점 찾기
    print("\n📈 trend_state 전환점 (CSV 기준):")
    for i in range(1, min_len):
        if trend_states_csv[i] != trend_states_csv[i-1]:
            csv_val = trend_states_csv[i]
            py_val = trend_states_python[i]
            match = "✅" if csv_val == py_val else "❌"
            print(f"  {match} [{i}] {df_csv['time'].iloc[i]}: {trend_states_csv[i-1]} → {csv_val} (Python: {py_val})")

    # 최종 결과
    print("\n" + "="*80)
    print("📊 최종 검증 결과")
    print("="*80)

    if bb_accuracy >= 95 and trend_accuracy >= 95:
        print("✅ 검증 성공! Python 구현이 PineScript와 95% 이상 일치합니다.")
        return True
    elif bb_accuracy >= 90 and trend_accuracy >= 90:
        print("⚠️  부분 성공: 90% 이상 일치하지만 일부 차이가 있습니다.")
        return False
    else:
        print("❌ 검증 실패: 일치도가 90% 미만입니다. 코드 재검토 필요.")
        return False


def main():
    csv_path = "/Users/seunghyun/Downloads/OKX_BTCUSDT.P, 15_ba3e6.csv"

    print("🔍 PineScript vs Python Trend Indicator 검증")
    print("="*80)

    # 1. CSV 데이터 로드
    df_csv = load_csv_data(csv_path)

    # 2. Candles 형식으로 변환
    candles = prepare_candles(df_csv)

    print(f"\n✅ {len(candles)}개 캔들 준비 완료")

    # 3. Python 구현체로 계산
    print("\n🔧 Python Trend Indicator 계산 중...")

    try:
        # 15분 타임프레임 기준 (CSV 데이터가 15m)
        # is_confirmed_only=False: 모든 히스토리 캔들 확정으로 처리
        results = compute_trend_state(
            candles,
            use_longer_trend=False,
            current_timeframe_minutes=15,
            is_confirmed_only=False  # 백테스트 모드
        )

        print("✅ Python 계산 완료")

        # 4. 결과 비교
        success = compare_results(df_csv, results)

        if success:
            print("\n🎉 검증 완료! 모든 수정이 정상적으로 적용되었습니다.")
            sys.exit(0)
        else:
            print("\n⚠️  일부 차이가 발견되었습니다. 추가 디버깅이 필요할 수 있습니다.")
            sys.exit(1)

    except Exception as e:
        print(f"\n❌ Python 계산 중 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
