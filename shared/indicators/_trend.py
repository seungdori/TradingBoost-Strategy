"""
Trend analysis indicators
"""
import math

from ._bollinger import calc_stddev
from ._core import crossover, rising, falling, pivothigh, pivotlow, resample_candles
from ._moving_averages import calc_sma, get_ma


def _calc_bb_state(candle_data, length_bb=15, mult_bb=1.5, ma_length=100):
    """
    BB_State 계산 헬퍼 함수 (Pine Script Line 261-352)

    Args:
        candle_data: 캔들 데이터 리스트
        length_bb: Bollinger Band 길이
        mult_bb: Bollinger Band 승수
        ma_length: BBW MA 길이

    Returns:
        bb_state_list: BB_State 값 리스트
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

        # BBW = (upper - lower) * 10 / basis
        if basis_val != 0:
            bbw_list.append((up - lo) * 10.0 / basis_val)
        else:
            bbw_list.append(math.nan)

        # BBR = (close - lower) / (upper - lower)
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

    # Pivot Arrays
    array_size = 50
    ph_array = []
    pl_array = []

    # Pivot 수집
    for i in range(len(closes)):
        bbw_val = bbw_list[i]
        ma_val = bbw_ma[i]

        if ma_val is None or math.isnan(ma_val) or math.isnan(bbw_val):
            continue

        # bbw > ma일 때만 pivot high 수집
        if bbw_val > ma_val and ph_list[i] is not None:
            ph_array.append(ph_list[i])
            if len(ph_array) > array_size:
                ph_array.pop(0)

        # bbw < ma일 때만 pivot low 수집
        if bbw_val < ma_val and pl_list[i] is not None:
            pl_array.append(pl_list[i])
            if len(pl_array) > array_size:
                pl_array.pop(0)

    # ph_avg, pl_avg 계산
    if len(ph_array) > 0:
        ph_avg = sum(ph_array) / len(ph_array)
    else:
        ph_avg = max([b for b in bbw_list if not math.isnan(b)] + [5])

    if len(pl_array) > 0:
        pl_avg = sum(pl_array) / len(pl_array)
    else:
        pl_avg = min([b for b in bbw_list if not math.isnan(b)] + [5])

    # BBW 2nd
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

    # Collect pivot lows for BBW_2nd
    pl_array_2nd = []
    for i in range(len(closes)):
        bbw_2nd_val = bbw_2nd_list[i]
        if not math.isnan(bbw_2nd_val) and bbw_2nd_val < 1 and pl_2nd_list[i] is not None:
            pl_array_2nd.append(pl_2nd_list[i])
            if len(pl_array_2nd) > array_size:
                pl_array_2nd.pop(0)

    # pl_avg_2nd 계산
    if len(pl_array_2nd) > 0:
        pl_avg_2nd = sum(pl_array_2nd) / len(pl_array_2nd)
    else:
        pl_avg_2nd = min([b for b in bbw_2nd_list if not math.isnan(b)] + [5])

    # buzz, squeeze 계산
    mult_plph = 0.7
    buzz = ph_avg * mult_plph
    squeeze = pl_avg * (1 / mult_plph)
    squeeze_2nd = pl_avg_2nd * (1 / mult_plph)

    # bbw_2nd_squeeze 상태
    bbw_2nd_squeeze = True
    bbw_2nd_squeeze_history = [True] * len(closes)

    for i in range(len(closes)):
        bbw_2nd_val = bbw_2nd_list[i]
        if not math.isnan(bbw_2nd_val):
            if use_bbw_2nd and bbw_2nd_val > squeeze_2nd:
                bbw_2nd_squeeze = False
            if use_bbw_2nd and bbw_2nd_val < squeeze_2nd:
                bbw_2nd_squeeze = True
        bbw_2nd_squeeze_history[i] = bbw_2nd_squeeze

    # BB_State 계산
    bb_state_list = [0] * len(closes)

    for i in range(len(closes)):
        if i < 1:
            bb_state_list[i] = 0
            continue

        bbw_val = bbw_list[i]
        bbr_val = bbr_list[i]
        prev_bb_state = bb_state_list[i-1]

        if math.isnan(bbw_val) or math.isnan(bbr_val):
            bb_state_list[i] = prev_bb_state
            continue

        # 기본적으로 이전 상태 유지
        current_state = prev_bb_state

        # crossover(bbw, buzz)
        if crossover(bbw_list, [buzz]*len(closes), i):
            if bbr_val > 0.5:
                current_state = 2
            else:
                current_state = -2

        # bbw < squeeze
        if bbw_val < squeeze and bbw_2nd_squeeze_history[i]:
            current_state = -1

        # 상태 전환
        if current_state == 2 and bbr_val < 0.2:
            current_state = -2
        if current_state == -2 and bbr_val > 0.8:
            current_state = 2

        # falling/rising으로 리셋
        if ((current_state == 2 or current_state == -2) and falling(bbw_list, i, 3)):
            current_state = 0
        if (bbw_val > pl_avg and current_state == -1 and rising(bbw_list, i, 1)):
            current_state = 0

        bb_state_list[i] = current_state

    return bb_state_list


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
    candles_higher_tf=None,      # CYCLE용 MTF 데이터 (res_)
    candles_4h=None,              # CYCLE_2nd용 MTF 데이터 (240분)
    candles_bb_mtf=None,          # BB_State용 MTF 데이터 (bb_mtf)
    current_timeframe_minutes=None,  # 현재 타임프레임 (분), 리샘플링용
):
    """
    TradingView PineScript의 CYCLE_Bull/Bear, BBW, extreme_state 등을
    Multi-Timeframe (MTF) 로직 포함하여 정확하게 구현.

    Pine Script의 request.security() (f_security) 동작을 구현:
    - candles_higher_tf: CYCLE_Bull/Bear 계산용 (현재 TF에 따라 15m/30m/60m/480m)
    - candles_4h: CYCLE_Bull_2nd/Bear_2nd 계산용 (항상 240분)
    - candles_bb_mtf: BB_State_MTF 계산용 (현재 TF에 따라 5m/15m/60m)

    MTF 데이터가 제공되지 않으면 current_timeframe_minutes 기반으로 리샘플링.
    """
    closes = [c["close"] for c in candles]

    ##################################################
    # 0) MTF 타임프레임 결정 및 데이터 준비
    ##################################################
    # Pine Script Line 32: res_ 결정
    # res_ = timeframe.multiplier <= 3 ? '15' : timeframe.multiplier <= 30 ? '30' : timeframe.multiplier < 240 ? '60' : '480'
    if current_timeframe_minutes is not None:
        if current_timeframe_minutes <= 3:
            res_minutes = 15
        elif current_timeframe_minutes <= 30:
            res_minutes = 30
        elif current_timeframe_minutes < 240:
            res_minutes = 60
        else:
            res_minutes = 480
    else:
        res_minutes = None

    # Pine Script Line 355: bb_mtf 결정
    # bb_mtf = timeframe.multiplier <= 3 ? '5' : timeframe.multiplier <= 15 ? '15' : '60'
    if current_timeframe_minutes is not None:
        if current_timeframe_minutes <= 3:
            bb_mtf_minutes = 5
        elif current_timeframe_minutes <= 15:
            bb_mtf_minutes = 15
        else:
            bb_mtf_minutes = 60
    else:
        bb_mtf_minutes = None

    # Pine Script Line 212: CYCLE_RES_2nd = '240' (항상 240분)
    cycle_2nd_minutes = 240

    # MTF 데이터 준비: 제공되지 않으면 리샘플링
    if candles_higher_tf is None and res_minutes is not None:
        candles_higher_tf = resample_candles(candles, res_minutes)

    if candles_4h is None:
        candles_4h = resample_candles(candles, cycle_2nd_minutes)

    if candles_bb_mtf is None and bb_mtf_minutes is not None:
        candles_bb_mtf = resample_candles(candles, bb_mtf_minutes)

    # MTF 데이터가 없으면 현재 타임프레임 사용 (fallback)
    if candles_higher_tf is None:
        candles_higher_tf = candles
    if candles_4h is None:
        candles_4h = candles
    if candles_bb_mtf is None:
        candles_bb_mtf = candles

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
    # 2) MA들 계산 (MTF 데이터 사용)
    ##################################################
    # Pine Script Line 197-204: MA (Cycle 1) - MTF (res_) 데이터로 계산
    # Pine Script Line 232-233: CYCLE_Bull/Bear = f_security(..., res_, ...)
    closes_htf = [c["close"] for c in candles_higher_tf]
    MA1_htf = get_ma(closes_htf, CYCLE_TYPE, length=lenF, phase_jma=50, power_jma=2)
    MA2_htf = get_ma(closes_htf, CYCLE_TYPE, length=lenM, phase_jma=50, power_jma=2)
    MA3_htf = get_ma(closes_htf, CYCLE_TYPE, length=lenS, phase_jma=50, power_jma=2)

    # rationalQuadratic 보정 (Pine Script Line 202-204)
    MA1_adj = rational_quadratic(MA1_htf, lookback=lookback, relative_weight=relative_weight, start_at_bar=start_at_bar)
    MA2_adj = rational_quadratic(MA2_htf, lookback=lookback, relative_weight=relative_weight, start_at_bar=start_at_bar)
    MA3_adj = rational_quadratic(MA3_htf, lookback=lookback, relative_weight=relative_weight, start_at_bar=start_at_bar)

    # Pine Script Line 213-225: MA (Cycle 2, VIDYA) - 4시간 MTF 데이터로 계산
    # Pine Script Line 224-225: CYCLE_Bull_2nd/Bear_2nd = f_security(..., '240', ...)
    closes_4h = [c["close"] for c in candles_4h]
    MA1_2nd = get_ma(closes_4h, "VIDYA", length=lenF_2nd)
    MA2_2nd = get_ma(closes_4h, "VIDYA", length=lenM_2nd)
    MA3_2nd = get_ma(closes_4h, "VIDYA", length=lenS_2nd)

    ##################################################
    # 3) CYCLE_Bull / CYCLE_Bear (MTF - res_)
    ##################################################
    # Pine Script Line 229-233: MTF 데이터로 계산된 CYCLE
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
    # 6) BBW / BB_State - Pine Script 원본 로직 (헬퍼 함수 사용)
    ##################################################
    # Pine Script Line 261-352: BB_State 계산 (현재 타임프레임)
    # - 참고용으로 계산하지만, extreme_state에서는 사용 안 함
    bb_state_list = _calc_bb_state(candles, length_bb=15, mult_bb=1.5, ma_length=100)

    # Pine Script Line 358: BB_State_MTF = f_security(..., bb_mtf, BB_State)
    # - extreme_state 계산에 실제로 사용되는 MTF BB_State
    bb_state_mtf_list = _calc_bb_state(candles_bb_mtf, length_bb=15, mult_bb=1.5, ma_length=100)

    ##################################################
    # 7) Extreme State (Pine Script Line 364-374, MTF 사용)
    ##################################################
    extreme_list = [0]*len(closes)
    for i in range(len(closes)):
        bull = final_bull[i]
        bear = final_bear[i]
        # Pine Script Line 358, 364, 370: BB_State_MTF 사용 (현재 TF의 BB_State 아님!)
        bb_st_mtf = bb_state_mtf_list[i]

        # 이전 상태 가져오기 (PineScript의 var 동작 모방)
        prev_state = extreme_list[i-1] if i > 0 else 0

        # 상승 극단 조건 (Pine Script Line 364-365)
        # if CYCLE_Bull and (use_longer_trend ? true : BB_State_MTF == 2)
        if bull and (use_longer_trend or bb_st_mtf == 2):
            extreme_list[i] = 2
        # 상승 극단 종료 조건 (Pine Script Line 367-368)
        # if extreme_state == 2 and not CYCLE_Bull
        elif prev_state == 2 and not bull:
            extreme_list[i] = 0
        # 하락 극단 조건 (Pine Script Line 370-371)
        # if CYCLE_Bear and (use_longer_trend ? true : BB_State_MTF == -2)
        elif bear and (use_longer_trend or bb_st_mtf == -2):
            extreme_list[i] = -2
        # 하락 극단 종료 조건 (Pine Script Line 373-374)
        # if extreme_state == -2 and not CYCLE_Bear
        elif prev_state == -2 and not bear:
            extreme_list[i] = 0
        # 상태 유지 (PineScript의 var 동작)
        else:
            extreme_list[i] = prev_state

    ##################################################
    # 계산 결과를 candles에 저장
    ##################################################
    for i in range(len(candles)):
        candles[i]["CYCLE_Bull"] = final_bull[i]
        candles[i]["CYCLE_Bear"] = final_bear[i]
        candles[i]["BB_State"]   = bb_state_list[i]
        candles[i]["trend_state"] = extreme_list[i]

    return candles
