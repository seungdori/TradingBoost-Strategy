"""
Moving Average indicators
"""
import math


def calc_sma(series: list[float], length: int) -> list[float | None]:
    """Simple Moving Average"""
    n = len(series)
    out: list[float | None] = [None]*n
    if length <= 0:
        return out

    running_sum = 0.0
    for i, val in enumerate(series):
        running_sum += val
        if i < length:
            # 아직 length개 미만: (i+1)개 단순평균
            out[i] = running_sum / (i+1)
        else:
            # length개 이상: 일반 SMA
            running_sum -= series[i - length]
            out[i] = running_sum / length
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


def calc_vidya(series, smooth_period=9):
    """
    Variable Index Dynamic Average (VIDYA)
    """
    if not series:
        return []
    result = []
    # 초깃값
    vidya_prev = series[0]
    result.append(vidya_prev)
    for i in range(1, len(series)):
        # RVI 개념으로 N=9 고정(간단화)
        sum_up, sum_down = 0.0, 0.0
        for k in range(1, 10):
            if i - k < 0:
                break
            diff = series[i - k] - series[i - k - 1] if (i - k - 1 >= 0) else 0
            if diff > 0:
                sum_up += diff
            else:
                sum_down -= diff
        chande_momentum = 1.0
        if (sum_up + sum_down) != 0:
            chande_momentum = abs((sum_up - sum_down) / (sum_up + sum_down))

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


def get_ma(source, ma_type, length=20, phase_jma=50, power_jma=2):
    """
    Select and calculate moving average by type
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
        return calc_vidya(source, length)
    else:
        # 기본은 EMA
        return calc_ema(source, length)
