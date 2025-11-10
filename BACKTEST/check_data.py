#!/usr/bin/env python3
"""
Check TimescaleDB data availability for backtest period.
"""
import asyncio
from datetime import datetime
from BACKTEST.data import TimescaleProvider


async def main():
    provider = TimescaleProvider()

    # User's original test period
    symbol = "BTC/USDT:USDT"
    timeframe = "15m"
    start_date = datetime.fromisoformat("2025-09-06T00:00:00+00:00")
    end_date = datetime.fromisoformat("2025-11-06T23:59:59+00:00")

    print("=" * 70)
    print(f"Checking data availability for {symbol}")
    print(f"Period: {start_date} to {end_date}")
    print(f"Timeframe: {timeframe}")
    print("=" * 70)

    try:
        # Validate data availability
        validation = await provider.validate_data_availability(
            symbol, timeframe, start_date, end_date
        )

        print(f"\nValidation result:")
        print(f"  Available: {validation['available']}")
        print(f"  Coverage: {validation['coverage']*100:.1f}%")
        print(f"  Data source: {validation['data_source']}")
        print(f"  Total candles expected: {validation.get('total_candles_expected', 'N/A')}")
        print(f"  Total candles found: {validation.get('total_candles_found', 'N/A')}")

        # Fetch actual candles
        print(f"\n{'='*70}")
        print("Fetching candles...")
        candles = await provider.get_candles(
            symbol, timeframe, start_date, end_date
        )

        print(f"Total candles fetched: {len(candles)}")

        if candles:
            print(f"\nFirst candle:")
            first = candles[0]
            print(f"  Time: {first.timestamp}")
            print(f"  Close: {first.close}")
            print(f"  RSI: {first.rsi}")
            print(f"  ATR: {first.atr}")
            print(f"  EMA: {first.ema}")
            print(f"  SMA: {first.sma}")

            print(f"\nLast candle:")
            last = candles[-1]
            print(f"  Time: {last.timestamp}")
            print(f"  Close: {last.close}")
            print(f"  RSI: {last.rsi}")
            print(f"  ATR: {last.atr}")
            print(f"  EMA: {last.ema}")
            print(f"  SMA: {last.sma}")
        else:
            print("\n❌ NO CANDLES RETURNED!")

    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await provider.close()


if __name__ == "__main__":
    asyncio.run(main())
