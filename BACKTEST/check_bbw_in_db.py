#!/usr/bin/env python3
"""
Check BBW values directly from database
"""
import asyncio
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import text
from BACKTEST.data.timescale_provider import TimescaleProvider


async def check_bbw():
    provider = TimescaleProvider()
    session = await provider._get_session()

    # Check if bbw column exists and has values
    query = text("""
        SELECT
            time,
            close,
            bb_upper,
            bb_middle,
            bb_lower
        FROM okx_candles_15m
        WHERE symbol = 'BTC-USDT-SWAP'
        ORDER BY time DESC
        LIMIT 100
    """)

    result = await session.execute(query)
    rows = result.fetchall()

    print(f"Found {len(rows)} rows")
    print("\n📊 BB Band Values (latest 100 candles):")

    # Calculate BBW manually
    bbw_values = []
    for row in rows:
        time, close, bb_upper, bb_middle, bb_lower = row
        if bb_upper is not None and bb_lower is not None and bb_middle is not None:
            # BBW = (upper - lower) * 10 / basis
            bbw = (bb_upper - bb_lower) * 10 / bb_middle
            bbw_values.append((time, bbw, close))
        else:
            bbw_values.append((time, None, close))

    # Show statistics
    valid_bbw = [v[1] for v in bbw_values if v[1] is not None]

    if valid_bbw:
        print(f"\n✅ Valid BBW values: {len(valid_bbw)}")
        print(f"Min BBW: {min(valid_bbw):.6f}")
        print(f"Max BBW: {max(valid_bbw):.6f}")
        print(f"Mean BBW: {sum(valid_bbw) / len(valid_bbw):.6f}")

        # Show distribution
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
            count = sum(1 for v in valid_bbw if min_val <= v < max_val)
            pct = count / len(valid_bbw) * 100
            print(f"  {label}: {count:3d} ({pct:5.1f}%)")

        # Show recent values
        print("\n🕒 Recent BBW values (last 20):")
        for time, bbw, close in bbw_values[:20]:
            if bbw is not None:
                print(f"  {time}: BBW={bbw:.4f}, Close={close:.1f}")
            else:
                print(f"  {time}: BBW=None, Close={close:.1f}")

        # Check for pivot highs manually
        print("\n🔍 Looking for pivot highs (left=20, right=10):")
        # Reverse to chronological order
        bbw_chronological = [v[1] for v in reversed(bbw_values) if v[1] is not None]

        pivot_left = 20
        pivot_right = 10
        pivots_found = []

        for i in range(pivot_left, len(bbw_chronological) - pivot_right):
            current = bbw_chronological[i]

            # Check left
            is_pivot = True
            for j in range(i - pivot_left, i):
                if bbw_chronological[j] >= current:
                    is_pivot = False
                    break

            if not is_pivot:
                continue

            # Check right
            for j in range(i + 1, i + pivot_right + 1):
                if bbw_chronological[j] >= current:
                    is_pivot = False
                    break

            if is_pivot:
                pivots_found.append((i, current))

        print(f"Found {len(pivots_found)} pivot highs in last 100 candles")
        if pivots_found:
            print("\nPivot highs:")
            for idx, bbw in pivots_found[:10]:
                print(f"  Index {idx}: BBW={bbw:.4f}")
        else:
            print("❌ No pivot highs found in last 100 candles!")
            print("\nThis confirms the issue: BBW is too smooth - no local maxima within 30-bar window.")

    else:
        print("❌ No valid BBW values!")
        print("\nChecking if BB bands are NULL:")
        null_count = sum(1 for v in bbw_values if v[1] is None)
        print(f"NULL BB bands: {null_count}/{len(bbw_values)}")


if __name__ == "__main__":
    asyncio.run(check_bbw())
