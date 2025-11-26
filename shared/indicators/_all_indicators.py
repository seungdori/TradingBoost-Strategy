"""
Compute all indicators at once
"""
import math

import numpy as np

from ._atr import calc_atr
from ._bollinger import calc_bollinger_bands, calc_stddev
from ._core import crossover, crossunder, dynamic_round, rising, falling, pivothigh, pivotlow, resample_candles
from ._moving_averages import calc_ema, calc_jma, calc_sma, calc_t3, calc_vidya
from ._rsi import calc_rsi
from ._trend import rational_quadratic


def _calc_bb_state_helper(candle_data, bb_length=15, bb_mult=1.5, bb_ma_len=100):
    """
    BB_State 계산 헬퍼 함수 (Pine Script Line 261-352)

    Args:
        candle_data: 캔들 데이터 리스트
        bb_length: Bollinger Band 길이
        bb_mult: Bollinger Band 배수
        bb_ma_len: BBW MA 길이

    Returns:
        bb_state_list: BB_State 값 리스트
    """
    closes = [c["close"] for c in candle_data]

    # BBW 1st (length=15, mult=1.5)
    basis_list = calc_sma(closes, bb_length)
    stdev_list = calc_stddev(closes, bb_length)
    bbw_list = []
    bbr_list = []  # BBR (Bollinger Band Ratio)

    for i in range(len(closes)):
        basis_val = basis_list[i]
        stdev_val = stdev_list[i]
        if basis_val is None or stdev_val is None or math.isnan(basis_val) or math.isnan(stdev_val):
            bbw_list.append(math.nan)
            bbr_list.append(math.nan)
        else:
            upper = basis_val + bb_mult * stdev_val
            lower = basis_val - bb_mult * stdev_val

            # BBW = (upper - lower) * 10 / basis
            if basis_val != 0:
                bbw_list.append((upper - lower) * 10.0 / basis_val)
            else:
                bbw_list.append(math.nan)

            # BBR = (close - lower) / (upper - lower)
            if (upper - lower) != 0:
                bbr_list.append((closes[i] - lower) / (upper - lower))
            else:
                bbr_list.append(math.nan)

    # BBW MA (len_ma=100)
    bbw_ma = calc_sma(bbw_list, bb_ma_len)

    # Pivot High/Low 계산 (pivot_left=20, right=10)
    pivot_left = 20
    pivot_right = 10
    ph_list = pivothigh(bbw_list, pivot_left, pivot_right)
    pl_list = pivotlow(bbw_list, pivot_left, pivot_right)

    # Pine Script의 var 동작 모방: 각 바마다 동적으로 ph_array, pl_array 업데이트
    array_size = 50
    mult_plph = 0.7

    # 각 바마다의 ph_avg, pl_avg, buzz, squeeze를 저장할 리스트
    ph_avg_list = [math.nan] * len(closes)
    pl_avg_list = [math.nan] * len(closes)
    buzz_list = [math.nan] * len(closes)
    squeeze_list = [math.nan] * len(closes)

    # var 변수 초기화 (Pine Script의 var 동작)
    ph_array = []
    pl_array = []

    # Pine Script lines 283-294: 각 바마다 pivot 수집 및 평균 계산
    for i in range(len(closes)):
        bbw_val = bbw_list[i]
        ma_val = bbw_ma[i]

        # pivot 수집 (Pine Script lines 283-288)
        if not (ma_val is None or math.isnan(ma_val) or math.isnan(bbw_val)):
            # bbw > ma일 때만 pivot high 수집
            if bbw_val > ma_val and ph_list[i] is not None and ph_list[i] > 0:
                ph_array.append(ph_list[i])
                if len(ph_array) > array_size:
                    ph_array.pop(0)

            # bbw < ma일 때만 pivot low 수집
            if bbw_val < ma_val and pl_list[i] is not None and pl_list[i] > 0:
                pl_array.append(pl_list[i])
                if len(pl_array) > array_size:
                    pl_array.pop(0)

        # 현재 바의 ph_avg, pl_avg 계산 (Pine Script lines 289-294)
        if len(ph_array) > 0:
            ph_avg_list[i] = sum(ph_array) / len(ph_array)
        else:
            # 기본값: max(현재 바의 bbw, 5) - Pine Script: math.max(bbw, 5)
            ph_avg_list[i] = max(bbw_val, 5) if not math.isnan(bbw_val) else 5

        if len(pl_array) > 0:
            pl_avg_list[i] = sum(pl_array) / len(pl_array)
        else:
            # 기본값: min(현재 바의 bbw, 5) - Pine Script: math.min(bbw, 5)
            pl_avg_list[i] = min(bbw_val, 5) if not math.isnan(bbw_val) else 5

        # 현재 바의 buzz, squeeze 계산 (Pine Script lines 322-323)
        buzz_list[i] = ph_avg_list[i] * mult_plph
        squeeze_list[i] = pl_avg_list[i] * (1 / mult_plph)

    # BBW 2nd (length_2nd=60, mult=1.5)
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
            upper_2nd = basis_val + bb_mult * stdev_val
            lower_2nd = basis_val - bb_mult * stdev_val
            if basis_val != 0:
                bbw_2nd_list.append((upper_2nd - lower_2nd) * 10.0 / basis_val)
            else:
                bbw_2nd_list.append(math.nan)

    # BBW_2nd MA
    bbw_2nd_ma = calc_sma(bbw_2nd_list, bb_ma_len)

    # Pivot Low for BBW_2nd (pivot_left=30, right=10)
    pl_2nd_list = pivotlow(bbw_2nd_list, 30, 10)

    # 각 바마다의 pl_avg_2nd, squeeze_2nd를 저장할 리스트
    pl_avg_2nd_list = [math.nan] * len(closes)
    squeeze_2nd_list = [math.nan] * len(closes)

    # var 변수 초기화 (Pine Script의 var 동작)
    pl_array_2nd = []

    # Pine Script lines 311-320: 각 바마다 pivot 수집 및 평균 계산
    for i in range(len(closes)):
        bbw_2nd_val = bbw_2nd_list[i]

        # pivot low 수집 (Pine Script lines 311-313)
        if not math.isnan(bbw_2nd_val) and bbw_2nd_val < 1 and pl_2nd_list[i] is not None and pl_2nd_list[i] > 0:
            pl_array_2nd.append(pl_2nd_list[i])
            if len(pl_array_2nd) > array_size:
                pl_array_2nd.pop(0)

        # 현재 바의 pl_avg_2nd 계산 (Pine Script lines 315-319)
        if len(pl_array_2nd) > 0:
            pl_avg_2nd_list[i] = sum(pl_array_2nd) / len(pl_array_2nd)
        else:
            # 기본값: min(현재 바의 bbw_2nd, 5) - Pine Script: math.min(bbw_2nd, 5)
            pl_avg_2nd_list[i] = min(bbw_2nd_val, 5) if not math.isnan(bbw_2nd_val) else 5

        # 현재 바의 squeeze_2nd 계산 (Pine Script line 325)
        squeeze_2nd_list[i] = pl_avg_2nd_list[i] * (1 / mult_plph)

    # bbw_2nd_squeeze 상태 (var bool, lines 329-334)
    bbw_2nd_squeeze = True
    bbw_2nd_squeeze_history = [True] * len(closes)

    for i in range(len(closes)):
        bbw_2nd_val = bbw_2nd_list[i]
        squeeze_2nd = squeeze_2nd_list[i]  # 동적 squeeze_2nd 사용
        if not math.isnan(bbw_2nd_val) and not math.isnan(squeeze_2nd):
            if use_bbw_2nd and bbw_2nd_val > squeeze_2nd:
                bbw_2nd_squeeze = False
            if use_bbw_2nd and bbw_2nd_val < squeeze_2nd:
                bbw_2nd_squeeze = True
        bbw_2nd_squeeze_history[i] = bbw_2nd_squeeze

    # BB_State 계산 (Pine Script lines 337-352)
    bb_state_list = [0] * len(closes)

    for i in range(len(closes)):
        if i < 1:
            bb_state_list[i] = 0
            continue

        bbw_val = bbw_list[i]
        bbr_val = bbr_list[i]
        prev_bb_state = bb_state_list[i-1]

        # 현재 바의 동적 임계값 사용
        buzz = buzz_list[i]
        squeeze = squeeze_list[i]
        pl_avg = pl_avg_list[i]

        if math.isnan(bbw_val) or math.isnan(bbr_val) or math.isnan(buzz) or math.isnan(squeeze):
            bb_state_list[i] = prev_bb_state
            continue

        # 기본적으로 이전 상태 유지
        current_state = prev_bb_state

        # Line 338-341: crossover(bbw, buzz)
        if crossover(bbw_list, buzz_list, i):
            if bbr_val > 0.5:
                current_state = 2
            else:
                current_state = -2

        # Line 342-343: bbw < squeeze
        if bbw_val < squeeze and bbw_2nd_squeeze_history[i]:
            current_state = -1

        # Line 345-348: 상태 전환
        if current_state == 2 and bbr_val < 0.2:
            current_state = -2
        if current_state == -2 and bbr_val > 0.8:
            current_state = 2

        # Line 351-352: falling/rising으로 리셋
        if ((current_state == 2 or current_state == -2) and falling(bbw_list, i, 3)):
            current_state = 0
        if (bbw_val > pl_avg and current_state == -1 and rising(bbw_list, i, 1)):
            current_state = 0

        bb_state_list[i] = current_state

    return bb_state_list


def compute_all_indicators(candles, rsi_period=14, atr_period=14,
                           # Trend State 파라미터
                           use_longer_trend=False,
                           use_custom_length=False,
                           custom_length=10,
                           rq_lookback=30,
                           rq_rel_weight=0.5,
                           rq_start_bar=5,
                           bb_length=15,
                           bb_mult=1.5,
                           bb_ma_len=100,
                           # MTF (Multi-Timeframe) 파라미터
                           candles_higher_tf=None,        # CYCLE용 MTF 데이터 (res_)
                           candles_4h=None,               # CYCLE_2nd용 MTF 데이터 (240분)
                           candles_bb_mtf=None,           # BB_State용 MTF 데이터 (bb_mtf)
                           current_timeframe_minutes=None, # 현재 타임프레임 (분), 리샘플링용
                           ):
    """
    candles: [{timestamp, open, high, low, close, volume}, ... ] (과거->현재)
      기존: SMA, JMA, RSI, Bollinger Bands, ATR 저장
      + Trend State( CYCLE_Bull, CYCLE_Bear, BBW 관련, trend_state )도 추가

    Pine Script의 request.security() (f_security) 동작을 구현:
    - candles_higher_tf: CYCLE_Bull/Bear 계산용 (현재 TF에 따라 15m/30m/60m/480m)
    - candles_4h: CYCLE_Bull_2nd/Bear_2nd 계산용 (항상 240분)
    - candles_bb_mtf: BB_State_MTF 계산용 (현재 TF에 따라 5m/15m/60m)

    MTF 데이터가 제공되지 않으면 current_timeframe_minutes 기반으로 리샘플링.
    """
    closes = [c["close"] for c in candles]

    # =============================================================================
    # MTF (Multi-Timeframe) 데이터 준비
    # =============================================================================
    # Pine Script Line 32: res_ 타임프레임 결정
    res_minutes = None
    if current_timeframe_minutes is not None:
        if current_timeframe_minutes <= 3:
            res_minutes = 15
        elif current_timeframe_minutes <= 30:
            res_minutes = 30
        elif current_timeframe_minutes < 240:
            res_minutes = 60
        else:
            res_minutes = 480

    # Pine Script Line 355: bb_mtf 타임프레임 결정
    bb_mtf_minutes = None
    if current_timeframe_minutes is not None:
        if current_timeframe_minutes <= 3:
            bb_mtf_minutes = 5
        elif current_timeframe_minutes <= 15:
            bb_mtf_minutes = 15
        else:
            bb_mtf_minutes = 60

    # Pine Script Line 212: CYCLE_RES_2nd = '240'
    cycle_2nd_minutes = 240

    # MTF 데이터 준비: 제공되지 않으면 리샘플링
    if candles_higher_tf is None and res_minutes is not None:
        candles_higher_tf = resample_candles(candles, res_minutes)
    elif candles_higher_tf is None:
        candles_higher_tf = candles  # 폴백: 현재 타임프레임 사용

    if candles_4h is None:
        candles_4h = resample_candles(candles, cycle_2nd_minutes)

    if candles_bb_mtf is None and bb_mtf_minutes is not None:
        candles_bb_mtf = resample_candles(candles, bb_mtf_minutes)
    elif candles_bb_mtf is None:
        candles_bb_mtf = candles  # 폴백: 현재 타임프레임 사용

    # 1) SMA
    sma5   = calc_sma(closes, 5)
    sma20  = calc_sma(closes, 20)
    sma50  = calc_sma(closes, 50)
    sma60  = calc_sma(closes, 50)   # 원본 코드 상에서 50 그대로
    sma100 = calc_sma(closes, 100)
    sma200 = calc_sma(closes, 200)

    # 2) JMA
    jma5   = calc_jma(closes, length=5,  phase=50, power=2)
    jma10  = calc_jma(closes, length=10, phase=50, power=2)
    jma20  = calc_jma(closes, length=20, phase=50, power=2)

    # 2-1) EMA
    ema5   = calc_ema(closes, 5)
    ema7   = calc_ema(closes, 7)
    ema14  = calc_ema(closes, 14)
    ema20  = calc_ema(closes, 20)
    ema200 = calc_ema(closes, 200)

    # 3) RSI
    # numpy 배열로 변환하여 RSI 계산
    closes_array = np.array(closes)
    rsi14_array = calc_rsi(closes_array, period=rsi_period)
    rsi14 = rsi14_array.tolist()

    # ATR
    atr14  = calc_atr(candles, length=atr_period)

    # 4) Bollinger Bands(20, mult=2)
    bb_up, bb_mid, bb_low = calc_bollinger_bands(closes, length=20, mult=2.0)

    # ---------------------------------------------------------
    # Trend State 추가 로직
    # ---------------------------------------------------------
    # (A) MA lengths 설정
    CYCLE_TYPE = "JMA"
    lenF, lenM, lenS = 5, 10, 20
    if use_longer_trend:
        lenF, lenM, lenS = 20, 40, 120
        CYCLE_TYPE = "T3"

    if use_custom_length:
        lenF = max(custom_length+1, 1)
        lenM = round(custom_length * 2.6)
        lenS = round(custom_length * 4.8)
        CYCLE_TYPE = "T3"

    # (B) 1st Cycle MA - Pine Script Line 197-204: MTF (res_) 데이터로 계산
    closes_htf = [c["close"] for c in candles_higher_tf]
    if CYCLE_TYPE == "T3":
        MA1_ = calc_t3(closes_htf, lenF)
        MA2_ = calc_t3(closes_htf, lenM)
        MA3_ = calc_t3(closes_htf, lenS)
    else:
        # 기본 JMA
        MA1_ = calc_jma(closes_htf, length=lenF, phase=50, power=2)
        MA2_ = calc_jma(closes_htf, length=lenM, phase=50, power=2)
        MA3_ = calc_jma(closes_htf, length=lenS, phase=50, power=2)

    # rationalQuadratic 보정
    MA1_adj = rational_quadratic(MA1_, lookback=rq_lookback, relative_weight=rq_rel_weight, start_at_bar=rq_start_bar)
    MA2_adj = rational_quadratic(MA2_, lookback=rq_lookback, relative_weight=rq_rel_weight, start_at_bar=rq_start_bar)
    MA3_adj = rational_quadratic(MA3_, lookback=rq_lookback, relative_weight=rq_rel_weight, start_at_bar=rq_start_bar)

    # (C) 2nd Cycle (VIDYA 고정) - Pine Script Line 213-225: 4시간 MTF 데이터로 계산
    # 간단히 3,9,21
    lenF2, lenM2, lenS2 = 3, 9, 21
    closes_4h = [c["close"] for c in candles_4h]
    MA1_2nd = calc_vidya(closes_4h, lenF2)
    MA2_2nd = calc_vidya(closes_4h, lenM2)
    MA3_2nd = calc_vidya(closes_4h, lenS2)

    # CYCLE_Bull, CYCLE_Bear
    cycle_bull_list = []
    cycle_bear_list = []
    for i in range(len(closes)):
        m1, m2, m3 = MA1_adj[i], MA2_adj[i], MA3_adj[i]
        if any(map(math.isnan, [m1, m2, m3])):
            cycle_bull_list.append(False)
            cycle_bear_list.append(False)
            continue
        is_bull = ((m1 > m2 and m2 > m3) or (m2 > m1 and m1 > m3))
        is_bear = (m3 > m2 and m2 > m1)
        cycle_bull_list.append(is_bull)
        cycle_bear_list.append(is_bear)

    # 2nd cycle
    cycle_bull2_list = []
    cycle_bear2_list = []
    for i in range(len(closes)):
        m1_, m2_, m3_ = MA1_2nd[i], MA2_2nd[i], MA3_2nd[i]
        if any(map(math.isnan, [m1_, m2_, m3_])):
            cycle_bull2_list.append(False)
            cycle_bear2_list.append(False)
            continue
        # 원본: (m1_2nd > m3_2nd > m2_2nd) or ... 등등
        is_bull2 = ((m1_ > m3_ > m2_) or
                    (m1_ > m2_ > m3_) or
                    (m2_ > m1_ > m3_))
        is_bear2 = ((m3_ > m2_ > m1_) or
                    (m2_ > m3_ > m1_) or
                    (m3_ > m1_ > m2_))
        cycle_bull2_list.append(is_bull2)
        cycle_bear2_list.append(is_bear2)

    # use_longer_trend => CYCLE_Bull = bull & bull2, etc.
    final_bull_list = []
    final_bear_list = []
    for i in range(len(closes)):
        bull = cycle_bull_list[i]
        bear = cycle_bear_list[i]
        bull2 = cycle_bull2_list[i]
        bear2 = cycle_bear2_list[i]
        if use_longer_trend:
            bull = bull and bull2
            bear = bear and bear2
        final_bull_list.append(bull)
        final_bear_list.append(bear)

    # (D) BBW & BB_State - Pine Script 원본 로직 정확히 구현
    # Pine Script lines 261-352

    # Pine Script Line 261-352: BB_State 계산 (현재 타임프레임)
    # - 참고용으로 계산하지만, trend_state에서는 사용 안 함
    bb_state_list = _calc_bb_state_helper(candles, bb_length=bb_length, bb_mult=bb_mult, bb_ma_len=bb_ma_len)

    # Pine Script Line 358: BB_State_MTF = f_security(..., bb_mtf, BB_State)
    # - trend_state 계산에 실제로 사용되는 MTF BB_State
    bb_state_mtf_list = _calc_bb_state_helper(candles_bb_mtf, bb_length=bb_length, bb_mult=bb_mult, bb_ma_len=bb_ma_len)

    # (E) Trend State (Pine Script Line 364-374)
    # trend_state = 2 / -2 / 0 (PineScript 원본 로직과 동일하게 상태 유지)
    # Bull & BB_State_MTF=2 => trend_state=2
    # Bear & BB_State_MTF=-2 => trend_state=-2
    # 상태 유지 로직 추가
    trend_state_list = [0]*len(closes)
    for i in range(len(closes)):
        bull = final_bull_list[i]
        bear = final_bear_list[i]
        # Pine Script Line 358, 364, 370: BB_State_MTF 사용 (현재 TF의 BB_State 아님!)
        bb_st_mtf = bb_state_mtf_list[i]

        # 이전 상태 가져오기 (PineScript의 var 동작 모방)
        prev_state = trend_state_list[i-1] if i > 0 else 0

        # Bull 조건 (PineScript Line 364-365)
        # if CYCLE_Bull and (use_longer_trend ? true : BB_State_MTF == 2)
        if bull and (use_longer_trend or bb_st_mtf == 2):
            trend_state_list[i] = 2
        # Bull 종료 조건 (PineScript Line 367-368)
        # if trend_state == 2 and not CYCLE_Bull
        elif prev_state == 2 and not bull:
            trend_state_list[i] = 0
        # Bear 조건 (PineScript Line 370-371)
        # if CYCLE_Bear and (use_longer_trend ? true : BB_State_MTF == -2)
        elif bear and (use_longer_trend or bb_st_mtf == -2):
            trend_state_list[i] = -2
        # Bear 종료 조건 (PineScript Line 373-374)
        # if trend_state == -2 and not CYCLE_Bear
        elif prev_state == -2 and not bear:
            trend_state_list[i] = 0
        # 상태 유지 (PineScript의 var 동작)
        else:
            trend_state_list[i] = prev_state

    # ---------------------------------------------------------
    # 결과를 각 candle에 저장
    # ---------------------------------------------------------
    for i in range(len(candles)):
        # 기존 인디케이터
        candles[i]["sma5"]   = dynamic_round(sma5[i])
        candles[i]["sma20"]  = dynamic_round(sma20[i])
        candles[i]["sma50"]  = dynamic_round(sma50[i])
        candles[i]["sma60"]  = dynamic_round(sma60[i])
        candles[i]["sma100"] = dynamic_round(sma100[i])
        candles[i]["sma200"] = dynamic_round(sma200[i])

        candles[i]["jma5"]   = dynamic_round(jma5[i])
        candles[i]["jma10"]  = dynamic_round(jma10[i])
        candles[i]["jma20"]  = dynamic_round(jma20[i])

        candles[i]["ema5"]   = dynamic_round(ema5[i])
        candles[i]["ema7"]   = dynamic_round(ema7[i])
        candles[i]["ema14"]  = dynamic_round(ema14[i])
        candles[i]["ema20"]  = dynamic_round(ema20[i])
        candles[i]["ema200"] = dynamic_round(ema200[i])

        candles[i]["rsi"]    = dynamic_round(rsi14[i])

        candles[i]["bb_upper"]   = dynamic_round(bb_up[i]) if bb_up[i] is not None else None
        candles[i]["bb_middle"]  = dynamic_round(bb_mid[i]) if bb_mid[i] is not None else None
        candles[i]["bb_lower"]   = dynamic_round(bb_low[i]) if bb_low[i] is not None else None

        candles[i]["atr14"]  = dynamic_round(atr14[i]) if atr14[i] is not None else None

        # Trend State 필드들
        candles[i]["CYCLE_Bull"] = final_bull_list[i]
        candles[i]["CYCLE_Bear"] = final_bear_list[i]
        candles[i]["BB_State"]   = bb_state_list[i]
        candles[i]["trend_state"] = trend_state_list[i]

    return candles


def add_auto_trend_state_to_candles(
    candles,
    auto_trend_candles,
    current_timeframe_minutes,
    rq_lookback=30,
    rq_rel_weight=0.5,
    rq_start_bar=5,
    bb_length=15,
    bb_mult=1.5,
    bb_ma_len=100,
):
    """
    각 타임프레임의 캔들에 auto_trend_state 필드를 추가합니다.

    Pine Script의 '자동' 로직을 구현:
    - 차트 타임프레임에 따라 자동으로 결정된 트렌드 타임프레임의 캔들 데이터로 trend_state 계산
    - 계산된 trend_state를 auto_trend_state 필드로 저장

    Args:
        candles: 현재 타임프레임의 캔들 데이터 (auto_trend_state를 추가할 대상)
        auto_trend_candles: 자동 결정된 트렌드 타임프레임의 캔들 데이터
        current_timeframe_minutes: 현재 타임프레임 (분 단위)
        rq_lookback: Rational Quadratic lookback
        rq_rel_weight: Rational Quadratic relative weight
        rq_start_bar: Rational Quadratic start bar
        bb_length: Bollinger Band 길이
        bb_mult: Bollinger Band 배수
        bb_ma_len: BBW MA 길이

    Returns:
        candles: auto_trend_state 필드가 추가된 캔들 데이터
    """
    from ._trend import compute_trend_state

    if not auto_trend_candles or len(auto_trend_candles) < 30:
        # 충분한 데이터가 없으면 auto_trend_state를 0으로 설정
        for i in range(len(candles)):
            candles[i]["auto_trend_state"] = 0
        return candles

    # 자동 트렌드 타임프레임의 캔들로 trend_state 계산
    # use_longer_trend=False (Pine Script의 자동 로직에서는 일반적으로 False)
    trend_result = compute_trend_state(
        auto_trend_candles,
        use_longer_trend=False,
        use_custom_length=False,
        custom_length=10,
        lookback=rq_lookback,
        relative_weight=rq_rel_weight,
        start_at_bar=rq_start_bar,
        candles_higher_tf=None,  # 자동 모드에서는 추가 MTF 사용 안 함
        candles_4h=None,
        candles_bb_mtf=None,
        current_timeframe_minutes=None,  # 리샘플링 불필요
        is_confirmed_only=False,
    )

    # trend_result에서 trend_state 추출 (trend_result는 candles 리스트)
    auto_trend_state_list = [c["trend_state"] for c in trend_result]

    # 현재 타임프레임 캔들에 auto_trend_state 매핑
    # Forward-fill 로직: 상위 타임프레임의 값을 하위 타임프레임에 매핑
    auto_trend_idx = 0
    for i in range(len(candles)):
        candle_ts = candles[i]["timestamp"]

        # 현재 캔들의 타임스탬프에 해당하는 auto_trend_candles의 인덱스 찾기
        while (auto_trend_idx < len(auto_trend_candles) - 1 and
               auto_trend_candles[auto_trend_idx + 1]["timestamp"] <= candle_ts):
            auto_trend_idx += 1

        # auto_trend_state 값 할당
        if auto_trend_idx < len(auto_trend_state_list):
            candles[i]["auto_trend_state"] = auto_trend_state_list[auto_trend_idx]
        else:
            candles[i]["auto_trend_state"] = 0

    return candles
