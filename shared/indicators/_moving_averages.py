"""
Moving Average indicators
"""
import math


def calc_sma(series: list[float], length: int) -> list[float | None]:
    """
    Simple Moving Average - handles NaN values like Pine Script's ta.sma()

    Pine Script's ta.sma() skips NaN values and only averages valid values in the window.
    """
    n = len(series)
    out: list[float | None] = [math.nan]*n
    if length <= 0:
        return out

    for i in range(n):
        # Get window: last 'length' values up to and including index i
        start = max(0, i - length + 1)
        window = series[start:i+1]

        # Filter out NaN values (Pine Script behavior)
        valid_values = [v for v in window if not (math.isnan(v) if isinstance(v, float) else False)]

        if len(valid_values) > 0:
            out[i] = sum(valid_values) / len(valid_values)
        else:
            out[i] = math.nan

    return out


def calc_ema(series, length):
    """Exponential Moving Average"""
    if not series:
        return []
    alpha = 2 / (length + 1.0)
    ema_values = []
    prev = series[0]
    ema_values.append(prev)
    for i in range(1, len(series)):
        curr = series[i] * alpha + prev * (1 - alpha)
        ema_values.append(curr)
        prev = curr
    return ema_values


def calc_rma(series, length):
    """Relative Moving Average (Wilder's smoothing)"""
    if not series:
        return []
    rma_values = []

    # 첫 번째 값은 SMA
    if len(series) >= length:
        first_avg = sum(series[:length]) / length
    else:
        first_avg = sum(series) / len(series)

    rma_values.append(first_avg)

    # 나머지는 Wilder의 방식대로
    alpha = 1.0 / length
    prev = first_avg
    for i in range(length, len(series)):
        curr = alpha * series[i] + (1 - alpha) * prev
        rma_values.append(curr)
        prev = curr

    return rma_values


def calc_t3(series, length=5):
    """
    T3 Moving Average
    """
    if not series:
        return []
    # 여러 번 EMA
    e1 = calc_ema(series, length)
    e2 = calc_ema(e1, length)
    e3 = calc_ema(e2, length)
    e4 = calc_ema(e3, length)
    e5 = calc_ema(e4, length)
    e6 = calc_ema(e5, length)

    out = []
    ab = 0.7
    ac1 = -ab**3
    ac2 = 3*ab**2 + 3*ab**3
    ac3 = -6*ab**2 - 3*ab - 3*ab**3
    ac4 = 1 + 3*ab + ab**3 + 3*ab**2

    for i in range(len(series)):
        if math.isnan(e1[i]) or math.isnan(e2[i]) or math.isnan(e3[i]) or \
           math.isnan(e4[i]) or math.isnan(e5[i]) or math.isnan(e6[i]):
            out.append(math.nan)
        else:
            t3_val = ac1*e6[i] + ac2*e5[i] + ac3*e4[i] + ac4*e3[i]
            out.append(t3_val)
    return out


def calc_vidya(series, smooth_period=9, momentum_source=None):
    """
    Variable Index Dynamic Average (VIDYA)

    PineScript FuncVIDYA 정확한 구현:
    - series: 스무딩 적용할 가격 시리즈 (Pine의 _src)
    - momentum_source: Chande Momentum 계산용 시리즈 (Pine의 close, 기본값은 series와 동일)

    Pine에서 FuncVIDYA는:
    - vidya_price = _src (입력 source로 스무딩)
    - vidya_pricc = close (항상 close로 모멘텀 계산)
    """
    if not series:
        return []

    # momentum_source가 없으면 series 자체를 사용 (기존 동작 유지)
    if momentum_source is None:
        momentum_source = series

    result = []
    # 초깃값
    vidya_prev = series[0]
    result.append(vidya_prev)

    for i in range(1, len(series)):
        # Chande Momentum Oscillator (CMO) 계산 - N=9 고정
        # Pine Script: for k = 1 to 9, diff = close[k] - close[k-1]
        # close[k] = k개 전 바, close[k-1] = k-1개 전 바 (close[0] = 현재)
        sum_up, sum_down = 0.0, 0.0
        for k in range(1, 10):
            if i - k < 0:
                break

            # Pine: close[k] - close[k-1] = (k개 전) - (k-1개 전)
            # Python: momentum_source[i-k] - momentum_source[i-k+1] = (k개 전) - (k-1개 전)
            curr_val = momentum_source[i - k]
            prev_val = momentum_source[i - k + 1]  # 수정: i-k-1 → i-k+1 (Pine의 close[k-1] = k-1개 전)
            diff = curr_val - prev_val

            if diff > 0:
                sum_up += diff
            else:
                sum_down -= diff

        # CMO 값 계산
        chande_momentum = 1.0
        if (sum_up + sum_down) != 0:
            chande_momentum = abs((sum_up - sum_down) / (sum_up + sum_down))

        # VIDYA 계산: series에 적용 (Pine의 vidya_price = _src)
        alpha = 2.0 / (smooth_period + 1.0)
        factor = alpha * chande_momentum
        vidya_val = vidya_prev + factor * (series[i] - vidya_prev)
        result.append(vidya_val)
        vidya_prev = vidya_val

    return result


def calc_jma(series: list[float], length: int = 5, phase: int = 50, power: int = 2) -> list[float | None]:
    """Jurik Moving Average"""
    n = len(series)
    out: list[float | None] = [None]*n
    if n == 0:
        return out

    if phase < -100:
        phase_ratio = 0.5
    elif phase > 100:
        phase_ratio = 2.5
    else:
        phase_ratio = (phase / 100.0) + 1.5

    beta = 0.45*(length-1) / (0.45*(length-1) + 2) if length > 1 else 0
    alpha1 = beta ** power

    e0 = [0.0]*n
    e1 = [0.0]*n
    e2 = [0.0]*n
    jma= [0.0]*n

    for i in range(n):
        src = series[i]
        if i == 0:
            e0[i] = src
            e1[i] = 0.0
            e2[i] = 0.0
            jma[i]= src
            out[i] = src
        else:
            # JMA 내부 상태는 계속 업데이트 (부드러운 초기화)
            e0[i] = (1 - alpha1)*src + alpha1*e0[i-1]
            e1[i] = (src - e0[i])*(1 - beta) + beta*e1[i-1]
            e2[i] = ( e0[i] + phase_ratio*e1[i] - jma[i-1] ) * ((1 - alpha1)**2) \
                     + (alpha1**2)*e2[i-1]
            jma[i] = e2[i] + jma[i-1]

        if i < length:
            # 길이 부족: 단순평균
            out[i] = sum(series[:i+1]) / (i+1)
        else:
            # 정상 구간: JMA 값
            out[i] = jma[i]

    return out


def get_ma(source, ma_type, length=20, phase_jma=50, power_jma=2, momentum_source=None):
    """
    Select and calculate moving average by type

    Args:
        source: 가격 시리즈 (스무딩 적용 대상)
        ma_type: MA 타입 ('SMA', 'EMA', 'VIDYA', 'JMA', 'T3', etc.)
        length: MA 길이
        phase_jma: JMA phase 파라미터
        power_jma: JMA power 파라미터
        momentum_source: VIDYA용 모멘텀 계산 소스 (기본값은 source와 동일)
    """
    if ma_type == 'SMA':
        return calc_sma(source, length)
    elif ma_type == 'EMA':
        return calc_ema(source, length)
    elif ma_type == 'WMA':
        # Weighted Moving Average
        out = []
        sum_w = length*(length+1)/2  # 1+2+...+length
        window = []
        for i in range(len(source)):
            window.append(source[i])
            if len(window) > length:
                window.pop(0)
            if i < length-1:
                out.append(math.nan)
                continue
            wma_val = 0.0
            for w in range(length):
                wma_val += window[w]*(w+1)
            wma_val /= sum_w
            out.append(wma_val)
        return out
    elif ma_type == 'RMA':
        return calc_rma(source, length)
    elif ma_type == "JMA":
        return calc_jma(source, length, phase_jma, power_jma)
    elif ma_type == "T3":
        return calc_t3(source, length)
    elif ma_type == "VIDYA":
        return calc_vidya(source, length, momentum_source=momentum_source)
    else:
        # 기본은 EMA
        return calc_ema(source, length)
