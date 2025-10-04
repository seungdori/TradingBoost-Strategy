"""
Compute all indicators at once
"""
import math
import numpy as np
from ._core import dynamic_round, crossover, crossunder
from ._moving_averages import calc_sma, calc_jma, calc_t3, calc_vidya
from ._rsi import calc_rsi
from ._atr import calc_atr
from ._bollinger import calc_bollinger_bands, calc_stddev
from ._trend import rational_quadratic


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
                           ):
    """
    candles: [{timestamp, open, high, low, close, volume}, ... ] (과거->현재)
      기존: SMA, JMA, RSI, Bollinger Bands, ATR 저장
      + Trend State( CYCLE_Bull, CYCLE_Bear, BBW 관련, trend_state )도 추가
    """
    closes = [c["close"] for c in candles]

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

    # (B) 1st Cycle MA
    if CYCLE_TYPE == "T3":
        MA1_ = calc_t3(closes, lenF)
        MA2_ = calc_t3(closes, lenM)
        MA3_ = calc_t3(closes, lenS)
    else:
        # 기본 JMA
        MA1_ = calc_jma(closes, length=lenF, phase=50, power=2)
        MA2_ = calc_jma(closes, length=lenM, phase=50, power=2)
        MA3_ = calc_jma(closes, length=lenS, phase=50, power=2)

    # rationalQuadratic 보정
    MA1_adj = rational_quadratic(MA1_, lookback=rq_lookback, relative_weight=rq_rel_weight, start_at_bar=rq_start_bar)
    MA2_adj = rational_quadratic(MA2_, lookback=rq_lookback, relative_weight=rq_rel_weight, start_at_bar=rq_start_bar)
    MA3_adj = rational_quadratic(MA3_, lookback=rq_lookback, relative_weight=rq_rel_weight, start_at_bar=rq_start_bar)

    # (C) 2nd Cycle (VIDYA 고정)
    # 간단히 3,9,21
    lenF2, lenM2, lenS2 = 3, 9, 21
    MA1_2nd = calc_vidya(closes, lenF2)
    MA2_2nd = calc_vidya(closes, lenM2)
    MA3_2nd = calc_vidya(closes, lenS2)

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

    # (D) BBW & BB_State (간략)
    # 기본 BB: length=bb_length, mult=bb_mult
    basis_list = calc_sma(closes, bb_length)
    stdev_list = calc_stddev(closes, bb_length)
    bbw_list = []
    for i in range(len(closes)):
        if math.isnan(basis_list[i]) or math.isnan(stdev_list[i]):
            bbw_list.append(math.nan)
        else:
            up_ = basis_list[i] + bb_mult*stdev_list[i]
            lo_ = basis_list[i] - bb_mult*stdev_list[i]
            if basis_list[i] != 0:
                bbw_list.append((up_ - lo_)*10.0 / basis_list[i])
            else:
                bbw_list.append(math.nan)
    # bbw의 SMA (ma_2)
    bbw_ma = calc_sma(bbw_list, bb_ma_len)

    bb_state_list = [0]*len(closes)

    for i in range(len(closes)):
        if i < 1:
            bb_state_list[i] = 0
            continue
        ma_val = bbw_ma[i]
        if math.isnan(ma_val):
            bb_state_list[i] = 0
            continue
        # 예시: buzz, squeeze를 ma_val 기반 임의 계산
        buzz = ma_val * 1.2
        squeeze = ma_val * 0.7

        if crossover(bbw_list, [buzz]*len(closes), i):
            bb_state_list[i] = 2
        elif crossunder(bbw_list, [squeeze]*len(closes), i):
            bb_state_list[i] = -2
        else:
            # 간단히 직전 state 유지
            bb_state_list[i] = bb_state_list[i-1]

    # (E) extreme_state = 2 / -2 / 0
    # Bull & BB_State=2 => extreme=2
    # Bear & BB_State=-2 => extreme=-2  (원본처럼 -2를 찍는 분기)
    # etc...
    trend_state_list = [0]*len(closes)
    for i in range(len(closes)):
        bull = final_bull_list[i]
        bear = final_bear_list[i]
        bb_st = bb_state_list[i]
        if bull and (bb_st == 2):
            trend_state_list[i] = 2
        elif bear and (bb_st == -1):
            trend_state_list[i] = -2
        else:
            trend_state_list[i] = 0

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
