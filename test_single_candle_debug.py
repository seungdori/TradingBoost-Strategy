"""
단일 캔들 디버깅

목적: 불일치 구간의 중간 계산 값 출력
"""

import asyncio
from datetime import datetime, timedelta, timezone
from BACKTEST.data.timescale_provider import TimescaleProvider
from shared.indicators._trend import compute_trend_state


async def test_single_candle_debug():
    """단일 캔들 디버깅"""

    print("=" * 80)
    print("단일 캔들 디버깅")
    print("=" * 80)

    # 데이터 수집
    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(days=1)

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

    # trend_state 계산
    print("\n⚙️  trend_state 계산 중...")
    result = compute_trend_state(
        candles=candles_1m,
        use_longer_trend=False,
        current_timeframe_minutes=1,
        candles_higher_tf=candles_15m,
        candles_bb_mtf=candles_5m,
        candles_4h=candles_4h,
        is_confirmed_only=True
    )

    print(f"✅ 계산 완료: {len(result)}개")

    # 처음 100개 캔들 출력
    print("\n" + "=" * 120)
    print("처음 100개 캔들의 중간 계산 값")
    print("=" * 120)

    print(f"\n{'Index':<8} {'Timestamp':<20} {'Close':>10} {'BB_State':>10} {'BB_MTF':>10} {'CYCLE_B':>10} {'CYCLE_b':>10} {'trend':>6} {'Pine':>6}")
    print("-" * 120)

    for i in range(min(100, len(result))):
        candle = result[i]

        timestamp = candle.get('timestamp', 'N/A')
        close = candle.get('close', 0)
        bb_state = candle.get('BB_State', 0)
        bb_state_mtf = candle.get('BB_State_MTF', 0)
        cycle_bull = candle.get('CYCLE_Bull', False)
        cycle_bear = candle.get('CYCLE_Bear', False)
        trend_state = candle.get('trend_state', 0)

        # TimescaleDB의 Pine Script 값
        pine_trend = candles_1m_raw[i].trend_state if hasattr(candles_1m_raw[i], 'trend_state') and candles_1m_raw[i].trend_state is not None else 0

        cycle_bull_str = "Bull" if cycle_bull else "----"
        cycle_bear_str = "Bear" if cycle_bear else "----"

        match = "✅" if trend_state == pine_trend else "❌"

        print(f"{i:<8} {str(timestamp)[:19]:<20} {close:>10.2f} {bb_state:>10} {bb_state_mtf:>10} "
              f"{cycle_bull_str:>10} {cycle_bear_str:>10} {trend_state:>6} {pine_trend:>6} {match}")


if __name__ == "__main__":
    asyncio.run(test_single_candle_debug())
