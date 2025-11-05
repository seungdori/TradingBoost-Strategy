"""Test TimescaleProvider symbol normalization"""
import asyncio
from datetime import datetime, timezone
from BACKTEST.data.timescale_provider import TimescaleProvider

async def test_provider():
    provider = TimescaleProvider()

    # Test symbol normalization
    test_symbols = [
        "BTC/USDT:USDT",
        "BTC-USDT-SWAP",
        "BTCUSDT"
    ]

    print("Symbol Normalization Tests:")
    for symbol in test_symbols:
        normalized = provider._normalize_symbol(symbol)
        print(f"  {symbol} -> {normalized}")

    print("\n" + "="*50)

    # Test data validation
    symbol = "BTC/USDT:USDT"
    timeframe = "15m"
    start_date = datetime(2025, 9, 4, 0, 0, 0, tzinfo=timezone.utc)
    end_date = datetime(2025, 11, 4, 23, 59, 59, tzinfo=timezone.utc)

    print(f"\nData Validation Test:")
    print(f"  Symbol: {symbol}")
    print(f"  Timeframe: {timeframe}")
    print(f"  Start: {start_date}")
    print(f"  End: {end_date}")

    try:
        validation = await provider.validate_data_availability(
            symbol, timeframe, start_date, end_date
        )
        print(f"\nValidation Result:")
        for key, value in validation.items():
            print(f"  {key}: {value}")
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await provider.close()

if __name__ == "__main__":
    asyncio.run(test_provider())
