#!/usr/bin/env python3
"""
btc_usdt 테이블의 전체 데이터 범위 확인
"""

import asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

DB_URL = "postgresql+asyncpg://tradeuser:SecurePassword123@158.247.218.188:5432/candlesdb"


async def check_data_range():
    """데이터 범위 확인"""

    engine = create_async_engine(DB_URL, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        print("=" * 80)
        print("📊 btc_usdt 테이블 데이터 범위 분석")
        print("=" * 80)
        print()

        # 1. 5m 타임프레임 전체 범위
        query = text("""
            SELECT
                MIN(time) as first_candle,
                MAX(time) as last_candle,
                COUNT(*) as total_count
            FROM btc_usdt
            WHERE timeframe = '5m'
        """)
        result = await session.execute(query)
        row = result.fetchone()

        print(f"🔍 5m 타임프레임 전체 데이터:")
        print(f"   - 첫 캔들: {row.first_candle}")
        print(f"   - 마지막 캔들: {row.last_candle}")
        print(f"   - 총 캔들 수: {row.total_count:,}개")
        print()

        # 2. 11월 데이터 확인
        query_nov = text("""
            SELECT
                DATE(time) as date,
                COUNT(*) as count,
                MIN(time) as first_candle,
                MAX(time) as last_candle
            FROM btc_usdt
            WHERE timeframe = '5m'
                AND time >= '2025-11-01 00:00:00+00'
                AND time <= '2025-11-30 23:59:59+00'
            GROUP BY DATE(time)
            ORDER BY date
        """)
        result = await session.execute(query_nov)
        rows = result.fetchall()

        print(f"📅 11월 날짜별 데이터:")
        if rows:
            print(f"   {'날짜':<12} {'캔들 개수':<10} {'첫 캔들':<20} {'마지막 캔들'}")
            print(f"   {'-'*75}")
            for row in rows:
                print(f"   {row.date} {row.count:>8}개 {row.first_candle}  {row.last_candle}")
        else:
            print(f"   ⚠️ 11월 데이터가 없습니다!")

        print()

        # 3. 11월 13일 데이터 확인 (첫 진입일)
        query_nov13 = text("""
            SELECT
                time,
                close,
                rsi14,
                ema7,
                ma20,
                trend_state
            FROM btc_usdt
            WHERE timeframe = '5m'
                AND time >= '2025-11-13 00:00:00+00'
                AND time <= '2025-11-13 23:59:59+00'
            ORDER BY time
            LIMIT 20
        """)
        result = await session.execute(query_nov13)
        rows = result.fetchall()

        print(f"🎯 11월 13일 샘플 데이터 (첫 진입일):")
        if rows:
            print(f"   {'시간':<20} {'Close':<12} {'RSI14':<8} {'EMA7':<12} {'MA20':<12} {'Trend'}")
            print(f"   {'-'*80}")

            for row in rows[:10]:
                rsi_str = f"{row.rsi14:.2f}" if row.rsi14 is not None else "NULL"
                ema_str = f"{row.ema7:.2f}" if row.ema7 is not None else "NULL"
                ma_str = f"{row.ma20:.2f}" if row.ma20 is not None else "NULL"
                trend_str = str(row.trend_state) if row.trend_state is not None else "NULL"

                print(f"   {row.time} {row.close:>10.2f}  {rsi_str:<8} {ema_str:<12} {ma_str:<12} {trend_str}")
        else:
            print(f"   ⚠️ 11월 13일 데이터가 없습니다!")

        print()

        # 4. 각 타임프레임별 데이터 확인
        query_tf = text("""
            SELECT
                timeframe,
                COUNT(*) as count,
                MIN(time) as first_candle,
                MAX(time) as last_candle
            FROM btc_usdt
            GROUP BY timeframe
            ORDER BY timeframe
        """)
        result = await session.execute(query_tf)
        rows = result.fetchall()

        print(f"📊 타임프레임별 데이터:")
        print(f"   {'Timeframe':<12} {'캔들 개수':<15} {'첫 캔들':<25} {'마지막 캔들'}")
        print(f"   {'-'*85}")
        for row in rows:
            print(f"   {row.timeframe:<12} {row.count:>12,}개  {row.first_candle}  {row.last_candle}")

        print()
        print("=" * 80)

    await engine.dispose()


async def main():
    try:
        await check_data_range()
    except Exception as e:
        print(f"❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
