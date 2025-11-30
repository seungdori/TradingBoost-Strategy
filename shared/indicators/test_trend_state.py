#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
shared/indicators/test_trend_state.py
Pine Script vs Python trend_state 검증 스크립트

실행: cd TradingBoost-Strategy && python -m shared.indicators.test_trend_state
"""
import csv
import os
from datetime import datetime

from shared.indicators._trend import compute_trend_state


def parse_timestamp(time_str):
    """
    Pine Script CSV의 time 컬럼 파싱
    예: "2025-10-29T19:00:00+09:00" -> Unix timestamp (초)
    """
    # ISO 8601 형식 파싱
    dt = datetime.fromisoformat(time_str)
    return int(dt.timestamp())


def safe_int(val, default=0):
    """NaN이나 빈 값을 안전하게 int로 변환"""
    if val is None or val == '' or val.lower() == 'nan':
        return default
    return int(float(val))


def safe_float(val, default=0.0):
    """NaN이나 빈 값을 안전하게 float로 변환"""
    if val is None or val == '' or val.lower() == 'nan':
        return default
    return float(val)


def load_pine_csv(filepath):
    """Pine Script CSV 데이터 로드"""
    candles = []
    with open(filepath, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # NaN 여부 확인 (Pine Script 미확정 캔들)
            is_nan = row['trend_State'].lower() == 'nan' if row['trend_State'] else True
            candles.append({
                'timestamp': parse_timestamp(row['time']),
                'time_str': row['time'],  # 원본 시간 문자열 보존
                'open': safe_float(row['open']),
                'high': safe_float(row['high']),
                'low': safe_float(row['low']),
                'close': safe_float(row['close']),
                'volume': 0,  # CSV에 볼륨 없음, 기본값 설정
                'pine_trend_state': safe_int(row['trend_State']),
                'pine_bb_state': safe_int(row['BB_State']),
                'pine_bb_state_mtf': safe_int(row['BB_state_MTF']),
                'pine_rsi': safe_float(row['rsi']),
                'pine_bbr': safe_float(row['bbr']),
                'pine_bbw': safe_float(row['bbw']),
                'pine_is_nan': is_nan,  # Pine Script 미확정 캔들 플래그
            })
    return candles


def compare_trend_states(candles, current_timeframe_minutes=15, debug=False, use_pine_bb_state=False):
    """
    Python 계산 결과와 Pine Script 결과 비교

    Args:
        candles: Pine Script CSV에서 로드한 캔들 데이터
        current_timeframe_minutes: 현재 타임프레임 (분)
        debug: 디버그 모드 여부
        use_pine_bb_state: True면 Pine BB_State를 사용해서 trend_state 검증

    Returns:
        mismatches: 불일치 목록
        result: compute_trend_state 결과
    """
    # Pine BB_State 리스트 준비 (use_pine_bb_state 모드용)
    external_bb_state_list = None
    external_bb_state_mtf_list = None

    if use_pine_bb_state:
        print("\n=== Pine BB_State를 사용한 trend_state 검증 모드 ===")
        # Pine BB_State 추출
        external_bb_state_list = [c['pine_bb_state'] for c in candles]
        # Pine BB_State_MTF 추출
        external_bb_state_mtf_list = [c['pine_bb_state_mtf'] for c in candles]

    # Python compute_trend_state 호출
    result = compute_trend_state(
        candles,
        use_longer_trend=False,
        use_custom_length=False,
        custom_length=10,
        lookback=30,
        relative_weight=0.5,
        start_at_bar=5,
        candles_higher_tf=None,      # 리샘플링으로 자동 생성
        candles_4h=None,             # 리샘플링으로 자동 생성
        candles_bb_mtf=None,         # 리샘플링으로 자동 생성
        current_timeframe_minutes=current_timeframe_minutes,
        is_confirmed_only=False,     # 백테스트 모드 (모든 캔들 확정)
        external_bb_state_list=external_bb_state_list,
        external_bb_state_mtf_list=external_bb_state_mtf_list,
    )

    mismatches = []
    for i, candle in enumerate(result):
        # Pine Script NaN 캔들은 비교 제외 (미확정 캔들)
        if candle.get('pine_is_nan', False):
            continue

        pine_ts = candle['pine_trend_state']
        python_ts = candle['trend_state']

        if pine_ts != python_ts:
            mismatches.append({
                'row': i + 2,  # CSV 1-indexed + header
                'time': candle.get('time_str', ''),
                'pine': pine_ts,
                'python': python_ts,
                'pine_bb_state': candle.get('pine_bb_state'),
                'pine_bb_state_mtf': candle.get('pine_bb_state_mtf'),
                'python_bb_state': candle.get('BB_State'),
                'python_bb_state_mtf': candle.get('BB_State_MTF'),
                'python_cycle_bull': candle.get('CYCLE_Bull'),
                'python_cycle_bear': candle.get('CYCLE_Bear'),
            })

    return mismatches, result


def print_transition_points(candles, result):
    """trend_state 전환 포인트 출력"""
    print("\n=== Pine Script trend_State 전환 포인트 ===")
    prev_pine = None
    for i, c in enumerate(candles):
        pine_ts = c['pine_trend_state']
        if prev_pine is not None and pine_ts != prev_pine:
            print(f"Row {i+2}: {c['time_str']} | Pine: {prev_pine} → {pine_ts}")
        prev_pine = pine_ts

    print("\n=== Python trend_state 전환 포인트 ===")
    prev_python = None
    for i, c in enumerate(result):
        python_ts = c['trend_state']
        if prev_python is not None and python_ts != prev_python:
            print(f"Row {i+2}: {c.get('time_str', '')} | Python: {prev_python} → {python_ts}")
        prev_python = python_ts


def print_detailed_comparison(candles, result, rows_to_check):
    """특정 행의 상세 비교 출력"""
    print("\n=== 상세 비교 ===")
    for row in rows_to_check:
        idx = row - 2  # CSV row -> 0-indexed
        if 0 <= idx < len(result):
            c = result[idx]
            print(f"\n[Row {row}] {c.get('time_str', '')}")
            print(f"  Pine: trend_State={c['pine_trend_state']}, BB_State={c['pine_bb_state']}, BB_State_MTF={c['pine_bb_state_mtf']}")
            print(f"  Python: trend_state={c['trend_state']}, BB_State={c.get('BB_State')}, BB_State_MTF={c.get('BB_State_MTF')}")
            print(f"  Python: CYCLE_Bull={c.get('CYCLE_Bull')}, CYCLE_Bear={c.get('CYCLE_Bear')}")
            print(f"  Python: CYCLE_Bull_2nd={c.get('CYCLE_Bull_2nd')}, CYCLE_Bear_2nd={c.get('CYCLE_Bear_2nd')}")
            print(f"  Pine RSI={c.get('pine_rsi', 'N/A'):.2f}, BBR={c.get('pine_bbr', 'N/A'):.4f}, BBW={c.get('pine_bbw', 'N/A'):.4f}")


def main():
    # 스크립트 위치 기준으로 CSV 파일 경로 결정
    script_dir = os.path.dirname(os.path.abspath(__file__))
    filepath = os.path.join(script_dir, 'OKX_BTCUSDT.P, 15_02ed8.csv')

    print(f"CSV 파일 경로: {filepath}")

    if not os.path.exists(filepath):
        print(f"❌ 파일을 찾을 수 없습니다: {filepath}")
        return

    # CSV 로드
    candles = load_pine_csv(filepath)
    print(f"✅ 로드된 캔들 수: {len(candles)}")

    # trend_state 비교 (Python BB_State 사용)
    print("\n" + "="*60)
    print("모드 1: Python BB_State 사용")
    print("="*60)
    mismatches, result = compare_trend_states(candles, current_timeframe_minutes=15)

    # trend_state 비교 (Pine BB_State 사용)
    print("\n" + "="*60)
    print("모드 2: Pine BB_State/BB_State_MTF 사용 (CYCLE 로직만 검증)")
    print("="*60)
    mismatches_pine, result_pine = compare_trend_states(
        load_pine_csv(filepath),  # 새로 로드 (원본 데이터)
        current_timeframe_minutes=15,
        use_pine_bb_state=True
    )

    # Pine BB_State 모드 불일치 확인
    pine_mode_mismatches = []
    for i, candle in enumerate(result_pine):
        # Pine Script NaN 캔들은 비교 제외 (미확정 캔들)
        if candle.get('pine_is_nan', False):
            continue

        pine_ts = candle['pine_trend_state']
        python_ts = candle.get('trend_state', 0)
        if pine_ts != python_ts:
            pine_mode_mismatches.append({
                'row': i + 2,
                'time': candle.get('time_str', ''),
                'pine': pine_ts,
                'python': python_ts,
                'CYCLE_Bull': candle.get('CYCLE_Bull'),
                'CYCLE_Bear': candle.get('CYCLE_Bear'),
                'BB_State_MTF': candle.get('BB_State_MTF'),
            })

    print(f"\n📊 Pine BB_State 모드 결과: 총 {len(candles)}개 캔들 중 {len(pine_mode_mismatches)}개 불일치")
    if pine_mode_mismatches:
        print(f"❌ 불일치 목록 (처음 20개):")
        for m in pine_mode_mismatches[:20]:
            print(f"  Row {m['row']}: {m['time']}")
            print(f"    Pine trend_State={m['pine']}, Python trend_state={m['python']}")
            print(f"    CYCLE_Bull={m['CYCLE_Bull']}, CYCLE_Bear={m['CYCLE_Bear']}, BB_State_MTF={m['BB_State_MTF']}")

    # 결과 출력
    print(f"\n📊 비교 결과: 총 {len(candles)}개 캔들 중 {len(mismatches)}개 불일치")

    if mismatches:
        print(f"\n❌ 불일치 목록 (처음 30개):")
        for m in mismatches[:30]:
            print(f"  Row {m['row']}: {m['time']}")
            print(f"    Pine trend_State={m['pine']}, Python trend_state={m['python']}")
            print(f"    Pine BB_State_MTF={m['pine_bb_state_mtf']}, Python BB_State_MTF={m['python_bb_state_mtf']}")
            print(f"    Python CYCLE_Bull={m['python_cycle_bull']}, CYCLE_Bear={m['python_cycle_bear']}")
    else:
        print("✅ 모든 캔들의 trend_state가 일치합니다!")

    # 전환 포인트 비교
    print_transition_points(candles, result)

    # 주요 전환 포인트 상세 비교
    key_rows = [23, 24, 25, 26, 44, 45, 62, 63, 70, 71, 78, 79, 88, 89, 108, 109, 149, 150, 186, 187]
    print_detailed_comparison(candles, result, key_rows)

    return mismatches, result


if __name__ == '__main__':
    main()
