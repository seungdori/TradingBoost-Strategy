#!/usr/bin/env python3
"""
Debug script to check why pivothigh is not detecting any pivots in BBW data
"""
import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from BACKTEST.data.timescale_provider import TimescaleProvider
from shared.indicators._all_indicators import compute_all_indicators
from shared.indicators._core import pivothigh
import math


async def debug_pivothigh():
    """Debug pivothigh detection in BBW calculation"""

    from datetime import datetime, timezone
    from sqlalchemy import text

    provider = TimescaleProvider()

    # Fetch ALL BTC-USDT-SWAP 15m data
    # Get first and last timestamp from DB
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

    print(f"Date range: {start_date} to {end_date}")

    # Fetch all candles
    candles = await provider.get_candles(
        symbol="BTC-USDT-SWAP",
        timeframe="15m",
        start_date=start_date,
        end_date=end_date
    )

    print(f"Total candles: {len(candles)}")
    print("=" * 80)

    # Convert to dict list
    candles_dict = [
        {
            "timestamp": c.timestamp,
            "open": c.open,
            "high": c.high,
            "low": c.low,
            "close": c.close,
            "volume": c.volume
        }
        for c in candles
    ]

    # Compute indicators
    candles_with_indicators = compute_all_indicators(
        candles=candles_dict,
        current_timeframe_minutes=15
    )

    # Check what fields are available
    if candles_with_indicators:
        print("\n📋 Available fields in first candle:")
        print(f"Keys: {list(candles_with_indicators[0].keys())}")
        print(f"\nFirst candle sample:")
        for k, v in list(candles_with_indicators[0].items())[:10]:
            print(f"  {k}: {v}")

    # Extract BBW values
    bbw_list = [c.get("bbw", float('nan')) for c in candles_with_indicators]

    print("\n📊 BBW Statistics:")
    valid_bbw = [b for b in bbw_list if not math.isnan(b)]
    print(f"Total BBW values: {len(bbw_list)}")
    print(f"Valid BBW values: {len(valid_bbw)}")
    print(f"NaN BBW values: {len(bbw_list) - len(valid_bbw)}")

    if valid_bbw:
        print(f"Min BBW: {min(valid_bbw):.6f}")
        print(f"Max BBW: {max(valid_bbw):.6f}")
        print(f"Mean BBW: {sum(valid_bbw) / len(valid_bbw):.6f}")
    else:
        print("⚠️ NO VALID BBW VALUES FOUND!")
        print("\nLet's check BB_State field:")
        bb_state_list = [c.get("BB_State") for c in candles_with_indicators]
        print(f"BB_State values (first 50): {bb_state_list[:50]}")
        print(f"Unique BB_State values: {set(bb_state_list)}")
        return

    # Show BBW values distribution
    print("\n📈 BBW Distribution:")
    ranges = [
        (0.0, 0.1, "0.0-0.1"),
        (0.1, 0.2, "0.1-0.2"),
        (0.2, 0.3, "0.2-0.3"),
        (0.3, 0.5, "0.3-0.5"),
        (0.5, 1.0, "0.5-1.0"),
        (1.0, float('inf'), ">1.0")
    ]
    for min_val, max_val, label in ranges:
        count = sum(1 for b in valid_bbw if min_val <= b < max_val)
        pct = count / len(valid_bbw) * 100
        print(f"  {label}: {count:5d} ({pct:5.1f}%)")

    # Manual pivot high detection
    print("\n🔍 Manual Pivot High Detection:")
    pivot_left = 20
    pivot_right = 10

    # Check specific windows
    test_indices = [
        100, 200, 500, 1000, 5000, 10000, 15000
    ]

    for idx in test_indices:
        if idx < pivot_left or idx >= len(bbw_list) - pivot_right:
            continue

        current = bbw_list[idx]
        if math.isnan(current):
            continue

        # Check left window
        left_window = bbw_list[idx - pivot_left:idx]
        left_max = max([b for b in left_window if not math.isnan(b)], default=0)

        # Check right window
        right_window = bbw_list[idx + 1:idx + pivot_right + 1]
        right_max = max([b for b in right_window if not math.isnan(b)], default=0)

        is_pivot = current > left_max and current > right_max

        print(f"\nIndex {idx}:")
        print(f"  Current BBW: {current:.6f}")
        print(f"  Left max: {left_max:.6f}")
        print(f"  Right max: {right_max:.6f}")
        print(f"  Is pivot? {is_pivot}")

    # Run pivothigh function
    print("\n⚙️ Running pivothigh function:")
    ph_list = pivothigh(bbw_list, pivot_left, pivot_right)

    pivots_found = [i for i, p in enumerate(ph_list) if p is not None]
    print(f"Pivots found by pivothigh: {len(pivots_found)}")

    if pivots_found:
        print("\nFirst 10 pivots:")
        for i in pivots_found[:10]:
            print(f"  Index {i}: BBW={ph_list[i]:.6f}")
    else:
        print("\n❌ NO PIVOTS FOUND!")
        print("\nLet's check if the issue is with the comparison logic...")

        # Try manual implementation with debug
        manual_pivots = []
        for i in range(pivot_left, len(bbw_list) - pivot_right):
            current = bbw_list[i]

            if math.isnan(current):
                continue

            # Check left: current must be > all left values
            is_pivot = True
            for j in range(i - pivot_left, i):
                if not math.isnan(bbw_list[j]) and bbw_list[j] >= current:
                    is_pivot = False
                    break

            if not is_pivot:
                continue

            # Check right: current must be > all right values
            for j in range(i + 1, i + pivot_right + 1):
                if not math.isnan(bbw_list[j]) and bbw_list[j] >= current:
                    is_pivot = False
                    break

            if is_pivot:
                manual_pivots.append(i)

        print(f"\nManual pivot detection: {len(manual_pivots)} pivots")

        if manual_pivots:
            print("\nFirst 10 manual pivots:")
            for i in manual_pivots[:10]:
                print(f"  Index {i}: BBW={bbw_list[i]:.6f}")
        else:
            print("\n❌ Manual detection also found no pivots!")
            print("\nThis means BBW values are too smooth - no local maxima detected.")
            print("Let's check the volatility of BBW:")

            # Calculate BBW changes
            changes = []
            for i in range(1, len(valid_bbw)):
                change = abs(valid_bbw[i] - valid_bbw[i-1])
                changes.append(change)

            avg_change = sum(changes) / len(changes)
            max_change = max(changes)

            print(f"\nBBW Volatility:")
            print(f"  Average change: {avg_change:.6f}")
            print(f"  Max change: {max_change:.6f}")
            print(f"  Change/Mean ratio: {avg_change / (sum(valid_bbw) / len(valid_bbw)):.4f}")


if __name__ == "__main__":
    asyncio.run(debug_pivothigh())
