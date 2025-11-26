#!/usr/bin/env python3
"""
trend_state 상세 분석 및 진입 조건 확인
"""

import asyncio
from datetime import datetime, timezone
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

DB_URL = "postgresql+asyncpg://tradeuser:SecurePassword123@158.247.218.188:5432/candlesdb"


async def analyze_trend_state_detailed():
    """trend_state 상세 분석"""

    engine = create_async_engine(DB_URL, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        print("=" * 80)
        print("🔍 Trend State 상세 분석 (11/13 09:20 이후)")
        print("=" * 80)
        print()

        # 1. 전체 trend_state 분포
        query_trend_dist = text("""
            SELECT
                trend_state,
                COUNT(*) as count,
                COUNT(*) * 100.0 / SUM(COUNT(*)) OVER() as percentage
            FROM btc_usdt
            WHERE timeframe = '5m'
                AND time > '2025-11-13 09:20:00+00'
                AND time <= '2025-11-25 23:59:59+00'
            GROUP BY trend_state
            ORDER BY trend_state DESC NULLS LAST
        """)
        result = await session.execute(query_trend_dist)
        trend_dist = result.fetchall()

        print("📊 1. Trend State 전체 분포")
        print(f"   {'Trend State':<15} {'개수':<10} {'비율'}")
        print(f"   {'-'*40}")
        for row in trend_dist:
            trend_label = {
                2: "강한 상승 (2)",
                1: "상승 (1)",
                0: "중립 (0)",
                -1: "하락 (-1)",
                -2: "강한 하락 (-2)",
                None: "NULL"
            }.get(row.trend_state, f"Unknown ({row.trend_state})")
            print(f"   {trend_label:<15} {row.count:>8}개  {row.percentage:>6.2f}%")
        print()

        # 2. RSI 극값과 trend_state 조합 분석
        query_rsi_trend = text("""
            SELECT
                CASE
                    WHEN rsi14 <= 30 THEN 'RSI ≤ 30 (LONG 후보)'
                    WHEN rsi14 >= 70 THEN 'RSI ≥ 70 (SHORT 후보)'
                END as rsi_condition,
                trend_state,
                COUNT(*) as count
            FROM btc_usdt
            WHERE timeframe = '5m'
                AND time > '2025-11-13 09:20:00+00'
                AND time <= '2025-11-25 23:59:59+00'
                AND (rsi14 <= 30 OR rsi14 >= 70)
            GROUP BY
                CASE
                    WHEN rsi14 <= 30 THEN 'RSI ≤ 30 (LONG 후보)'
                    WHEN rsi14 >= 70 THEN 'RSI ≥ 70 (SHORT 후보)'
                END,
                trend_state
            ORDER BY rsi_condition, trend_state DESC NULLS LAST
        """)
        result = await session.execute(query_rsi_trend)
        rsi_trend_combo = result.fetchall()

        print("🎯 2. RSI 극값 + Trend State 조합")
        print(f"   {'RSI 조건':<25} {'Trend':<15} {'개수':<10} {'진입 가능?'}")
        print(f"   {'-'*65}")
        for row in rsi_trend_combo:
            trend_label = {
                2: "강한 상승 (2)",
                1: "상승 (1)",
                0: "중립 (0)",
                -1: "하락 (-1)",
                -2: "강한 하락 (-2)",
                None: "NULL"
            }.get(row.trend_state, f"Unknown ({row.trend_state})")

            # 진입 가능 여부 판단
            if row.rsi_condition == 'RSI ≤ 30 (LONG 후보)':
                # LONG 진입: trend_state = -2일 때 불가
                can_enter = "❌ 불가" if row.trend_state == -2 else "✅ 가능"
            else:  # RSI ≥ 70 (SHORT 후보)
                # SHORT 진입: trend_state = 2일 때 불가
                can_enter = "❌ 불가" if row.trend_state == 2 else "✅ 가능"

            print(f"   {row.rsi_condition:<25} {trend_label:<15} {row.count:>8}개  {can_enter}")
        print()

        # 3. RSI 돌파 조건 확인 (prev_rsi와 current_rsi 비교)
        query_rsi_breakthrough = text("""
            WITH candle_with_prev AS (
                SELECT
                    time,
                    close,
                    rsi14,
                    LAG(rsi14) OVER (ORDER BY time) as prev_rsi,
                    trend_state
                FROM btc_usdt
                WHERE timeframe = '5m'
                    AND time > '2025-11-13 09:20:00+00'
                    AND time <= '2025-11-25 23:59:59+00'
            )
            SELECT
                COUNT(*) FILTER (
                    WHERE prev_rsi > 30 AND rsi14 <= 30
                ) as long_breakthrough_count,
                COUNT(*) FILTER (
                    WHERE prev_rsi > 30 AND rsi14 <= 30 AND trend_state = -2
                ) as long_breakthrough_blocked,
                COUNT(*) FILTER (
                    WHERE prev_rsi > 30 AND rsi14 <= 30 AND trend_state != -2
                ) as long_breakthrough_allowed,
                COUNT(*) FILTER (
                    WHERE prev_rsi < 70 AND rsi14 >= 70
                ) as short_breakthrough_count,
                COUNT(*) FILTER (
                    WHERE prev_rsi < 70 AND rsi14 >= 70 AND trend_state = 2
                ) as short_breakthrough_blocked,
                COUNT(*) FILTER (
                    WHERE prev_rsi < 70 AND rsi14 >= 70 AND trend_state != 2
                ) as short_breakthrough_allowed
            FROM candle_with_prev
        """)
        result = await session.execute(query_rsi_breakthrough)
        breakthrough = result.fetchone()

        print("🚀 3. RSI 돌파 조건 분석")
        print(f"   LONG 진입 (RSI 30 돌파):")
        print(f"      전체 돌파: {breakthrough.long_breakthrough_count}회")
        print(f"      ❌ 차단됨 (trend=-2): {breakthrough.long_breakthrough_blocked}회")
        print(f"      ✅ 진입 가능: {breakthrough.long_breakthrough_allowed}회")
        print()
        print(f"   SHORT 진입 (RSI 70 돌파):")
        print(f"      전체 돌파: {breakthrough.short_breakthrough_count}회")
        print(f"      ❌ 차단됨 (trend=2): {breakthrough.short_breakthrough_blocked}회")
        print(f"      ✅ 진입 가능: {breakthrough.short_breakthrough_allowed}회")
        print()

        # 4. 진입 가능했던 구체적 사례 (RSI 돌파 + trend 조건 OK)
        query_entry_candidates = text("""
            WITH candle_with_prev AS (
                SELECT
                    time,
                    close,
                    rsi14,
                    LAG(rsi14) OVER (ORDER BY time) as prev_rsi,
                    trend_state
                FROM btc_usdt
                WHERE timeframe = '5m'
                    AND time > '2025-11-13 09:20:00+00'
                    AND time <= '2025-11-25 23:59:59+00'
            )
            SELECT
                time,
                close,
                prev_rsi,
                rsi14,
                trend_state,
                CASE
                    WHEN prev_rsi > 30 AND rsi14 <= 30 THEN 'LONG'
                    WHEN prev_rsi < 70 AND rsi14 >= 70 THEN 'SHORT'
                END as signal_type
            FROM candle_with_prev
            WHERE (
                (prev_rsi > 30 AND rsi14 <= 30 AND trend_state != -2)
                OR
                (prev_rsi < 70 AND rsi14 >= 70 AND trend_state != 2)
            )
            ORDER BY time
            LIMIT 20
        """)
        result = await session.execute(query_entry_candidates)
        entry_candidates = result.fetchall()

        print("✅ 4. 진입 가능했던 구체적 사례 (RSI 돌파 + Trend OK)")
        if entry_candidates:
            print(f"   {'시간':<20} {'Close':<12} {'Prev RSI':<10} {'RSI':<8} {'Trend':<8} {'신호'}")
            print(f"   {'-'*75}")
            for row in entry_candidates:
                trend_label = {
                    2: "강상승",
                    1: "상승",
                    0: "중립",
                    -1: "하락",
                    -2: "강하락",
                    None: "NULL"
                }.get(row.trend_state, "?")
                print(f"   {row.time} {row.close:>10.2f}  {row.prev_rsi:>8.2f}  {row.rsi14:>6.2f}  {trend_label:<8} {row.signal_type}")
        else:
            print(f"   ⚠️ 진입 조건을 충족하는 캔들이 없습니다!")
        print()

        # 5. 날짜별 진입 가능 기회 분석
        query_daily_opportunities = text("""
            WITH candle_with_prev AS (
                SELECT
                    time,
                    DATE(time) as date,
                    close,
                    rsi14,
                    LAG(rsi14) OVER (ORDER BY time) as prev_rsi,
                    trend_state
                FROM btc_usdt
                WHERE timeframe = '5m'
                    AND time > '2025-11-13 09:20:00+00'
                    AND time <= '2025-11-25 23:59:59+00'
            )
            SELECT
                date,
                COUNT(*) FILTER (
                    WHERE prev_rsi > 30 AND rsi14 <= 30 AND trend_state != -2
                ) as long_opportunities,
                COUNT(*) FILTER (
                    WHERE prev_rsi < 70 AND rsi14 >= 70 AND trend_state != 2
                ) as short_opportunities,
                COUNT(*) FILTER (
                    WHERE prev_rsi > 30 AND rsi14 <= 30 AND trend_state = -2
                ) as long_blocked,
                COUNT(*) FILTER (
                    WHERE prev_rsi < 70 AND rsi14 >= 70 AND trend_state = 2
                ) as short_blocked
            FROM candle_with_prev
            GROUP BY date
            ORDER BY date
        """)
        result = await session.execute(query_daily_opportunities)
        daily_opps = result.fetchall()

        print("📅 5. 날짜별 진입 기회 분석")
        print(f"   {'날짜':<12} {'LONG 기회':<12} {'SHORT 기회':<13} {'LONG 차단':<12} {'SHORT 차단'}")
        print(f"   {'-'*65}")
        for row in daily_opps:
            if row.long_opportunities > 0 or row.short_opportunities > 0 or row.long_blocked > 0 or row.short_blocked > 0:
                print(f"   {row.date} {row.long_opportunities:>10}회  {row.short_opportunities:>11}회  {row.long_blocked:>10}회  {row.short_blocked:>11}회")
        print()

        print("=" * 80)
        print("💡 분석 결론")
        print("=" * 80)
        print(f"✅ RSI 돌파 진입 가능: LONG {breakthrough.long_breakthrough_allowed}회 + SHORT {breakthrough.short_breakthrough_allowed}회")
        print(f"❌ Trend로 차단됨: LONG {breakthrough.long_breakthrough_blocked}회 + SHORT {breakthrough.short_breakthrough_blocked}회")
        print()

    await engine.dispose()


async def main():
    try:
        await analyze_trend_state_detailed()
    except Exception as e:
        print(f"❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
