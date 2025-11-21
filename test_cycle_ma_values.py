"""
CYCLE MA 값 직접 출력

목적: CYCLE_Bull/Bear가 왜 False인지 확인
"""

import asyncio
from datetime import datetime, timedelta, timezone
from BACKTEST.data.timescale_provider import TimescaleProvider
from shared.indicators._trend import compute_trend_state


async def test_cycle_ma_values():
    """CYCLE MA 값 직접 출력"""

    print("=" * 120)
    print("CYCLE MA 값 디버깅")
    print("=" * 120)

    # 데이터 수집 (7일)
    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(days=7)

    provider = TimescaleProvider()

    # 1분봉
    candles_1m_raw = await provider.get_candles(
        symbol="BTC-USDT-SWAP",
        timeframe="1m",
        start_date=start_time,
        end_date=end_time
    )

    candles_1m = [
        {
            'timestamp': c.timestamp,
            'open': c.open,
            'high': c.high,
            'low': c.low,
            'close': c.close,
            'volume': c.volume
        }
        for c in candles_1m_raw
    ]

    # 15분봉
    candles_15m_raw = await provider.get_candles(
        symbol="BTC-USDT-SWAP",
        timeframe="15m",
        start_date=start_time,
        end_date=end_time
    )

    candles_15m = [
        {
            'timestamp': c.timestamp,
            'open': c.open,
            'high': c.high,
            'low': c.low,
            'close': c.close,
            'volume': c.volume
        }
        for c in candles_15m_raw
    ]

    # 5분봉
    candles_5m_raw = await provider.get_candles(
        symbol="BTC-USDT-SWAP",
        timeframe="5m",
        start_date=start_time,
        end_date=end_time
    )

    candles_5m = [
        {
            'timestamp': c.timestamp,
            'open': c.open,
            'high': c.high,
            'low': c.low,
            'close': c.close,
            'volume': c.volume
        }
        for c in candles_5m_raw
    ]

    # 4h
    candles_4h_raw = await provider.get_candles(
        symbol="BTC-USDT-SWAP",
        timeframe="4h",
        start_date=start_time,
        end_date=end_time
    )

    candles_4h = [
        {
            'timestamp': c.timestamp,
            'open': c.open,
            'high': c.high,
            'low': c.low,
            'close': c.close,
            'volume': c.volume
        }
        for c in candles_4h_raw
    ]

    print(f"\n📊 1분봉: {len(candles_1m)}개")
    print(f"📊 15분봉: {len(candles_15m)}개")
    print(f"📊 5분봉: {len(candles_5m)}개")
    print(f"📊 4h: {len(candles_4h)}개")

    # shared/indicators/_trend.py에서 직접 MA 계산 로직 복사
    from shared.indicators._moving_averages import get_ma
    from shared.indicators._trend import _forward_fill_mtf_to_current_tf, rational_quadratic

    # Pine Script Line 192-204: MA (Cycle 1)
    lenF = 5
    lenM = 20
    lenS = 50

    # 15분봉으로 MA 계산
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

    # CYCLE_Bull/Bear 조건 확인
    print("\n" + "=" * 140)
    print("처음 20개 캔들의 CYCLE MA 값")
    print("=" * 140)

    print(f"\n{'Idx':<5} {'Timestamp':<20} {'Close':>10} {'MA1_adj':>12} {'MA2_adj':>12} {'MA3_adj':>12} {'Bull':>6} {'Bear':>6}")
    print("-" * 140)

    for i in range(min(20, len(candles_1m))):
        candle = candles_1m[i]
        timestamp = candle.get('timestamp', 'N/A')
        close = candle.get('close', 0)

        ma1 = MA1_adj[i]
        ma2 = MA2_adj[i]
        ma3 = MA3_adj[i]

        # Pine Script Line 205-206: CYCLE Bull/Bear 조건
        cycle_bull = ma1 > ma2 and ma2 > ma3
        cycle_bear = ma1 < ma2 and ma2 < ma3

        bull_str = "Bull" if cycle_bull else "----"
        bear_str = "Bear" if cycle_bear else "----"

        print(f"{i:<5} {str(timestamp)[:19]:<20} {close:>10.2f} {ma1:>12.2f} {ma2:>12.2f} {ma3:>12.2f} {bull_str:>6} {bear_str:>6}")

    # 15분봉에서 직접 계산한 MA 값도 출력
    print("\n" + "=" * 120)
    print("15분봉 처음 10개의 MA 값 (forward fill 전)")
    print("=" * 120)

    print(f"\n{'Index':<8} {'Timestamp':<20} {'Close':>10} {'MA1':>12} {'MA2':>12} {'MA3':>12}")
    print("-" * 100)

    for i in range(min(10, len(candles_15m))):
        ts = candles_15m[i]['timestamp']
        close = candles_15m[i]['close']
        ma1 = MA1_adj_htf[i]
        ma2 = MA2_adj_htf[i]
        ma3 = MA3_adj_htf[i]

        print(f"{i:<8} {str(ts)[:19]:<20} {close:>10.2f} {ma1:>12.2f} {ma2:>12.2f} {ma3:>12.2f}")


if __name__ == "__main__":
    asyncio.run(test_cycle_ma_values())
