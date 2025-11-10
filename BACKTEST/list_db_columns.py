#!/usr/bin/env python3
"""List all columns in okx_candles_15m table"""
import asyncio
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import text
from BACKTEST.data.timescale_provider import TimescaleProvider


async def list_columns():
    provider = TimescaleProvider()
    session = await provider._get_session()

    query = text("""
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_name = 'okx_candles_15m'
        ORDER BY ordinal_position
    """)

    result = await session.execute(query)
    rows = result.fetchall()

    print(f"Columns in okx_candles_15m table ({len(rows)} total):")
    print("=" * 60)
    for col_name, data_type in rows:
        print(f"  {col_name:30s} {data_type}")


if __name__ == "__main__":
    asyncio.run(list_columns())
