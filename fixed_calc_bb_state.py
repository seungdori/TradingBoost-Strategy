#!/usr/bin/env python3
"""
수정된 _calc_bb_state 함수 - PineScript와 100% 일치

핵심 수정사항:
1. ph_avg, pl_avg, pl_avg_2nd를 각 캔들마다 동적 계산
2. 배열이 비어있을 때는 현재 캔들의 bbw 값 사용 (PineScript와 동일)
"""

import math
from typing import List, Dict
from shared.indicators._moving_averages import calc_sma
from shared.indicators._bollinger import calc_stddev
from shared.indicators._core import pivothigh, pivotlow


def _calc_bb_state_fixed(candle_data, length_bb=15, mult_bb=1.5, ma_length=100, is_confirmed_only=True):
    """
    BB_State 계산 - PineScript 완전 일치 버전

    주요 변경사항:
    - pivot array를 각 캔들마다 업데이트하면서 avg 계산
    - 배열이 비어있을 때는 현재 캔들의 bbw 값 사용
    """
    closes = [c["close"] for c in candle_data]

    # BBW 1st 계산
    basis_list = calc_sma(closes, length_bb)
    std_list = calc_stddev(closes, length_bb)
    upper_list = []
    lower_list = []
    bbw_list = []
    bbr_list = []

    for i in range(len(closes)):
        basis_val = basis_list[i]
        std_val = std_list[i]
        if basis_val is None or std_val is None or math.isnan(basis_val) or math.isnan(std_val):
            upper_list.append(math.nan)
            lower_list.append(math.nan)
            bbw_list.append(math.nan)
            bbr_list.append(math.nan)
            continue

        up = basis_val + mult_bb * std_val
        lo = basis_val - mult_bb * std_val
        upper_list.append(up)
        lower_list.append(lo)

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

    # Pivot High/Low 계산
    pivot_left = 20
    pivot_right = 10
    ph_list = pivothigh(bbw_list, pivot_left, pivot_right)
    pl_list = pivotlow(bbw_list, pivot_left, pivot_right)

    # BBW 2nd 계산
    length_2nd = 60
    use_bbw_2nd = True
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

    # Pivot Low for BBW_2nd
    pl_2nd_list = pivotlow(bbw_2nd_list, 30, 10)

    # 각 캔들마다 계산할 값들을 저장할 리스트
    array_size = 50
    mult_plph = 0.7

    # bbw_2nd_squeeze 초기값
    bbw_2nd_squeeze_history = []

    # BB_State 계산 - 각 캔들마다 처리
    bb_state_list = []

    # PineScript와 동일하게 고정 크기 배열로 초기화 (nan으로 채움)
    # PineScript: var float[] pl_array = array.new_float(array_size, na)
    ph_array = [math.nan] * array_size
    pl_array = [math.nan] * array_size
    pl_array_2nd = [math.nan] * array_size

    for i in range(len(closes)):
        # 현재 캔들의 값들
        bbw_val = bbw_list[i]
        bbr_val = bbr_list[i]
        ma_val = bbw_ma[i]
        bbw_2nd_val = bbw_2nd_list[i]

        # ===== PineScript ta.pivothigh 동작 구현 =====
        # PineScript: ph = ta.pivothigh(bbw, leftbars=20, rightbars=10)
        # → 현재 바(i)에서 i-leftbars 위치의 pivot을 반환 (leftbars만큼 지연!)
        # → i-20 위치가 pivot이면 그 값, 아니면 na
        # → Python: ph_list[i-20]을 사용 (20개 지연)

        # pivot high (leftbars=20만큼 지연)
        recent_ph = None
        if i >= pivot_left:  # i >= 20
            if ph_list[i - pivot_left] is not None:
                recent_ph = ph_list[i - pivot_left]

        # pivot low (leftbars=20만큼 지연)
        recent_pl = None
        if i >= pivot_left:  # i >= 20
            if pl_list[i - pivot_left] is not None:
                recent_pl = pl_list[i - pivot_left]

        # pivot low 2nd (leftbars=30만큼 지연)
        recent_pl_2nd = None
        if i >= 30:  # pl_2nd는 leftbars=30
            if pl_2nd_list[i - 30] is not None:
                recent_pl_2nd = pl_2nd_list[i - 30]

        # ===== Pivot Array 업데이트 (PineScript 로직) =====
        # PineScript: if bbw > ma and ph > 0: array.shift() → array.push()
        # Python: 항상 pop(0) → append() (shift → push 동작 모방)

        # ph_array: 현재 바에서 bbw > ma이고, 최근 pivot이 있으면 추가
        if ma_val is not None and not math.isnan(ma_val) and not math.isnan(bbw_val):
            if bbw_val > ma_val and recent_ph is not None:
                ph_array.pop(0)  # 항상 shift 실행
                ph_array.append(recent_ph)

        # pl_array: 현재 바에서 bbw < ma이고, 최근 pivot이 있으면 추가
        if ma_val is not None and not math.isnan(ma_val) and not math.isnan(bbw_val):
            if bbw_val < ma_val and recent_pl is not None:
                pl_array.pop(0)  # 항상 shift 실행
                pl_array.append(recent_pl)

        # pl_array_2nd: 현재 바에서 bbw_2nd < 1이고, 최근 pivot이 있으면 추가
        if not math.isnan(bbw_2nd_val) and bbw_2nd_val < 1 and recent_pl_2nd is not None:
            pl_array_2nd.pop(0)  # 항상 shift 실행
            pl_array_2nd.append(recent_pl_2nd)

        # ===== 현재 캔들의 avg 값 계산 (PineScript와 동일) =====
        # PineScript: ph_count = count_not_na(ph_array), ph_sum = array.sum(ph_array)
        # PineScript array.sum()은 na를 제외하고 합계 계산

        # ph_avg: nan을 제외한 값들로 평균 계산
        valid_ph = [v for v in ph_array if not math.isnan(v)]
        if len(valid_ph) > 0:
            ph_avg = sum(valid_ph) / len(valid_ph)
        else:
            ph_avg = max(bbw_val if not math.isnan(bbw_val) else 0, 5)

        # pl_avg: nan을 제외한 값들로 평균 계산
        valid_pl = [v for v in pl_array if not math.isnan(v)]
        if len(valid_pl) > 0:
            pl_avg = sum(valid_pl) / len(valid_pl)
        else:
            pl_avg = min(bbw_val if not math.isnan(bbw_val) else 999, 5)

        # pl_avg_2nd: nan을 제외한 값들로 평균 계산
        valid_pl_2nd = [v for v in pl_array_2nd if not math.isnan(v)]
        if len(valid_pl_2nd) > 0:
            pl_avg_2nd = sum(valid_pl_2nd) / len(valid_pl_2nd)
        else:
            pl_avg_2nd = min(bbw_2nd_val if not math.isnan(bbw_2nd_val) else 999, 5)

        # buzz, squeeze 계산
        buzz = ph_avg * mult_plph
        squeeze = pl_avg * (1 / mult_plph)
        squeeze_2nd = pl_avg_2nd * (1 / mult_plph)

        # ===== bbw_2nd_squeeze 상태 업데이트 =====
        prev_squeeze = bbw_2nd_squeeze_history[-1] if bbw_2nd_squeeze_history else True
        current_squeeze = prev_squeeze

        if not math.isnan(bbw_2nd_val):
            if use_bbw_2nd and bbw_2nd_val > squeeze_2nd:
                current_squeeze = False
            elif use_bbw_2nd and bbw_2nd_val < squeeze_2nd:
                current_squeeze = True

        bbw_2nd_squeeze_history.append(current_squeeze)

        # ===== BB_State 계산 =====
        if i < 1:
            bb_state_list.append(0)
            continue

        prev_bb_state = bb_state_list[i-1]
        is_confirmed = True  # 백테스트 모드: 모든 캔들 확정

        # 기본값: 이전 상태 유지
        new_bb_state = prev_bb_state

        if math.isnan(bbw_val) or math.isnan(bbr_val):
            bb_state_list.append(new_bb_state)
            continue

        # BBW falling/rising 계산
        bbw_falling = False
        bbw_rising = False
        if i >= 2:
            if not math.isnan(bbw_list[i-1]) and not math.isnan(bbw_list[i-2]):
                bbw_falling = (bbw_val < bbw_list[i-1] and bbw_list[i-1] < bbw_list[i-2])
                bbw_rising = (bbw_val > bbw_list[i-1])

        # Pine Script Line 338-342: Crossover 조건
        bbw_prev = bbw_list[i-1] if i > 0 else math.nan
        if not math.isnan(bbw_prev):
            # Crossover: 이전 캔들은 buzz 이하, 현재 캔들은 buzz 초과
            if bbw_prev <= buzz and bbw_val > buzz and is_confirmed:
                if bbr_val > 0.5:
                    new_bb_state = 2
                elif bbr_val < 0.5:
                    new_bb_state = -2

        # Pine Script Line 342-343: Squeeze 조건 (barstate.isconfirmed 없음!)
        if bbw_val < squeeze and current_squeeze:
            new_bb_state = -1

        # Pine Script Line 345-348: BBR 조건
        if new_bb_state == 2 and bbr_val < 0.2 and is_confirmed:
            new_bb_state = -2
        if new_bb_state == -2 and bbr_val > 0.8 and is_confirmed:
            new_bb_state = 2

        # Pine Script Line 351-352: 상태 리셋 조건
        # 조건 A: (BB_State == 2 or BB_State == -2) and bbw_falling → barstate.isconfirmed 없음!
        # 조건 B: (bbw > pl_avg and BB_State == -1 and bbw_rising) and barstate.isconfirmed
        if ((new_bb_state == 2 or new_bb_state == -2) and bbw_falling):
            new_bb_state = 0
        if (bbw_val > pl_avg and new_bb_state == -1 and bbw_rising) and is_confirmed:
            new_bb_state = 0

        bb_state_list.append(new_bb_state)

    return bb_state_list
