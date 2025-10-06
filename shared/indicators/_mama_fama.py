"""
MAMA/FAMA (MESA Adaptive Moving Average) indicator
"""
import pandas as pd
import numpy as np

# PI 상수 정의
PI = 2 * np.arcsin(1)


def hilbert_transform(src):
    """
    Hilbert Transform을 계산합니다.

    Parameters:
    -----------
    src : np.ndarray
        입력 데이터 배열

    Returns:
    --------
    np.ndarray
        Hilbert Transform 값
    """
    return 0.0962 * src + 0.5769 * np.roll(src, 2) - 0.5769 * np.roll(src, 4) - 0.0962 * np.roll(src, 6)


def compute_component(src, mesa_period_mult):
    """
    MESA 주기 구성요소를 계산합니다.

    Parameters:
    -----------
    src : np.ndarray
        입력 데이터 배열
    mesa_period_mult : float or np.ndarray
        MESA 주기 승수

    Returns:
    --------
    np.ndarray
        계산된 구성요소
    """
    return hilbert_transform(src) * mesa_period_mult


def compute_alpha(src, er, er_ratio, prev_mesa_period, prev_I2, prev_Q2, prev_Re, prev_Im, prev_phase):
    """
    MAMA/FAMA의 Alpha 값을 계산합니다.

    Parameters:
    -----------
    src : np.ndarray
        입력 가격 데이터
    er : float
        Efficiency Ratio
    er_ratio : float
        ER 비율
    prev_mesa_period : np.ndarray
        이전 MESA 주기
    prev_I2 : np.ndarray
        이전 I2 값
    prev_Q2 : np.ndarray
        이전 Q2 값
    prev_Re : np.ndarray
        이전 Real 값
    prev_Im : np.ndarray
        이전 Imaginary 값
    prev_phase : np.ndarray
        이전 Phase 값

    Returns:
    --------
    tuple
        (alpha, beta, mesa_period, I2, Q2, Re, Im, phase)
    """
    smooth = (4 * src + 3 * np.roll(src, 1) + 2 * np.roll(src, 2) + np.roll(src, 3)) / 10
    mesa_period_mult = 0.075 * np.roll(prev_mesa_period, 1) + 0.54
    detrender = compute_component(smooth, mesa_period_mult)

    I1 = np.roll(detrender, 3)
    Q1 = compute_component(detrender, mesa_period_mult)

    jI = compute_component(I1, mesa_period_mult)
    jQ = compute_component(Q1, mesa_period_mult)

    I2 = I1 - jQ
    Q2 = Q1 + jI

    I2 = 0.2 * I2 + 0.8 * np.roll(I2, 1)
    Q2 = 0.2 * Q2 + 0.8 * np.roll(Q2, 1)

    Re = I2 * np.roll(I2, 1) + Q2 * np.roll(Q2, 1)
    Im = I2 * np.roll(Q2, 1) - Q2 * np.roll(I2, 1)

    Re = 0.2 * Re + 0.8 * np.roll(Re, 1)
    Im = 0.2 * Im + 0.8 * np.roll(Im, 1)

    mesa_period = np.zeros_like(src)
    if np.any(Re != 0) and np.any(Im != 0):
        mesa_period = 2 * PI / np.arctan(Im / Re)

    mesa_period = np.where(mesa_period > 1.5 * np.roll(mesa_period, 1),
                           1.5 * np.roll(mesa_period, 1), mesa_period)
    mesa_period = np.where(mesa_period < 0.67 * np.roll(mesa_period, 1),
                           0.67 * np.roll(mesa_period, 1), mesa_period)
    mesa_period = np.clip(mesa_period, 6, 50)
    mesa_period = 0.2 * mesa_period + 0.8 * np.roll(mesa_period, 1)

    phase = np.zeros_like(src)
    if np.any(I1 != 0):
        phase = 180 / PI * np.arctan(Q1 / I1)

    delta_phase = np.roll(phase, 1) - phase
    delta_phase = np.where(delta_phase < 1, 1, delta_phase)

    alpha = er / delta_phase
    alpha = np.where(alpha < er_ratio, er_ratio, alpha)

    return alpha, alpha / 2.0, mesa_period, I2, Q2, Re, Im, phase


def compute_mama_fama(src: pd.Series, length: int = 20) -> tuple[np.ndarray, np.ndarray]:
    """
    MAMA (MESA Adaptive Moving Average)와 FAMA (Following Adaptive Moving Average)를 계산합니다.

    Parameters:
    -----------
    src : pd.Series
        가격 데이터 시리즈
    length : int
        ER(Efficiency Ratio) 계산 기간 (기본값 20)

    Returns:
    --------
    tuple
        (mama, fama) - numpy arrays
    """
    # Initialize variables
    mama = np.zeros_like(src)
    fama = np.zeros_like(src)
    mesa_period = np.zeros_like(src)
    I2 = np.zeros_like(src)
    Q2 = np.zeros_like(src)
    Re = np.zeros_like(src)
    Im = np.zeros_like(src)
    phase = np.zeros_like(src)

    # Calculate MAMA and FAMA
    for i in range(len(src)):
        if i < length:
            # Not enough data to compute ER yet
            er = 0
        else:
            diff_sum = np.sum(np.abs(np.diff(src.iloc[i-length:i+1])))
            if diff_sum == 0:  # Prevent division by zero
                er = 0
            else:
                er = np.abs(src.iloc[i] - src.iloc[i - length]) / np.sum(np.abs(np.diff(src.iloc[i-length:i+1])))

        alpha, beta, mesa_period, I2, Q2, Re, Im, phase = compute_alpha(
            np.array([src.iloc[i]]), er, er * 0.1, mesa_period, I2, Q2, Re, Im, phase
        )
        mama[i] = alpha[0] * src.iloc[i] + (1 - alpha[0]) * (mama[i-1] if i > 0 else src.iloc[i])
        fama[i] = beta[0] * mama[i] + (1 - beta[0]) * (fama[i-1] if i > 0 else mama[i])

    # Compute EMA for MAMA and FAMA using ewm
    # Convert to pandas Series to use ewm
    mama_series = pd.Series(mama)
    fama_series = pd.Series(fama)
    mama = mama_series.ewm(span=5, adjust=False).mean().values
    fama = fama_series.ewm(span=5, adjust=False).mean().values

    return mama, fama


def compute_ema(series: np.ndarray | list[float], length: int) -> np.ndarray:
    """
    EMA (Exponential Moving Average)를 계산합니다 (numpy array 버전).

    Parameters:
    -----------
    series : np.ndarray or array-like
        입력 데이터 배열
    length : int
        EMA 기간

    Returns:
    --------
    np.ndarray
        EMA 값
    """
    ema = np.zeros_like(series)
    alpha = 2 / (length + 1)

    for i in range(len(series)):
        if i == 0:
            ema[i] = series[i]
        else:
            ema[i] = alpha * series[i] + (1 - alpha) * ema[i-1]

    return ema
