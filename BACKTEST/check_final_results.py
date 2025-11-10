#!/usr/bin/env python3
"""
Check final BB_State and trend_state distribution after fix
"""
import asyncio
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import text
from BACKTEST.data.timescale_provider import TimescaleProvider


async def check_results():
    provider = TimescaleProvider()
    session = await provider._get_session()

    # Check BB_State distribution
    query = text("""
        SELECT
            bb_state,
            COUNT(*) as count,
            ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER(), 2) as percentage
        FROM okx_candles_15m
        WHERE symbol = 'BTC-USDT-SWAP'
        GROUP BY bb_state
        ORDER BY bb_state
    """)

    result = await session.execute(query)
    rows = result.fetchall()

    print("📊 BB_State Distribution:")
    print("=" * 60)
    for bb_state, count, pct in rows:
        state_label = {
            -2: "Bearish Expansion",
            -1: "Squeeze",
            0: "Normal",
            2: "Bullish Expansion"
        }.get(bb_state, f"Unknown ({bb_state})")
        print(f"  {bb_state:2d} ({state_label:20s}): {count:6d} ({pct:5.2f}%)")

    # Check trend_state distribution
    query = text("""
        SELECT
            trend_state,
            COUNT(*) as count,
            ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER(), 2) as percentage
        FROM okx_candles_15m
        WHERE symbol = 'BTC-USDT-SWAP'
        GROUP BY trend_state
        ORDER BY trend_state
    """)

    result = await session.execute(query)
    rows = result.fetchall()

    print("\n📈 Trend_State Distribution:")
    print("=" * 60)
    for trend_state, count, pct in rows:
        state_label = {
            -2: "Extreme Bearish",
            -1: "Bearish",
            0: "Neutral",
            1: "Bullish",
            2: "Extreme Bullish"
        }.get(trend_state, f"Unknown ({trend_state})")
        print(f"  {trend_state:2d} ({state_label:20s}): {count:6d} ({pct:5.2f}%)")

    # Show recent values
    query = text("""
        SELECT
            time,
            close,
            bb_state,
            trend_state,
            cycle_bull,
            cycle_bear
        FROM okx_candles_15m
        WHERE symbol = 'BTC-USDT-SWAP'
        ORDER BY time DESC
        LIMIT 30
    """)

    result = await session.execute(query)
    rows = result.fetchall()

    print("\n🕒 Recent Values (last 30 candles):")
    print("=" * 100)
    print(f"{'Time':20s} {'Close':>10s} {'BB_State':>10s} {'Trend':>6s} {'Bull':>6s} {'Bear':>6s}")
    print("=" * 100)

    for time, close, bb_state, trend_state, cycle_bull, cycle_bear in rows:
        print(f"{str(time)[:19]:20s} {close:10.1f} {bb_state:10d} {trend_state:6d} {'✓' if cycle_bull else '':>6s} {'✓' if cycle_bear else '':>6s}")

    print("\n✅ Verification complete!")


if __name__ == "__main__":
    asyncio.run(check_results())
