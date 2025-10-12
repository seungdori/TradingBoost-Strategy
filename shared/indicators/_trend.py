"""
Trend analysis indicators
"""
import math

from ._bollinger import calc_stddev
from ._core import crossover, crossunder
from ._moving_averages import calc_sma, get_ma


def rational_quadratic(series, lookback=30, relative_weight=0.5, start_at_bar=5):
    """
    PineScript rationalQuadratic()를 간단히 모방
    """
    N = len(series)
    out = []
    for i in range(N):
        w_sum = 0.0
        val_sum = 0.0
        # 예: i부터 최대 lookback까지 과거를 본다고 가정
        for lag in range(lookback):
            idx_ = i - lag
            if idx_ < start_at_bar or idx_ < 0:
                break
            y = series[idx_]
            # (1 + (lag^2 / (...)))^(-relative_weight)
            w = (1.0 + (lag**2) / ((lookback**2)*2*relative_weight))**(-relative_weight)
            w_sum += w
            val_sum += y*w
        if w_sum == 0:
            out.append(series[i])
        else:
            out.append(val_sum/w_sum)
    return out


def compute_trend_state(
    candles,
    use_longer_trend=False,
    use_custom_length=False,
    custom_length=10,
    lookback=30,
    relative_weight=0.5,
    start_at_bar=5,
):
    """
    TradingView PineScript에서의 CYCLE_Bull/Bear, BBW, extreme_state 등을
    단일 타임프레임 기준으로만 '유사'하게 구현한 예시.
    """
    closes = [c["close"] for c in candles]

    ##################################################
    # 1) 파라미터 세팅 (원본 코드 참조)
    ##################################################
    # 기본 빠른중간느린 길이
    lenF, lenM, lenS = 5, 10, 20
    CYCLE_TYPE = "JMA"

    if use_longer_trend:
        # 예: PineScript에서는 res_='D' 로 바꾸고, 길이를 20,40,120 등으로 세팅
        lenF, lenM, lenS = 20, 40, 120
        CYCLE_TYPE = "T3"

    if use_custom_length:
        lenF = max(custom_length+1, 1)
        lenM = round(custom_length*2.6)
        lenS = round(custom_length*4.8)
        CYCLE_TYPE = "T3"

    # 2번째 cycle (VIDYA 고정)
    lenF_2nd, lenM_2nd, lenS_2nd = 3, 9, 21

    ##################################################
    # 2) MA들 계산
    ##################################################
    # MA (Cycle 1)
    MA1_ = get_ma(closes, CYCLE_TYPE, length=lenF, phase_jma=50, power_jma=2)
    MA2_ = get_ma(closes, CYCLE_TYPE, length=lenM, phase_jma=50, power_jma=2)
    MA3_ = get_ma(closes, CYCLE_TYPE, length=lenS, phase_jma=50, power_jma=2)

    # rationalQuadratic 보정 (원본 코드상)
    MA1_adj = rational_quadratic(MA1_, lookback=lookback, relative_weight=relative_weight, start_at_bar=start_at_bar)
    MA2_adj = rational_quadratic(MA2_, lookback=lookback, relative_weight=relative_weight, start_at_bar=start_at_bar)
    MA3_adj = rational_quadratic(MA3_, lookback=lookback, relative_weight=relative_weight, start_at_bar=start_at_bar)

    # MA (Cycle 2, VIDYA)
    MA1_2nd = get_ma(closes, "VIDYA", length=lenF_2nd)
    MA2_2nd = get_ma(closes, "VIDYA", length=lenM_2nd)
    MA3_2nd = get_ma(closes, "VIDYA", length=lenS_2nd)

    ##################################################
    # 3) CYCLE_Bull / CYCLE_Bear (단일 타임프레임)
    ##################################################
    CYCLE_Bull_list = []
    CYCLE_Bear_list = []
    for i in range(len(closes)):
        m1 = MA1_adj[i]
        m2 = MA2_adj[i]
        m3 = MA3_adj[i]
        # 단순 NaN 체크
        if math.isnan(m1) or math.isnan(m2) or math.isnan(m3):
            CYCLE_Bull_list.append(False)
            CYCLE_Bear_list.append(False)
            continue

        # Bull 조건
        is_bull = ((m1 > m2 and m2 > m3) or (m2 > m1 and m1 > m3))
        # Bear 조건
        is_bear = (m3 > m2 and m2 > m1)

        CYCLE_Bull_list.append(is_bull)
        CYCLE_Bear_list.append(is_bear)

    ##################################################
    # 4) CYCLE_Bull_2nd / CYCLE_Bear_2nd
    ##################################################
    CYCLE_Bull_2nd_list = []
    CYCLE_Bear_2nd_list = []
    for i in range(len(closes)):
        m1_2 = MA1_2nd[i]
        m2_2 = MA2_2nd[i]
        m3_2 = MA3_2nd[i]
        if math.isnan(m1_2) or math.isnan(m2_2) or math.isnan(m3_2):
            CYCLE_Bull_2nd_list.append(False)
            CYCLE_Bear_2nd_list.append(False)
            continue

        is_bull_2nd = (
            (m1_2 > m3_2 and m3_2 > m2_2) or
            (m1_2 > m2_2 and m2_2 > m3_2) or
            (m2_2 > m1_2 and m1_2 > m3_2)
        )
        is_bear_2nd = (
            (m3_2 > m2_2 and m2_2 > m1_2) or
            (m2_2 > m3_2 and m3_2 > m1_2) or
            (m3_2 > m1_2 and m1_2 > m2_2)
        )
        CYCLE_Bull_2nd_list.append(is_bull_2nd)
        CYCLE_Bear_2nd_list.append(is_bear_2nd)

    ##################################################
    # 5) use_longer_trend 옵션 적용
    ##################################################
    final_bull = []
    final_bear = []
    for i in range(len(closes)):
        bull = CYCLE_Bull_list[i]
        bear = CYCLE_Bear_list[i]
        bull2 = CYCLE_Bull_2nd_list[i]
        bear2 = CYCLE_Bear_2nd_list[i]
        if use_longer_trend:
            bull = bull and bull2
            bear = bear and bear2
        final_bull.append(bull)
        final_bear.append(bear)

    ##################################################
    # 6) BBW / BB_State 계산
    ##################################################
    length_bb = 15
    mult_bb = 1.5
    ma_length = 100  # BBW를 다시 SMA

    # basis, dev
    basis_list = calc_sma(closes, length_bb)
    std_list = calc_stddev(closes, length_bb)
    upper_list = []
    lower_list = []
    bbw_list = []
    for i in range(len(closes)):
        basis_val = basis_list[i]
        std_val = std_list[i]
        if basis_val is None or std_val is None or math.isnan(basis_val) or math.isnan(std_val):
            upper_list.append(math.nan)
            lower_list.append(math.nan)
            bbw_list.append(math.nan)
            continue
        up = basis_val + mult_bb*std_val
        lo = basis_val - mult_bb*std_val
        upper_list.append(up)
        lower_list.append(lo)
        if basis_val != 0:
            bbw_list.append((up - lo)*10.0 / basis_val)
        else:
            bbw_list.append(math.nan)
    # bbw의 SMA
    bbw_ma = calc_sma(bbw_list, ma_length)

    # BB_State
    bb_state_list = [0]*len(closes)
    mul_plph = 0.7
    for i in range(len(closes)):
        if i<1:
            bb_state_list[i] = 0
            continue

        # 평균 bbw
        ma_val = bbw_ma[i]
        if ma_val is None or math.isnan(ma_val):
            bb_state_list[i] = 0
            continue

        buzz = ma_val * (1.5 * mul_plph)     # 예시
        squeeze = ma_val * (0.5 / mul_plph)  # 예시

        # crossover check
        if crossover(bbw_list, [buzz]*len(closes), i):
            bb_state_list[i] = 2
        elif crossunder(bbw_list, [squeeze]*len(closes), i):
            bb_state_list[i] = -2
        else:
            bb_state_list[i] = bb_state_list[i-1]

    ##################################################
    # 7) Extreme State
    ##################################################
    extreme_list = [0]*len(closes)
    for i in range(len(closes)):
        bull = final_bull[i]
        bear = final_bear[i]
        bb_st = bb_state_list[i]

        if bull and bb_st == 2:
            extreme_list[i] = 2
        elif bear and bb_st == -2:
            extreme_list[i] = -2
        else:
            extreme_list[i] = 0

    ##################################################
    # 계산 결과를 candles에 저장
    ##################################################
    for i in range(len(candles)):
        candles[i]["CYCLE_Bull"] = final_bull[i]
        candles[i]["CYCLE_Bear"] = final_bear[i]
        candles[i]["BB_State"]   = bb_state_list[i]
        candles[i]["trend_state"] = extreme_list[i]

    return candles
