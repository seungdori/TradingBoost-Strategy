"""
20:45~20:54 구간 forward fill 디버깅
"""

import asyncio
from datetime import datetime, timedelta, timezone
from BACKTEST.data.timescale_provider import TimescaleProvider
from shared.indicators._trend import compute_trend_state


async def debug_20_45_forward_fill():
    """20:45~20:54 forward fill 디버깅"""

    print("=" * 140)
    print("20:45~20:54 구간 Forward Fill 디버깅")
    print("=" * 140)

    csv_start = datetime(2025, 11, 16, 16, 51, 0, tzinfo=timezone.utc)
    start_time = csv_start - timedelta(days=7)
    end_time = datetime(2025, 11, 17, 7, 1, 0, tzinfo=timezone.utc)

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

    # 5분봉
    candles_5m_raw = await provider.get_candles("BTC-USDT-SWAP", "5m", start_time, end_time)
    candles_5m = [
        {'timestamp': c.timestamp, 'open': c.open, 'high': c.high, 'low': c.low, 'close': c.close, 'volume': c.volume}
        for c in candles_5m_raw
    ]

    # 4시간봉
    candles_4h_raw = await provider.get_candles("BTC-USDT-SWAP", "4h", start_time, end_time)
    candles_4h = [
        {'timestamp': c.timestamp, 'open': c.open, 'high': c.high, 'low': c.low, 'close': c.close, 'volume': c.volume}
        for c in candles_4h_raw
    ]

    print(f"\n📊 1분봉: {len(candles_1m)}개")
    print(f"📊 5분봉: {len(candles_5m)}개")

    # compute_trend_state 호출
    result = compute_trend_state(
        candles=candles_1m,
        use_longer_trend=False,
        current_timeframe_minutes=1,
        candles_higher_tf=candles_15m,
        candles_bb_mtf=candles_5m,
        candles_4h=candles_4h,
        is_confirmed_only=True
    )

    # 20:45~20:54 구간 출력
    print("\n" + "=" * 140)
    print("1분봉 BB_State_MTF (20:45~20:54)")
    print("=" * 140)

    print(f"\n{'Index':<8} {'Timestamp':<20} {'Close':>10} {'BB_State_MTF':>13}")
    print("-" * 140)

    target_start = datetime(2025, 11, 16, 20, 45, 0, tzinfo=timezone.utc)
    target_end = datetime(2025, 11, 16, 20, 54, 0, tzinfo=timezone.utc)

    for i, candle in enumerate(result):
        ts = candle['timestamp']
        if target_start <= ts <= target_end:
            bb_mtf = candle.get('BB_State_MTF', 0)
            close = candle.get('close', 0)

            print(f"{i:<8} {str(ts)[:19]:<20} {close:>10.2f} {bb_mtf:>13}")


if __name__ == "__main__":
    asyncio.run(debug_20_45_forward_fill())
