#!/usr/bin/env python3
"""
Analyze why no entry signals are generated.
"""
import asyncio
from datetime import datetime
import pandas as pd
from BACKTEST.data import TimescaleProvider


async def main():
    provider = TimescaleProvider()

    symbol = "BTC/USDT:USDT"
    timeframe = "15m"
    start_date = datetime.fromisoformat("2025-09-06T00:00:00+00:00")
    end_date = datetime.fromisoformat("2025-11-06T23:59:59+00:00")

    rsi_overbought = 70.0

    print("=" * 70)
    print(f"Analyzing signals for {symbol} SHORT strategy")
    print(f"Period: {start_date} to {end_date}")
    print(f"RSI Overbought: {rsi_overbought}")
    print("Entry option: 돌파 (crossover)")
    print("=" * 70)

    try:
        candles = await provider.get_candles(
            symbol, timeframe, start_date, end_date
        )

        print(f"\nTotal candles: {len(candles)}")

        # Check for RSI crossover signals
        rsi_crossovers = 0
        for i in range(1, len(candles)):
            prev_rsi = candles[i-1].rsi
            curr_rsi = candles[i].rsi

            if prev_rsi and curr_rsi:
                # SHORT: RSI crosses above overbought (돌파)
                if prev_rsi < rsi_overbought and curr_rsi >= rsi_overbought:
                    rsi_crossovers += 1
                    if rsi_crossovers <= 5:  # Show first 5
                        print(f"\nRSI crossover #{rsi_crossovers}:")
                        print(f"  Time: {candles[i].timestamp}")
                        print(f"  Prev RSI: {prev_rsi:.2f} -> Curr RSI: {curr_rsi:.2f}")
                        print(f"  Price: {candles[i].close:.2f}")
                        print(f"  EMA: {candles[i].ema}, SMA: {candles[i].sma}")

        print(f"\n{'='*70}")
        print(f"Total RSI crossovers (70 up): {rsi_crossovers}")

        # Analyze RSI distribution
        rsi_values = [c.rsi for c in candles if c.rsi]
        if rsi_values:
            print(f"\nRSI Statistics:")
            print(f"  Min: {min(rsi_values):.2f}")
            print(f"  Max: {max(rsi_values):.2f}")
            print(f"  Mean: {sum(rsi_values)/len(rsi_values):.2f}")
            print(f"  Above 70: {sum(1 for r in rsi_values if r > 70)} candles ({sum(1 for r in rsi_values if r > 70)/len(rsi_values)*100:.1f}%)")

    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await provider.close()


if __name__ == "__main__":
    asyncio.run(main())
