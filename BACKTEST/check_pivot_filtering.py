#!/usr/bin/env python3
"""
Check how many pivot highs pass the bbw > ma filter
"""
import asyncio
import sys
from pathlib import Path
import math

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from BACKTEST.data.timescale_provider import TimescaleProvider
from shared.indicators._moving_averages import calc_sma
from shared.indicators._core import pivothigh


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


async def check_filtering():
    """Check pivot filtering logic"""

    from datetime import datetime, timezone
    from sqlalchemy import text

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

    closes = [c["close"] for c in candles_dict]

    # Calculate BBW
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

    # Calculate BBW MA
    bbw_ma = calc_sma(bbw_list, bb_ma_len)

    # Check when MA becomes valid
    first_valid_ma = next((i for i, ma in enumerate(bbw_ma) if not math.isnan(ma)), None)
    print(f"\n📍 First valid BBW_MA index: {first_valid_ma}")

    if first_valid_ma:
        print(f"   MA becomes valid at index {first_valid_ma} (needs {bb_ma_len} bars)")
        valid_ma_count = sum(1 for ma in bbw_ma if not math.isnan(ma))
        print(f"   Total valid MA values: {valid_ma_count}/{len(bbw_ma)} ({valid_ma_count/len(bbw_ma)*100:.1f}%)")
    else:
        print(f"   ❌ ALL MA VALUES ARE NaN!")

    # Detect pivot highs
    ph_list = pivothigh(bbw_list, 20, 10)

    # Count pivots
    total_pivots = sum(1 for p in ph_list if p is not None)
    print(f"📊 Total pivot highs detected: {total_pivots}")

    # Show BBW vs MA comparison for pivots
    print("\n🔍 BBW vs MA for pivot highs (first 30 pivots):")
    pivot_count = 0
    for i in range(len(ph_list)):
        if ph_list[i] is not None:
            bbw_val = bbw_list[i]
            ma_val = bbw_ma[i]

            if pivot_count < 30:
                print(f"  Index {i}: BBW={bbw_val:.4f}, MA={ma_val:.4f}, Pass={bbw_val > ma_val}")
                pivot_count += 1

    # Count pivots that pass filter
    filtered_pivots = 0
    pivot_details = []

    for i in range(len(ph_list)):
        if ph_list[i] is not None:
            bbw_val = bbw_list[i]
            ma_val = bbw_ma[i]

            if not (ma_val is None or math.isnan(ma_val) or math.isnan(bbw_val)):
                if bbw_val > ma_val:
                    filtered_pivots += 1
                    pivot_details.append((i, bbw_val, ma_val, bbw_val - ma_val))

    print(f"✅ Pivots passing bbw > ma filter: {filtered_pivots} ({filtered_pivots/total_pivots*100:.1f}%)")
    print(f"❌ Pivots filtered out: {total_pivots - filtered_pivots} ({(total_pivots-filtered_pivots)/total_pivots*100:.1f}%)")

    if pivot_details:
        print("\n🔍 Sample of pivots that passed filter (first 20):")
        for i, bbw, ma, diff in pivot_details[:20]:
            print(f"  Index {i}: BBW={bbw:.4f}, MA={ma:.4f}, Diff={diff:.4f}")

        # Calculate what buzz would be with these pivots
        print("\n📈 Simulating ph_array accumulation:")
        ph_array = []
        array_size = 50

        for i in range(len(closes)):
            bbw_val = bbw_list[i]
            ma_val = bbw_ma[i]

            if not (ma_val is None or math.isnan(ma_val) or math.isnan(bbw_val)):
                if bbw_val > ma_val and ph_list[i] is not None:
                    ph_array.append(ph_list[i])
                    if len(ph_array) > array_size:
                        ph_array.pop(0)

        print(f"Final ph_array length: {len(ph_array)}")

        if len(ph_array) > 0:
            ph_avg = sum(ph_array) / len(ph_array)
            buzz = ph_avg * 0.7
            print(f"Final ph_avg: {ph_avg:.4f}")
            print(f"Final buzz: {buzz:.4f}")

            # Compare with recent BBW
            recent_bbw = [b for b in bbw_list[-100:] if not math.isnan(b)]
            max_recent = max(recent_bbw)
            mean_recent = sum(recent_bbw) / len(recent_bbw)

            print(f"\nRecent BBW stats (last 100):")
            print(f"  Max: {max_recent:.4f}")
            print(f"  Mean: {mean_recent:.4f}")
            print(f"  buzz/max ratio: {buzz / max_recent:.2f}")
            print(f"  buzz/mean ratio: {buzz / mean_recent:.2f}")

            if buzz > max_recent:
                print(f"\n❌ buzz ({buzz:.4f}) > max recent BBW ({max_recent:.4f})")
                print("   This means NO crossovers will occur!")
            else:
                print(f"\n✅ buzz ({buzz:.4f}) < max recent BBW ({max_recent:.4f})")
                print("   Crossovers are possible")

        else:
            print("❌ ph_array is empty after full accumulation!")
            print("   This means the default buzz = 5 * 0.7 = 3.5 will be used")

    else:
        print("\n❌ NO pivots passed the bbw > ma filter!")
        print("   This means ph_array will always be empty")
        print("   And buzz will always be the default: 5 * 0.7 = 3.5")


if __name__ == "__main__":
    asyncio.run(check_filtering())
