"""
15분봉 CYCLE 값 직접 확인
"""

import asyncio
from datetime import datetime, timedelta, timezone
from BACKTEST.data.timescale_provider import TimescaleProvider
from shared.indicators._trend import compute_trend_state


async def debug_cycle_15m():
    """15분봉 CYCLE 값 확인"""

    print("=" * 140)
    print("15분봉 CYCLE 값 직접 확인")
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

    # 15분봉의 CYCLE 값 추출 (1분봉 결과에서 15분봉 경계 찾기)
    print(f"\n15분봉 시작 시점의 CYCLE 값:")
    print(f"\n{'Index':<8} {'15m_Time':<20} {'Close':>10} {'CYCLE_Bull':>11} {'CYCLE_Bear':>11}")
    print("-" * 140)

    target_start = datetime(2025, 11, 16, 18, 0, 0, tzinfo=timezone.utc)
    target_end = datetime(2025, 11, 16, 19, 15, 0, tzinfo=timezone.utc)

    for i, candle in enumerate(result):
        ts = candle['timestamp']

        # 15분 경계 (00, 15, 30, 45분)만 출력
        if target_start <= ts <= target_end and ts.minute % 15 == 0:
            cycle_bull = candle.get('CYCLE_Bull', False)
            cycle_bear = candle.get('CYCLE_Bear', False)
            close = candle.get('close', 0)

            print(f"{i:<8} {str(ts)[:19]:<20} {close:>10.2f} {str(cycle_bull):>11} {str(cycle_bear):>11}")


if __name__ == "__main__":
    asyncio.run(debug_cycle_15m())
