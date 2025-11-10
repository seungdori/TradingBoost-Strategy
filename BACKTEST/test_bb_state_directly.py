#!/usr/bin/env python3
"""
Direct test of BB_State calculation to see BBW values
"""
import asyncio
import sys
from pathlib import Path
import math

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from BACKTEST.data.timescale_provider import TimescaleProvider
from shared.indicators._all_indicators import _calc_bb_state_helper
from shared.indicators._core import pivothigh


async def test_bb_state():
    """Test BB_State calculation and inspect BBW values"""

    from datetime import datetime, timezone

    provider = TimescaleProvider()

    # Get date range
    from sqlalchemy import text
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

    print(f"Total candles: {len(candles)}\n")

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

    # Call _calc_bb_state_helper directly and capture BBW
    print("Calling _calc_bb_state_helper...")

    # Manually reimplement to capture BBW values
    from shared.indicators._moving_averages import calc_sma
    from shared.indicators._core import pivothigh, pivotlow, crossover, rising, falling

    def calc_stddev(series, length):
        """Calculate standard deviation"""
        result = []
        for i in range(len(series)):
            if i < length - 1:
                result.append(float('nan'))
            else:
                window = series[i - length + 1:i + 1]
                mean = sum(window) / len(window)
                variance = sum((x - mean) ** 2 for x in window) / len(window)
                result.append(math.sqrt(variance))
        return result

    closes = [c["close"] for c in candles_dict]

    # BBW 1st (length=15, mult=1.5)
    bb_length = 15
    bb_mult = 1.5
    bb_ma_len = 100

    basis_list = calc_sma(closes, bb_length)
    stdev_list = calc_stddev(closes, bb_length)
    bbw_list = []

    for i in range(len(closes)):
        if math.isnan(basis_list[i]) or math.isnan(stdev_list[i]) or basis_list[i] == 0:
            bbw_list.append(float('nan'))
        else:
            upper = basis_list[i] + stdev_list[i] * bb_mult
            lower = basis_list[i] - stdev_list[i] * bb_mult
            bbw = (upper - lower) * 10 / basis_list[i]
            bbw_list.append(bbw)

    # Statistics
    valid_bbw = [b for b in bbw_list if not math.isnan(b)]

    print(f"\n📊 BBW Statistics:")
    print(f"Total BBW values: {len(bbw_list)}")
    print(f"Valid BBW values: {len(valid_bbw)}")
    print(f"NaN BBW values: {len(bbw_list) - len(valid_bbw)}")

    if valid_bbw:
        print(f"Min BBW: {min(valid_bbw):.6f}")
        print(f"Max BBW: {max(valid_bbw):.6f}")
        print(f"Mean BBW: {sum(valid_bbw) / len(valid_bbw):.6f}")
        print(f"Median BBW: {sorted(valid_bbw)[len(valid_bbw)//2]:.6f}")

        # Distribution
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

        # Show recent values
        print("\n🕒 Recent BBW values (last 30):")
        for i in range(len(bbw_list) - 30, len(bbw_list)):
            if not math.isnan(bbw_list[i]):
                print(f"  Index {i}: BBW={bbw_list[i]:.4f}, Close={closes[i]:.1f}")

        # Pivot high detection
        print("\n🔍 Pivot High Detection (left=20, right=10):")
        ph_list = pivothigh(bbw_list, 20, 10)
        pivots_found = [i for i, p in enumerate(ph_list) if p is not None]

        print(f"Pivots found: {len(pivots_found)}")

        if pivots_found:
            print("\nFirst 20 pivots:")
            for i in pivots_found[:20]:
                print(f"  Index {i}: BBW={ph_list[i]:.4f}")
        else:
            print("\n❌ NO PIVOTS FOUND!")

            # Manual check for potential pivots
            print("\n🔎 Manual pivot check (looking for local maxima):")

            pivot_left = 20
            pivot_right = 10

            manual_pivots = []
            for i in range(pivot_left, len(bbw_list) - pivot_right):
                current = bbw_list[i]

                if math.isnan(current):
                    continue

                # Check if this is higher than all neighbors
                is_highest = True
                for j in range(i - pivot_left, i + pivot_right + 1):
                    if j == i:
                        continue
                    if not math.isnan(bbw_list[j]) and bbw_list[j] >= current:
                        is_highest = False
                        break

                if is_highest:
                    manual_pivots.append((i, current))

            if manual_pivots:
                print(f"Found {len(manual_pivots)} local maxima:")
                for i, bbw in manual_pivots[:20]:
                    print(f"  Index {i}: BBW={bbw:.4f}")
            else:
                print("❌ No local maxima found in entire dataset!")
                print("\nThis confirms: BBW values are extremely smooth with no volatility spikes.")
                print("Let's check BBW volatility:")

                # Calculate BBW changes
                changes = []
                for i in range(1, len(valid_bbw)):
                    change = abs(valid_bbw[i] - valid_bbw[i-1])
                    changes.append(change)

                if changes:
                    avg_change = sum(changes) / len(changes)
                    max_change = max(changes)
                    mean_bbw = sum(valid_bbw) / len(valid_bbw)

                    print(f"\nBBW Volatility:")
                    print(f"  Average change: {avg_change:.6f}")
                    print(f"  Max change: {max_change:.6f}")
                    print(f"  Change/Mean ratio: {avg_change / mean_bbw:.4f}")
                    print(f"  Max change/Mean ratio: {max_change / mean_bbw:.4f}")

    else:
        print("❌ NO VALID BBW VALUES!")


if __name__ == "__main__":
    asyncio.run(test_bb_state())
