"""
20:50 시점 BB_State 상세 디버깅
Pine Script = 0, Python = -1 불일치 원인 분석
"""

import asyncio
from datetime import datetime, timedelta, timezone
from BACKTEST.data.timescale_provider import TimescaleProvider
from shared.indicators._trend import _calc_bb_state


async def debug_bb_state_20_50():
    """20:50 시점 BB_State 디버깅"""

    print("=" * 140)
    print("20:50 시점 BB_State 디버깅 (Pine=0, Python=-1)")
    print("=" * 140)

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

    print(f"\n📊 5분봉: {len(candles_5m)}개")

    # BB_State 계산
    bb_state_list = _calc_bb_state(
        candles_5m,
        length_bb=15,
        mult_bb=1.5,
        ma_length=100,
        is_confirmed_only=True
    )

    # 20:45~21:00 구간 출력
    print("\n" + "=" * 140)
    print("5분봉 BB_State (20:45~21:00)")
    print("=" * 140)

    print(f"\n{'Index':<8} {'Timestamp':<20} {'Close':>10} {'BB_State':>10}")
    print("-" * 140)

    target_start = datetime(2025, 11, 16, 20, 45, 0, tzinfo=timezone.utc)
    target_end = datetime(2025, 11, 16, 21, 0, 0, tzinfo=timezone.utc)

    for i, c in enumerate(candles_5m):
        ts = c['timestamp']
        if target_start <= ts <= target_end:
            print(f"{i:<8} {str(ts)[:19]:<20} {c['close']:>10.2f} {bb_state_list[i]:>10}")


if __name__ == "__main__":
    asyncio.run(debug_bb_state_20_50())
