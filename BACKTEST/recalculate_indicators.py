#!/usr/bin/env python3
"""
Script to recalculate ALL indicators and trend_state for BTC-USDT-SWAP 15m data.

This will recalculate all historical data in TimescaleDB with proper MTF (Multi-Timeframe) logic.

Usage:
    python recalculate_indicators.py
"""

import asyncio
import httpx
from datetime import datetime, timedelta, timezone


async def recalculate_indicators():
    """Call the recalculate-indicators API endpoint."""

    # API endpoint
    base_url = "http://localhost:8013"  # BACKTEST service port
    endpoint = f"{base_url}/backtest/recalculate-indicators"

    # Request data
    # Recalculate ALL data (None = all available data in DB)
    request_data = {
        "symbol": "BTC-USDT-SWAP",
        "timeframe": "15m",
        "start_date": None,
        "end_date": None
    }

    print(f"Calling API: {endpoint}")
    print(f"Request data: {request_data}")
    print("=" * 80)

    async with httpx.AsyncClient(timeout=1800.0) as client:  # 30 minute timeout for full recalculation
        try:
            response = await client.post(endpoint, json=request_data)
            response.raise_for_status()

            result = response.json()
            print("\n✅ Success!")
            print("=" * 80)
            print(f"Status: {result.get('status')}")
            print(f"Message: {result.get('message')}")
            print(f"Symbol: {result.get('symbol')}")
            print(f"Timeframe: {result.get('timeframe')}")
            print(f"Candles processed: {result.get('candles_processed')}")
            print(f"Start date: {result.get('start_date')}")
            print(f"End date: {result.get('end_date')}")
            print("=" * 80)

            return result

        except httpx.HTTPStatusError as e:
            print(f"\n❌ HTTP Error: {e.response.status_code}")
            print(f"Response: {e.response.text}")
            raise
        except Exception as e:
            print(f"\n❌ Error: {e}")
            raise


if __name__ == "__main__":
    print("🚀 Starting indicator recalculation...")
    print("=" * 80)

    result = asyncio.run(recalculate_indicators())

    print("\n✅ Recalculation complete!")
