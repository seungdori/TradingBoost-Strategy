"""
Pine Script CSV vs Python 계산 상세 비교
20:50 시점 모든 중간값 비교
"""

import asyncio
import math
import pandas as pd
from datetime import datetime, timedelta, timezone
from BACKTEST.data.timescale_provider import TimescaleProvider
from shared.indicators._all_indicators import calc_sma, calc_stddev, pivothigh, pivotlow, crossover, falling, rising


async def compare_detailed():
    """Pine Script CSV와 Python 계산의 모든 중간값 비교"""

    print("=" * 160)
    print("Pine Script CSV vs Python 계산 상세 비교 (20:45~21:00)")
    print("=" * 160)

    # Pine Script CSV 로드
    csv_path = "/Users/seunghyun/Downloads/OKX_BTCUSDT.P, 1_8f411.csv"
    df_pine = pd.read_csv(csv_path)
    df_pine['time'] = pd.to_datetime(df_pine['time'], unit='s', utc=True)

    # 5분봉 경계만 추출
    target_times = [
        datetime(2025, 11, 16, 20, 40, 0, tzinfo=timezone.utc),
        datetime(2025, 11, 16, 20, 45, 0, tzinfo=timezone.utc),
        datetime(2025, 11, 16, 20, 50, 0, tzinfo=timezone.utc),
        datetime(2025, 11, 16, 20, 55, 0, tzinfo=timezone.utc),
        datetime(2025, 11, 16, 21, 0, 0, tzinfo=timezone.utc),
    ]

    print("\n📊 Pine Script CSV (5분 경계):")
    print(f"{'Timestamp':<20} {'close':>10} {'BB_state_MTF':>13}")
    print("-" * 50)

    pine_data = {}
    for t in target_times:
        row = df_pine[df_pine['time'] == t]
        if not row.empty:
            close = row['close'].values[0]
            bb_mtf = int(row['BB_state_MTF'].values[0])
            pine_data[t] = {'close': close, 'bb_mtf': bb_mtf}
            print(f"{str(t)[:19]:<20} {close:>10.2f} {bb_mtf:>13}")

    # Python 계산
    csv_start = datetime(2025, 11, 16, 16, 51, 0, tzinfo=timezone.utc)
    start_time = csv_start - timedelta(days=7)
    end_time = datetime(2025, 11, 17, 7, 1, 0, tzinfo=timezone.utc)

    provider = TimescaleProvider()

    # 5분봉
    candles_5m_raw = await provider.get_candles("BTC-USDT-SWAP", "5m", start_time, end_time)
    candles_5m = [
        {'timestamp': c.timestamp, 'open': c.open, 'high': c.high, 'low': c.low, 'close': c.close, 'volume': c.volume}
        for c in candles_5m_raw
    ]

    print(f"\n📊 Python 5분봉: {len(candles_5m)}개")

    # BB_State 계산 파라미터
    length_bb = 15
    mult_bb = 1.5
    ma_length = 100

    closes = [c["close"] for c in candles_5m]

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

    # Pivot High/Low
    pivot_left = 20
    pivot_right = 10
    ph_list = pivothigh(bbw_list, pivot_left, pivot_right)
    pl_list = pivotlow(bbw_list, pivot_left, pivot_right)

    # Pivot Arrays
    array_size = 50
    ph_array = []
    pl_array = []

    for i in range(len(closes)):
        bbw_val = bbw_list[i]
        ma_val = bbw_ma[i]

        if ma_val is None or math.isnan(ma_val) or math.isnan(bbw_val):
            continue

        if bbw_val > ma_val and ph_list[i] is not None:
            ph_array.append(ph_list[i])
            if len(ph_array) > array_size:
                ph_array.pop(0)

        if bbw_val < ma_val and pl_list[i] is not None:
            pl_array.append(pl_list[i])
            if len(pl_array) > array_size:
                pl_array.pop(0)

    # ph_avg, pl_avg
    if len(ph_array) > 0:
        ph_avg = sum(ph_array) / len(ph_array)
    else:
        ph_avg = max([b for b in bbw_list if not math.isnan(b)] + [5])

    if len(pl_array) > 0:
        pl_avg = sum(pl_array) / len(pl_array)
    else:
        pl_avg = min([b for b in bbw_list if not math.isnan(b)] + [5])

    # buzz, squeeze
    mult_plph = 0.7
    buzz = ph_avg * mult_plph
    squeeze = pl_avg * (1 / mult_plph)

    print(f"\n📊 계산된 고정값:")
    print(f"   buzz = {buzz:.6f}")
    print(f"   squeeze = {squeeze:.6f}")
    print(f"   pl_avg = {pl_avg:.6f}")

    # BBW 2nd
    length_2nd = 60
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

    pl_2nd_list = pivotlow(bbw_2nd_list, 30, 10)

    pl_array_2nd = []
    for i in range(len(closes)):
        bbw_2nd_val = bbw_2nd_list[i]
        if not math.isnan(bbw_2nd_val) and bbw_2nd_val < 1 and pl_2nd_list[i] is not None:
            pl_array_2nd.append(pl_2nd_list[i])
            if len(pl_array_2nd) > array_size:
                pl_array_2nd.pop(0)

    if len(pl_array_2nd) > 0:
        pl_avg_2nd = sum(pl_array_2nd) / len(pl_array_2nd)
    else:
        pl_avg_2nd = min([b for b in bbw_2nd_list if not math.isnan(b)] + [5])

    squeeze_2nd = pl_avg_2nd * (1 / mult_plph)

    # bbw_2nd_squeeze
    bbw_2nd_squeeze_history = [True] * len(closes)
    use_bbw_2nd = True

    for i in range(len(closes)):
        bbw_2nd_val = bbw_2nd_list[i]
        prev_squeeze = bbw_2nd_squeeze_history[i-1] if i > 0 else True
        current_squeeze = prev_squeeze

        if not math.isnan(bbw_2nd_val):
            if use_bbw_2nd and bbw_2nd_val > squeeze_2nd:
                current_squeeze = False
            elif use_bbw_2nd and bbw_2nd_val < squeeze_2nd:
                current_squeeze = True

        bbw_2nd_squeeze_history[i] = current_squeeze

    # BB_State 계산
    bb_state_list = [0] * len(closes)

    for i in range(len(closes)):
        if i < 1:
            bb_state_list[i] = 0
            continue

        bbw_val = bbw_list[i]
        bbr_val = bbr_list[i]
        prev_bb_state = bb_state_list[i-1]
        is_confirmed = True

        if math.isnan(bbw_val) or math.isnan(bbr_val):
            bb_state_list[i] = prev_bb_state
            continue

        current_state = prev_bb_state

        # crossover(bbw, buzz)
        if is_confirmed and crossover(bbw_list, [buzz]*len(closes), i):
            if bbr_val > 0.5:
                current_state = 2
            elif bbr_val < 0.5:
                current_state = -2

        # squeeze
        if bbw_val < squeeze and bbw_2nd_squeeze_history[i]:
            current_state = -1

        # BBR 기반 상태 전환
        if is_confirmed:
            if current_state == 2 and bbr_val < 0.2:
                current_state = -2
            elif current_state == -2 and bbr_val > 0.8:
                current_state = 2

        # falling/rising으로 상태 리셋
        if is_confirmed:
            if (current_state == 2 or current_state == -2) and falling(bbw_list, i, 3):
                current_state = 0
            if bbw_val > pl_avg and current_state == -1 and rising(bbw_list, i, 1):
                current_state = 0

        bb_state_list[i] = current_state

    # 20:40~21:00 구간 상세 출력
    print("\n" + "=" * 160)
    print("Python 계산 상세 (20:40~21:00)")
    print("=" * 160)

    print(f"\n{'Index':<8} {'Timestamp':<20} {'Close':>10} {'BBW':>10} {'Squeeze':>10} {'BBW<Sq':>8} {'2nd_Sq':>8} {'Prev_ST':>8} {'BB_State':>9} {'Pine_BB':>9} {'Match':>8}")
    print("-" * 160)

    target_start = datetime(2025, 11, 16, 20, 40, 0, tzinfo=timezone.utc)
    target_end = datetime(2025, 11, 16, 21, 0, 0, tzinfo=timezone.utc)

    for i, c in enumerate(candles_5m):
        ts = c['timestamp']
        if target_start <= ts <= target_end:
            close = c['close']
            bbw = bbw_list[i]
            squeeze_val = bbw_2nd_squeeze_history[i]
            bbw_less_squeeze = bbw < squeeze
            prev_state = bb_state_list[i-1] if i > 0 else 0
            bb_state = bb_state_list[i]

            # Pine Script 값
            pine_bb = pine_data.get(ts, {}).get('bb_mtf', 'N/A')
            match = "✅" if bb_state == pine_bb else "❌"

            print(f"{i:<8} {str(ts)[:19]:<20} {close:>10.2f} {bbw:>10.4f} {squeeze:>10.4f} {str(bbw_less_squeeze):>8} {str(squeeze_val):>8} {prev_state:>8} {bb_state:>9} {pine_bb:>9} {match:>8}")


if __name__ == "__main__":
    asyncio.run(compare_detailed())
