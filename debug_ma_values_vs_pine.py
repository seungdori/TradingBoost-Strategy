"""
MA 값 디버깅 - Pine Script CSV 시간대
"""

import asyncio
import pandas as pd
from datetime import datetime, timezone
from BACKTEST.data.timescale_provider import TimescaleProvider
from shared.indicators._moving_averages import get_ma
from shared.indicators._trend import _forward_fill_mtf_to_current_tf, rational_quadratic


async def debug_ma_values():
    """MA 값 상세 출력"""

    print("=" * 140)
    print("MA 값 디버깅 - Pine Script CSV 시간대")
    print("=" * 140)

    # Pine Script CSV 로드
    csv_path = "/Users/seunghyun/Downloads/OKX_BTCUSDT.P, 1_8f411.csv"
    pine_df = pd.read_csv(csv_path)
    pine_df['datetime'] = pd.to_datetime(pine_df['time'], unit='s', utc=timezone.utc)

    # 17:00 이후 필터링
    start_time = datetime(2025, 11, 16, 17, 0, 0, tzinfo=timezone.utc)
    end_time = pine_df['datetime'].max()

    provider = TimescaleProvider()

    # 1분봉
    candles_1m_raw = await provider.get_candles("BTC-USDT-SWAP", "1m", start_time, end_time)
    candles_1m = [
        {'timestamp': c.timestamp, 'open': c.open, 'high': c.high, 'low': c.low, 'close': c.close, 'volume': c.volume}
        for c in candles_1m_raw
    ]

    # 15분봉
    candles_15m_raw = await provider.get_candles("BTC-USDT-SWAP", "15m", start_time, end_time)
    candles_15m = [
        {'timestamp': c.timestamp, 'open': c.open, 'high': c.high, 'low': c.low, 'close': c.close, 'volume': c.volume}
        for c in candles_15m_raw
    ]

    print(f"\n📊 1분봉: {len(candles_1m)}개")
    print(f"📊 15분봉: {len(candles_15m)}개")
    print(f"\n첫 1분봉: {candles_1m[0]['timestamp']}")
    print(f"첫 15분봉: {candles_15m[0]['timestamp']}")

    # MA 계산 (CYCLE 1 - 15분봉 기준)
    lenF = 5
    lenM = 20
    lenS = 50

    closes_15m = [c["close"] for c in candles_15m]
    MA1_htf = get_ma(closes_15m, "JMA", length=lenF)
    MA2_htf = get_ma(closes_15m, "VIDYA", length=lenM)
    MA3_htf = get_ma(closes_15m, "T3", length=lenS)

    # Rational quadratic 적용
    lookback = 8
    relative_weight = 8.0
    start_at_bar = 25

    MA1_adj_htf = rational_quadratic(MA1_htf, lookback=lookback, relative_weight=relative_weight, start_at_bar=start_at_bar)
    MA2_adj_htf = rational_quadratic(MA2_htf, lookback=lookback, relative_weight=relative_weight, start_at_bar=start_at_bar)
    MA3_adj_htf = rational_quadratic(MA3_htf, lookback=lookback, relative_weight=relative_weight, start_at_bar=start_at_bar)

    # Forward fill
    MA1_adj = _forward_fill_mtf_to_current_tf(candles_1m, candles_15m, MA1_adj_htf, is_backtest=True)
    MA2_adj = _forward_fill_mtf_to_current_tf(candles_1m, candles_15m, MA2_adj_htf, is_backtest=True)
    MA3_adj = _forward_fill_mtf_to_current_tf(candles_1m, candles_15m, MA3_adj_htf, is_backtest=True)

    # 처음 50개 캔들의 MA 값 출력
    print("\n" + "=" * 180)
    print("처음 50개 캔들의 CYCLE MA 값")
    print("=" * 180)

    print(f"\n{'Idx':<5} {'Timestamp':<20} {'Close':>10} {'MA1_adj':>12} {'MA2_adj':>12} {'MA3_adj':>12} "
          f"{'MA1>MA2':>8} {'MA2>MA3':>8} {'Bull':>6} {'Bear':>6} {'trend':>7} {'Pine':>7}")
    print("-" * 180)

    # Pine Script dict
    pine_dict = {}
    for _, row in pine_df.iterrows():
        ts = row['datetime']
        pine_dict[ts] = row['trend_state']

    for i in range(min(50, len(candles_1m))):
        candle = candles_1m[i]
        timestamp = candle['timestamp']
        close = candle['close']

        ma1 = MA1_adj[i]
        ma2 = MA2_adj[i]
        ma3 = MA3_adj[i]

        # CYCLE Bull/Bear 조건
        cycle_bull = ma1 > ma2 and ma2 > ma3
        cycle_bear = ma1 < ma2 and ma2 < ma3

        bull_str = "Bull" if cycle_bull else "----"
        bear_str = "Bear" if cycle_bear else "----"

        ma1_gt_ma2 = "Y" if ma1 > ma2 else "N"
        ma2_gt_ma3 = "Y" if ma2 > ma3 else "N"

        # trend_state (간단 버전: CYCLE만 체크)
        if cycle_bull:
            python_trend = 2
        elif cycle_bear:
            python_trend = -2
        else:
            python_trend = 0

        pine_trend = pine_dict.get(timestamp, 'N/A')

        print(f"{i:<5} {str(timestamp)[:19]:<20} {close:>10.2f} {ma1:>12.2f} {ma2:>12.2f} {ma3:>12.2f} "
              f"{ma1_gt_ma2:>8} {ma2_gt_ma3:>8} {bull_str:>6} {bear_str:>6} {python_trend:>7} {pine_trend:>7}")

    # 15분봉 MA 값도 출력
    print("\n" + "=" * 140)
    print("15분봉 처음 10개의 MA 값")
    print("=" * 140)

    print(f"\n{'Index':<8} {'Timestamp':<20} {'Close':>10} {'MA1':>12} {'MA2':>12} {'MA3':>12} "
          f"{'MA1>MA2':>8} {'MA2>MA3':>8}")
    print("-" * 140)

    for i in range(min(10, len(candles_15m))):
        ts = candles_15m[i]['timestamp']
        close = candles_15m[i]['close']
        ma1 = MA1_adj_htf[i]
        ma2 = MA2_adj_htf[i]
        ma3 = MA3_adj_htf[i]

        ma1_gt_ma2 = "Y" if ma1 > ma2 else "N"
        ma2_gt_ma3 = "Y" if ma2 > ma3 else "N"

        print(f"{i:<8} {str(ts)[:19]:<20} {close:>10.2f} {ma1:>12.2f} {ma2:>12.2f} {ma3:>12.2f} "
              f"{ma1_gt_ma2:>8} {ma2_gt_ma3:>8}")


if __name__ == "__main__":
    asyncio.run(debug_ma_values())
