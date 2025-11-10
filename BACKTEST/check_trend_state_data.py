#!/usr/bin/env python3
"""
Check trend_state data in TimescaleDB
"""
import asyncio
from datetime import datetime, timezone
from sqlalchemy import text
from BACKTEST.data.timescale_provider import TimescaleProvider

async def main():
    provider = TimescaleProvider()
    session = await provider._get_session()

    print("\n=== 최근 20개 데이터 (trend_state 포함) ===")
    query = text("""
        SELECT
            time,
            symbol,
            close,
            rsi,
            trend_state,
            CASE
                WHEN trend_state IS NULL THEN 'NULL'
                ELSE trend_state::text
            END as trend_state_display
        FROM okx_candles_15m
        WHERE symbol = 'BTCUSDT'
        ORDER BY time DESC
        LIMIT 20
    """)

    result = await session.execute(query)
    rows = result.fetchall()

    print(f"\n{'Time':<20} {'Close':>10} {'RSI':>8} {'Trend State':>12}")
    print("-" * 60)
    for row in rows:
        time_str = row[0].strftime('%Y-%m-%d %H:%M')
        close = f"{row[2]:.2f}"
        rsi = f"{row[3]:.2f}" if row[3] is not None else "NULL"
        trend = row[5]
        print(f"{time_str:<20} {close:>10} {rsi:>8} {trend:>12}")

    print("\n\n=== trend_state가 채워진 데이터 10개 ===")
    query2 = text("""
        SELECT
            time,
            close,
            rsi,
            trend_state
        FROM okx_candles_15m
        WHERE symbol = 'BTCUSDT'
          AND trend_state IS NOT NULL
        ORDER BY time DESC
        LIMIT 10
    """)

    result = await session.execute(query2)
    rows = result.fetchall()

    print(f"\n{'Time':<20} {'Close':>10} {'RSI':>8} {'Trend':>8}")
    print("-" * 50)
    for row in rows:
        time_str = row[0].strftime('%Y-%m-%d %H:%M')
        close = f"{row[1]:.2f}"
        rsi = f"{row[2]:.2f}" if row[2] is not None else "NULL"
        trend = row[3]
        print(f"{time_str:<20} {close:>10} {rsi:>8} {trend:>8}")

    print("\n\n=== trend_state가 NULL인 데이터 10개 ===")
    query3 = text("""
        SELECT
            time,
            close,
            rsi,
            trend_state
        FROM okx_candles_15m
        WHERE symbol = 'BTCUSDT'
          AND trend_state IS NULL
        ORDER BY time DESC
        LIMIT 10
    """)

    result = await session.execute(query3)
    rows = result.fetchall()

    print(f"\n{'Time':<20} {'Close':>10} {'RSI':>8} {'Trend':>8}")
    print("-" * 50)
    for row in rows:
        time_str = row[0].strftime('%Y-%m-%d %H:%M')
        close = f"{row[1]:.2f}"
        rsi = f"{row[2]:.2f}" if row[2] is not None else "NULL"
        trend = "NULL" if row[3] is None else str(row[3])
        print(f"{time_str:<20} {close:>10} {rsi:>8} {trend:>8}")

    print("\n\n=== 백테스트 기간 (2025-08-30 ~ 2025-11-06) 통계 ===")
    query4 = text("""
        SELECT
            COUNT(*) as total_rows,
            COUNT(trend_state) as non_null_trend_state,
            COUNT(*) - COUNT(trend_state) as null_trend_state,
            ROUND(100.0 * COUNT(trend_state) / COUNT(*), 2) as filled_percent
        FROM okx_candles_15m
        WHERE symbol = 'BTCUSDT'
          AND time >= '2025-08-30 00:00:00'::timestamp
          AND time <= '2025-11-06 23:59:59'::timestamp
    """)

    result = await session.execute(query4)
    row = result.fetchone()
    print(f"Total rows: {row[0]}")
    print(f"Non-NULL trend_state: {row[1]}")
    print(f"NULL trend_state: {row[2]}")
    print(f"Filled percent: {row[3]}%")

    print("\n\n=== 전체 BTCUSDT 데이터 통계 ===")
    query5 = text("""
        SELECT
            COUNT(*) as total_rows,
            COUNT(trend_state) as non_null_trend_state,
            COUNT(*) - COUNT(trend_state) as null_trend_state,
            ROUND(100.0 * COUNT(trend_state) / COUNT(*), 2) as filled_percent,
            MIN(time) as earliest_time,
            MAX(time) as latest_time
        FROM okx_candles_15m
        WHERE symbol = 'BTCUSDT'
    """)

    result = await session.execute(query5)
    row = result.fetchone()
    print(f"Total rows: {row[0]}")
    print(f"Non-NULL trend_state: {row[1]}")
    print(f"NULL trend_state: {row[2]}")
    print(f"Filled percent: {row[3]}%")
    print(f"Earliest data: {row[4]}")
    print(f"Latest data: {row[5]}")

    await provider.close()

if __name__ == "__main__":
    asyncio.run(main())
