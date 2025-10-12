"""
Incremental indicator calculations for performance optimization
"""
import logging
from typing import Any, Tuple, cast

import numpy as np
import pandas as pd

from GRID.indicators.state import IndicatorState
from shared.indicators import calculate_dm_tr, calculate_tr, compute_mama_fama


def calculate_adx_incremental(df: pd.DataFrame, state: IndicatorState, dilen: int = 28, adxlen: int = 28) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    증분형 ADX 계산 함수입니다.
    이전 계산 상태를 사용하여 새 데이터에 대해서만 ADX를 계산합니다.

    Parameters:
    -----------
    df : pandas.DataFrame
        계산할 OHLCV 데이터프레임
    state : IndicatorState
        이전 계산 상태
    dilen : int
        Directional Index의 기간
    adxlen : int
        ADX의 기간

    Returns:
    --------
    tuple
        (adx, plus_di, minus_di) - 계산된 ADX, +DI, -DI 값 배열
    """
    # 데이터프레임이 비어있으면 초기 상태 반환
    if df.empty:
        return np.array([]), np.array([]), np.array([])

    start_idx = 0

    # 이전 계산 결과가 있는 경우
    if state.adx_last_idx >= 0 and state.adx is not None and state.plus_di is not None and state.minus_di is not None:
        # 마지막으로 계산된 인덱스 다음부터 계산
        start_idx = state.adx_last_idx + 1

        # 이미 모든 데이터가 계산되었으면 현재 상태 반환
        if start_idx >= len(df):
            return state.adx, state.plus_di, state.minus_di

        # lookback 기간만큼 이전 데이터가 필요
        lookback = max(dilen, adxlen) + 10  # 여유를 두고 충분히 가져옴

        # 시작 인덱스 조정 (필요한 과거 데이터 포함)
        calc_start_idx = max(0, start_idx - lookback)

        # 계산에 필요한 데이터만 잘라내기
        calc_df = df.iloc[calc_start_idx:].copy()

        # DM과 TR 계산
        dm_tr = calculate_dm_tr(calc_df, dilen)

        # 기존 상태와 병합하기 위한 오프셋 계산
        offset = len(df) - len(calc_df)

        # 이전 결과와 새 결과를 합침
        adx_full = np.concatenate([state.adx[:offset], dm_tr['adx'].values])
        plus_di_full = np.concatenate([state.plus_di[:offset], dm_tr['plusDM'].values])
        minus_di_full = np.concatenate([state.minus_di[:offset], dm_tr['minusDM'].values])

        return adx_full, plus_di_full, minus_di_full
    else:
        # 첫 계산 또는 상태가 없는 경우 전체 계산
        dm_tr = calculate_dm_tr(df, dilen)

        # ADX 및 DI 값 추출
        adx = dm_tr['adx'].values if 'adx' in dm_tr.columns else np.array([])
        plus_di = dm_tr['plusDM'].values if 'plusDM' in dm_tr.columns else np.array([])
        minus_di = dm_tr['minusDM'].values if 'minusDM' in dm_tr.columns else np.array([])

        return adx, plus_di, minus_di


def atr_incremental(df: pd.DataFrame, state: IndicatorState, length: int = 14) -> np.ndarray:
    """
    증분형 ATR 계산 함수입니다.
    이전 계산 상태를 사용하여 새 데이터에 대해서만 ATR을 계산합니다.

    Parameters:
    -----------
    df : pandas.DataFrame
        계산할 OHLCV 데이터프레임
    state : IndicatorState
        이전 계산 상태
    length : int
        ATR 계산 기간

    Returns:
    --------
    numpy.ndarray
        계산된 ATR 값 배열
    """
    # 데이터프레임이 비어있으면 초기 상태 반환
    if df.empty:
        return np.array([])

    # TR 계산
    df_work = df.copy()
    df_work = calculate_tr(df_work)

    start_idx = 0

    # 이전 계산 결과가 있는 경우
    if state.atr_last_idx >= 0 and state.atr_values is not None and state.prev_atr is not None:
        # 마지막으로 계산된 인덱스 다음부터 계산
        start_idx = state.atr_last_idx + 1

        # 이미 모든 데이터가 계산되었으면 현재 상태 반환
        if start_idx >= len(df):
            return cast(np.ndarray, state.atr_values)

        # 이전 ATR 값 가져오기
        prev_atr = state.prev_atr

        # 계산 결과를 저장할 배열
        atr_values = np.zeros(len(df))

        # 이전 결과 복사
        atr_values[:start_idx] = state.atr_values[:start_idx]

        # 새 데이터에 대해 증분 계산
        for i in range(start_idx, len(df)):
            tr = df_work['tr'].iloc[i]
            if i == 0:
                atr_values[i] = tr
            else:
                atr_values[i] = (prev_atr * (length - 1) + tr) / length
            prev_atr = atr_values[i]

        return atr_values
    else:
        # 첫 계산 또는 상태가 없는 경우
        atr_values = np.zeros(len(df))

        for i in range(len(df)):
            tr = df_work['tr'].iloc[i]
            if i == 0:
                atr_values[i] = tr
            else:
                atr_values[i] = (atr_values[i-1] * (length - 1) + tr) / length

        return atr_values


def compute_mama_fama_incremental(src: Any, state: IndicatorState, length: int = 20,
                                   fast_limit: float = 0.5, slow_limit: float = 0.05) -> Tuple[np.ndarray, np.ndarray]:
    """
    증분형 MAMA/FAMA 계산 함수입니다.
    이전 계산 상태를 사용하여 새 데이터에 대해서만 MAMA/FAMA를 계산합니다.

    Parameters:
    -----------
    src : numpy.ndarray or pandas.Series
        가격 데이터 배열
    state : IndicatorState
        이전 계산 상태
    length : int
        계산 기간
    fast_limit : float
        빠른 적응 속도 제한
    slow_limit : float
        느린 적응 속도 제한

    Returns:
    --------
    tuple
        (mama, fama) - 계산된 MAMA, FAMA 값 배열
    """
    # 데이터가 비어있으면 초기 상태 반환
    if len(src) == 0:
        return np.array([]), np.array([])

    # pandas Series일 경우 값만 추출
    if hasattr(src, 'values'):
        src_values = src.values
    else:
        src_values = np.array(src)

    # 이전 계산 결과가 있는 경우
    if (state.mama_last_idx >= 0 and
            state.mama_values is not None and
            state.fama_values is not None):

        # 마지막으로 계산된 인덱스 다음부터 계산
        start_idx = state.mama_last_idx + 1

        # 이미 모든 데이터가 계산되었으면 현재 상태 반환
        if start_idx >= len(src_values):
            return state.mama_values, state.fama_values

        # 결과를 저장할 배열 초기화
        mama = np.zeros(len(src_values))
        fama = np.zeros(len(src_values))

        # 이전 결과 복사
        if len(state.mama_values) > 0 and start_idx > 0:
            # 배열 크기 체크하여 범위 내에서만 복사
            copy_length = min(start_idx, len(state.mama_values))
            mama[:copy_length] = state.mama_values[:copy_length]
            fama[:copy_length] = state.fama_values[:copy_length]

        # 이전 상태 불러오기
        prev_mama = mama[start_idx-1] if start_idx > 0 and len(mama) > start_idx-1 else src_values[0]
        prev_fama = fama[start_idx-1] if start_idx > 0 and len(fama) > start_idx-1 else src_values[0]

        # MESA 상태 변수 초기화
        prev_period = state.prev_period if state.prev_period != 0 else 0.0
        prev_I2 = state.prev_I2 if state.prev_I2 != 0 else 0.0
        prev_Q2 = state.prev_Q2 if state.prev_Q2 != 0 else 0.0
        prev_Re = state.prev_Re if state.prev_Re != 0 else 0.0
        prev_Im = state.prev_Im if state.prev_Im != 0 else 0.0
        prev_phase = state.prev_phase if state.prev_phase != 0 else 0.0

        # 새 데이터에 대해 계산
        for i in range(start_idx, len(src_values)):
            price = src_values[i]

            # 이동 평균 효율성 비율(ER) 계산
            if i < length:
                er = 0
            else:
                price_diff = np.abs(price - src_values[i-length])
                sum_price_changes = np.sum(np.abs(np.diff(src_values[i-length:i+1])))
                er = price_diff / sum_price_changes if sum_price_changes > 0 else 0

            # 초기화
            smooth = price
            detrender = 0.0
            I1 = 0.0
            Q1 = 0.0

            # MESA 계산
            if i >= 3:
                smooth = (4 * price + 3 * src_values[i-1] + 2 * src_values[i-2] + src_values[i-3]) / 10.0

            # 디트렌더 계산
            if i >= 6:
                detrender = (0.0962 * smooth + 0.5769 * src_values[i-2] -
                            0.5769 * src_values[i-4] - 0.0962 * src_values[i-6])

            # 인페이즈 및 쿼드라튜어 컴포넌트 계산
            if i >= 3:
                # 사이클 주기 계산을 위한 MESA 알고리즘 부분
                mesa_period_mult = 0.075 * prev_period + 0.54

                I1 = detrender
                Q1 = detrender

                # 힐버트 변환 계산
                jI = detrender
                jQ = detrender

                I2 = I1 - jQ
                Q2 = Q1 + jI

                # 스무딩
                I2 = 0.2 * I2 + 0.8 * prev_I2
                Q2 = 0.2 * Q2 + 0.8 * prev_Q2

                # 주기 추정
                Re = I2 * prev_I2 + Q2 * prev_Q2
                Im = I2 * prev_Q2 - Q2 * prev_I2

                # 스무딩
                Re = 0.2 * Re + 0.8 * prev_Re
                Im = 0.2 * Im + 0.8 * prev_Im

                # 주기 계산
                period = prev_period
                if Re != 0 and Im != 0:
                    try:
                        period = 2 * np.pi / np.arctan(Im / Re)
                    except:
                        # 에러 발생 시 이전 주기 유지
                        period = prev_period

                # 주기 제한
                if period > 1.5 * prev_period and prev_period > 0:
                    period = 1.5 * prev_period
                elif period < 0.67 * prev_period and prev_period > 0:
                    period = 0.67 * prev_period
                period = max(min(period, 50), 6)

                # 스무딩
                period = 0.2 * period + 0.8 * prev_period

                # 위상 계산
                phase = prev_phase
                if I1 != 0:
                    try:
                        phase = 180 / np.pi * np.arctan(Q1 / I1)
                    except:
                        # 에러 발생 시 이전 위상 유지
                        phase = prev_phase

                # 위상 변화율 계산
                delta_phase = abs(prev_phase - phase)
                delta_phase = max(delta_phase, 1)

                # 적응 계수 계산
                alpha = er / delta_phase
                alpha = max(alpha, er * 0.1)

                # MAMA/FAMA 계산에 사용할 적응 계수 제한
                phase_rate = (fast_limit - slow_limit) * alpha + slow_limit
                phase_rate = max(min(phase_rate, fast_limit), slow_limit)

                # MAMA/FAMA 업데이트
                mama[i] = phase_rate * price + (1 - phase_rate) * prev_mama
                fama[i] = 0.5 * phase_rate * mama[i] + (1 - 0.5 * phase_rate) * prev_fama

                # 다음 반복을 위한 값 업데이트
                prev_mama = mama[i]
                prev_fama = fama[i]
                prev_period = period
                prev_I2 = I2
                prev_Q2 = Q2
                prev_Re = Re
                prev_Im = Im
                prev_phase = phase
            else:
                # 초기 값 설정
                mama[i] = price
                fama[i] = price
                prev_mama = price
                prev_fama = price

        # 상태 업데이트
        state.prev_phase = prev_phase
        state.prev_I2 = prev_I2
        state.prev_Q2 = prev_Q2
        state.prev_Re = prev_Re
        state.prev_Im = prev_Im
        state.prev_period = prev_period

        # 마지막 계산 인덱스 업데이트
        state.mama_last_idx = len(src_values) - 1

        # 필터링 (선택적)
        try:
            mama_series = pd.Series(mama)
            fama_series = pd.Series(fama)
            mama = mama_series.ewm(span=5, adjust=False).mean().values
            fama = fama_series.ewm(span=5, adjust=False).mean().values
        except Exception as e:
            logging.warning(f"MAMA/FAMA 필터링 오류: {e}")

        return mama, fama
    else:
        # 첫 계산 또는 상태가 없는 경우, 기존 함수 호출
        return compute_mama_fama(src, length)
