#!/usr/bin/env python3
"""Verify that BB_State and trend_state are now correctly calculated"""
import asyncio
import sys
from pathlib import Path
from collections import Counter

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from BACKTEST.data.timescale_provider import TimescaleProvider
from datetime import datetime, timezone
from sqlalchemy import text


async def verify_fix():
    provider = TimescaleProvider()

    # Get date range
    session = await provider._get_session()
    table_name = provider._get_table_name("15m")
    normalized_symbol = provider._normalize_symbol("BTC-USDT-SWAP")

    query_str = f"""
        SELECT
            MIN(time) as start_time,
            MAX(time) as end_time
        FROM {table_name}
        WHERE symbol = :symbol
    """

    result = await session.execute(text(query_str), {"symbol": normalized_symbol})
    row = result.fetchone()

    start_date = row[0]
    end_date = row[1]

    # Fetch candles
    candles = await provider.get_candles(
        symbol="BTC-USDT-SWAP",
        timeframe="15m",
        start_date=start_date,
        end_date=end_date
    )

    print(f"Total candles: {len(candles)}")
    print("=" * 80)

    # Count BB_State distribution
    bb_states = Counter()
    trend_states = Counter()

    for c in candles:
        if hasattr(c, 'bb_state') and c.bb_state is not None:
            bb_states[c.bb_state] += 1
        if hasattr(c, 'trend_state') and c.trend_state is not None:
            trend_states[c.trend_state] += 1

    print("\n📊 BB_State Distribution:")
    print("=" * 60)
    total_bb = sum(bb_states.values())
    for state in sorted(bb_states.keys()):
        count = bb_states[state]
        pct = count / total_bb * 100 if total_bb > 0 else 0
        state_label = {
            -2: "Bearish Expansion",
            -1: "Squeeze",
            0: "Normal",
            2: "Bullish Expansion"
        }.get(state, f"Unknown ({state})")
        print(f"  {state:2d} ({state_label:20s}): {count:6d} ({pct:5.2f}%)")

    print("\n📈 Trend_State Distribution:")
    print("=" * 60)
    total_trend = sum(trend_states.values())
    for state in sorted(trend_states.keys()):
        count = trend_states[state]
        pct = count / total_trend * 100 if total_trend > 0 else 0
        state_label = {
            -2: "Extreme Bearish",
            -1: "Bearish",
            0: "Neutral",
            1: "Bullish",
            2: "Extreme Bullish"
        }.get(state, f"Unknown ({state})")
        print(f"  {state:2d} ({state_label:20s}): {count:6d} ({pct:5.2f}%)")

    # Show recent values
    print("\n🕒 Recent Values (last 30 candles):")
    print("=" * 100)
    print(f"{'Time':20s} {'Close':>10s} {'BB_State':>10s} {'Trend':>6s} {'Bull':>6s} {'Bear':>6s}")
    print("=" * 100)

    for c in candles[-30:]:
        bb_state = getattr(c, 'bb_state', None)
        trend_state = getattr(c, 'trend_state', None)
        cycle_bull = getattr(c, 'cycle_bull', None)
        cycle_bear = getattr(c, 'cycle_bear', None)

        bb_state_str = str(bb_state) if bb_state is not None else 'None'
        trend_state_str = str(trend_state) if trend_state is not None else 'None'

        print(f"{str(c.timestamp)[:19]:20s} {c.close:10.1f} "
              f"{bb_state_str:>10s} "
              f"{trend_state_str:>6s} "
              f"{'✓' if cycle_bull else '':>6s} "
              f"{'✓' if cycle_bear else '':>6s}")

    # Summary
    print("\n✅ Verification Summary:")
    print("=" * 80)

    # Check if we have diversity
    bb_2_count = bb_states.get(2, 0)
    bb_minus_2_count = bb_states.get(-2, 0)
    trend_2_count = trend_states.get(2, 0)
    trend_minus_2_count = trend_states.get(-2, 0)

    if bb_2_count > 0 or bb_minus_2_count > 0:
        print(f"✅ BB_State expansion detected: +2={bb_2_count}, -2={bb_minus_2_count}")
    else:
        print(f"⚠️  NO BB_State expansion detected (no +2 or -2 values)")

    if trend_2_count > 0 or trend_minus_2_count > 0:
        print(f"✅ Trend_State extremes detected: +2={trend_2_count}, -2={trend_minus_2_count}")
    else:
        print(f"⚠️  NO Trend_State extremes detected (no +2 or -2 values)")

    if bb_states.get(0, 0) == total_bb:
        print(f"❌ ALL BB_State values are 0 - something is still wrong!")
    elif bb_states.get(-1, 0) == total_bb:
        print(f"❌ ALL BB_State values are -1 (squeeze) - buzz may still be too high")
    else:
        print(f"✅ BB_State has diversity - fix appears successful!")

    if trend_states.get(0, 0) == total_trend:
        print(f"❌ ALL Trend_State values are 0 - something is still wrong!")
    else:
        print(f"✅ Trend_State has diversity - fix appears successful!")


if __name__ == "__main__":
    asyncio.run(verify_fix())
