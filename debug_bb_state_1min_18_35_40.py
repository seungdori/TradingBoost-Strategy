"""
18:35~18:40 1분봉 BB_State 변화 확인
"""

import asyncio
from datetime import datetime, timedelta, timezone
from BACKTEST.data.timescale_provider import TimescaleProvider
from shared.indicators._trend import compute_trend_state


async def debug_bb_state_1min():
    """18:35~18:40 1분봉 BB_State 확인"""

    print("=" * 140)
    print("18:35~18:40 1분봉 BB_State 변화")
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

    # 18:35~18:40 구간 출력
    print(f"\n{'Idx':<6} {'Timestamp':<20} {'Close':>10} {'BB_State':>9} {'BB_MTF':>8} {'trend_state':>12}")
    print("-" * 140)

    target_start = datetime(2025, 11, 16, 18, 35, 0, tzinfo=timezone.utc)
    target_end = datetime(2025, 11, 16, 18, 40, 0, tzinfo=timezone.utc)

    for i, candle in enumerate(result):
        ts = candle['timestamp']
        if target_start <= ts <= target_end:
            close = candle.get('close', 0)
            bb_state = candle.get('BB_State', 0)
            bb_mtf = candle.get('BB_State_MTF', 0)
            trend_state = candle.get('trend_state', 0)

            print(f"{i:<6} {str(ts)[:19]:<20} {close:>10.2f} {bb_state:>9} {bb_mtf:>8} {trend_state:>12}")


if __name__ == "__main__":
    asyncio.run(debug_bb_state_1min())
