#!/usr/bin/env python3
"""
특정 시점의 진입 조건 확인
"""

import asyncio
from datetime import datetime, timezone
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

DB_URL = "postgresql+asyncpg://tradeuser:SecurePassword123@158.247.218.188:5432/candlesdb"


async def check_specific_signals():
    """진입 가능했던 시점의 실제 데이터 확인"""

    engine = create_async_engine(DB_URL, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        print("=" * 80)
        print("🔍 진입 가능했던 시점의 실제 데이터 확인")
        print("=" * 80)
        print()

        # 11월 13일 13:25 LONG 시그널 확인
        query = text("""
            WITH candle_with_prev AS (
                SELECT
                    time,
                    close,
                    rsi14,
                    LAG(rsi14) OVER (ORDER BY time) as prev_rsi,
                    trend_state,
                    ema7,
                    ma20,
                    atr
                FROM btc_usdt
                WHERE timeframe = '5m'
                    AND time >= '2025-11-13 13:20:00+00'
                    AND time <= '2025-11-13 13:30:00+00'
                ORDER BY time
            )
            SELECT * FROM candle_with_prev
        """)
        result = await session.execute(query)
        rows = result.fetchall()

        print("📅 11/13 13:20~13:30 (LONG 시그널 예상 시점)")
        print(f"   {'시간':<20} {'Close':<12} {'Prev RSI':<10} {'RSI':<8} {'Trend':<8} {'진입 조건'}")
        print(f"   {'-'*85}")

        for row in rows:
            trend_label = {
                2: "강상승",
                1: "상승",
                0: "중립",
                -1: "하락",
                -2: "강하락",
                None: "NULL"
            }.get(row.trend_state, "?")

            # 진입 조건 확인
            entry_check = ""
            if row.prev_rsi is not None and row.rsi14 is not None:
                # 돌파 조건: prev_rsi > 30 and rsi <= 30
                if row.prev_rsi > 30 and row.rsi14 <= 30:
                    if row.trend_state == -2:
                        entry_check = "❌ LONG 차단 (trend=-2)"
                    else:
                        entry_check = "✅ LONG 진입 가능!"

            prev_rsi_str = f"{row.prev_rsi:.2f}" if row.prev_rsi is not None else "N/A"
            rsi_str = f"{row.rsi14:.2f}" if row.rsi14 is not None else "N/A"

            print(f"   {row.time} {row.close:>10.2f}  {prev_rsi_str:>8}  {rsi_str:>6}  {trend_label:<8} {entry_check}")

        print()
        print()

        # 11월 14일 04:30 LONG 시그널 확인
        query2 = text("""
            WITH candle_with_prev AS (
                SELECT
                    time,
                    close,
                    rsi14,
                    LAG(rsi14) OVER (ORDER BY time) as prev_rsi,
                    trend_state
                FROM btc_usdt
                WHERE timeframe = '5m'
                    AND time >= '2025-11-14 04:25:00+00'
                    AND time <= '2025-11-14 04:35:00+00'
                ORDER BY time
            )
            SELECT * FROM candle_with_prev
        """)
        result = await session.execute(query2)
        rows = result.fetchall()

        print("📅 11/14 04:25~04:35 (LONG 시그널 예상 시점)")
        print(f"   {'시간':<20} {'Close':<12} {'Prev RSI':<10} {'RSI':<8} {'Trend':<8} {'진입 조건'}")
        print(f"   {'-'*85}")

        for row in rows:
            trend_label = {
                2: "강상승",
                1: "상승",
                0: "중립",
                -1: "하락",
                -2: "강하락",
                None: "NULL"
            }.get(row.trend_state, "?")

            entry_check = ""
            if row.prev_rsi is not None and row.rsi14 is not None:
                if row.prev_rsi > 30 and row.rsi14 <= 30:
                    if row.trend_state == -2:
                        entry_check = "❌ LONG 차단 (trend=-2)"
                    else:
                        entry_check = "✅ LONG 진입 가능!"

            prev_rsi_str = f"{row.prev_rsi:.2f}" if row.prev_rsi is not None else "N/A"
            rsi_str = f"{row.rsi14:.2f}" if row.rsi14 is not None else "N/A"

            print(f"   {row.time} {row.close:>10.2f}  {prev_rsi_str:>8}  {rsi_str:>6}  {trend_label:<8} {entry_check}")

        print()
        print()

        # 11월 23일 07:00 확인 (마지막 진입 가능 시점)
        query3 = text("""
            WITH candle_with_prev AS (
                SELECT
                    time,
                    close,
                    rsi14,
                    LAG(rsi14) OVER (ORDER BY time) as prev_rsi,
                    trend_state
                FROM btc_usdt
                WHERE timeframe = '5m'
                    AND time >= '2025-11-23 06:55:00+00'
                    AND time <= '2025-11-23 07:05:00+00'
                ORDER BY time
            )
            SELECT * FROM candle_with_prev
        """)
        result = await session.execute(query3)
        rows = result.fetchall()

        print("📅 11/23 06:55~07:05 (마지막 LONG 시그널 시점)")
        print(f"   {'시간':<20} {'Close':<12} {'Prev RSI':<10} {'RSI':<8} {'Trend':<8} {'진입 조건'}")
        print(f"   {'-'*85}")

        for row in rows:
            trend_label = {
                2: "강상승",
                1: "상승",
                0: "중립",
                -1: "하락",
                -2: "강하락",
                None: "NULL"
            }.get(row.trend_state, "?")

            entry_check = ""
            if row.prev_rsi is not None and row.rsi14 is not None:
                if row.prev_rsi > 30 and row.rsi14 <= 30:
                    if row.trend_state == -2:
                        entry_check = "❌ LONG 차단 (trend=-2)"
                    else:
                        entry_check = "✅ LONG 진입 가능!"

            prev_rsi_str = f"{row.prev_rsi:.2f}" if row.prev_rsi is not None else "N/A"
            rsi_str = f"{row.rsi14:.2f}" if row.rsi14 is not None else "N/A"

            print(f"   {row.time} {row.close:>10.2f}  {prev_rsi_str:>8}  {rsi_str:>6}  {trend_label:<8} {entry_check}")

        print()

    await engine.dispose()


async def main():
    try:
        await check_specific_signals()
    except Exception as e:
        print(f"❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
