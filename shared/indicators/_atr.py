"""
ATR (Average True Range) indicator
"""


def calc_atr(candles, length=14):
    """
    ATR(Average True Range) 계산
    length: ATR 기간 (기본값 14)
    """
    n = len(candles)
    tr_list = [0.0]*n
    atr_list = [None]*n

    # 1) True Range 계산
    for i in range(n):
        high = candles[i]["high"]
        low = candles[i]["low"]

        if i == 0:
            # 첫 캔들은 고가 - 저가
            tr_list[i] = high - low
        else:
            prev_close = candles[i-1]["close"]
            # TR = max(고가-저가, |고가-전종가|, |저가-전종가|)
            tr_list[i] = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close)
            )

    # 2) ATR 계산 (Wilder's Smoothing)
    for i in range(n):
        if i < length:
            # length 미만: 단순평균
            if i == 0:
                atr_list[i] = tr_list[i]
            else:
                atr_list[i] = sum(tr_list[:i+1]) / (i+1)
        else:
            # length 이상: Wilder 공식
            prev_atr = atr_list[i-1]
            atr_list[i] = (prev_atr * (length-1) + tr_list[i]) / length

    return atr_list
