#!/usr/bin/env python3
"""
11월 4일~12일 데이터 갭 분석 스크립트
"""

import asyncio
from datetime import datetime, timezone
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

# candlesdb 연결 (BTC 캔들 데이터)
DB_URL = "postgresql+asyncpg://tradeuser:SecurePassword123@158.247.218.188:5432/candlesdb"


async def analyze_data_gap():
    """11월 4일~12일 데이터 갭 분석"""

    engine = create_async_engine(DB_URL, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        print("=" * 80)
        print("📊 TimescaleDB 데이터 분석: BTC-USDT-SWAP 5m (2025-11-04 ~ 2025-11-12)")
        print("=" * 80)
        print()

        # 1. 전체 캔들 개수 확인
        query_total = text("""
            SELECT COUNT(*) as count
            FROM btc_usdt
            WHERE timeframe = '5m'
                AND time >= '2025-11-04 00:00:00+00'
                AND time <= '2025-11-12 23:59:59+00'
        """)
        result = await session.execute(query_total)
        total_count = result.scalar()

        # 기대 캔들 개수 계산 (9일 * 24시간 * 12캔들/시간)
        expected_count = 9 * 24 * 12
        coverage = (total_count / expected_count * 100) if expected_count > 0 else 0

        print(f"🔍 1. 전체 데이터 현황")
        print(f"   - 기대 캔들 개수: {expected_count}개 (9일 * 24h * 12/h)")
        print(f"   - 실제 캔들 개수: {total_count}개")
        print(f"   - 데이터 커버리지: {coverage:.1f}%")
        print()

        # 2. 날짜별 캔들 개수
        query_daily = text("""
            SELECT
                DATE(time) as date,
                COUNT(*) as count,
                MIN(time) as first_candle,
                MAX(time) as last_candle
            FROM btc_usdt
            WHERE timeframe = '5m'
                AND time >= '2025-11-04 00:00:00+00'
                AND time <= '2025-11-12 23:59:59+00'
            GROUP BY DATE(time)
            ORDER BY date
        """)
        result = await session.execute(query_daily)
        rows = result.fetchall()

        print(f"📅 2. 날짜별 캔들 개수")
        print(f"   {'날짜':<12} {'캔들 개수':<10} {'커버리지':<10} {'첫 캔들':<20} {'마지막 캔들'}")
        print(f"   {'-'*75}")

        for row in rows:
            daily_expected = 24 * 12  # 288 candles per day
            daily_coverage = (row.count / daily_expected * 100)
            print(f"   {row.date} {row.count:>8}개 {daily_coverage:>7.1f}%  {row.first_candle}  {row.last_candle}")

        print()

        # 3. NULL 지표 확인
        query_nulls = text("""
            SELECT
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE rsi14 IS NULL) as rsi_null,
                COUNT(*) FILTER (WHERE atr IS NULL) as atr_null,
                COUNT(*) FILTER (WHERE ema7 IS NULL) as ema_null,
                COUNT(*) FILTER (WHERE ma20 IS NULL) as ma20_null,
                COUNT(*) FILTER (WHERE trend_state IS NULL) as trend_null
            FROM btc_usdt
            WHERE timeframe = '5m'
                AND time >= '2025-11-04 00:00:00+00'
                AND time <= '2025-11-12 23:59:59+00'
        """)
        result = await session.execute(query_nulls)
        row = result.fetchone()

        print(f"🔍 3. NULL 지표 분석")
        print(f"   - 전체 캔들: {row.total}개")
        print(f"   - RSI14 NULL: {row.rsi_null}개 ({row.rsi_null/row.total*100:.1f}%)")
        print(f"   - ATR NULL: {row.atr_null}개 ({row.atr_null/row.total*100:.1f}%)")
        print(f"   - EMA7 NULL: {row.ema_null}개 ({row.ema_null/row.total*100:.1f}%)")
        print(f"   - MA20 NULL: {row.ma20_null}개 ({row.ma20_null/row.total*100:.1f}%)")
        print(f"   - Trend State NULL: {row.trend_null}개 ({row.trend_null/row.total*100:.1f}%)")
        print()

        # 4. 샘플 데이터 확인 (첫 10개 캔들)
        query_sample = text("""
            SELECT
                time,
                close,
                rsi14,
                ema7,
                ma20,
                trend_state
            FROM btc_usdt
            WHERE timeframe = '5m'
                AND time >= '2025-11-04 00:00:00+00'
                AND time <= '2025-11-12 23:59:59+00'
            ORDER BY time
            LIMIT 10
        """)
        result = await session.execute(query_sample)
        rows = result.fetchall()

        print(f"📋 4. 샘플 데이터 (첫 10개 캔들)")
        print(f"   {'시간':<20} {'Close':<12} {'RSI14':<8} {'EMA7':<12} {'MA20':<12} {'Trend'}")
        print(f"   {'-'*80}")

        for row in rows:
            rsi_str = f"{row.rsi14:.2f}" if row.rsi14 is not None else "NULL"
            ema_str = f"{row.ema7:.2f}" if row.ema7 is not None else "NULL"
            ma_str = f"{row.ma20:.2f}" if row.ma20 is not None else "NULL"
            trend_str = str(row.trend_state) if row.trend_state is not None else "NULL"

            print(f"   {row.time} {row.close:>10.2f}  {rsi_str:<8} {ema_str:<12} {ma_str:<12} {trend_str}")

        print()

        # 5. 진입 조건 충족 캔들 확인 (RSI oversold/overbought + trend 있는 캔들)
        query_entry_conditions = text("""
            SELECT
                time,
                close,
                rsi14,
                ema7,
                ma20,
                trend_state
            FROM btc_usdt
            WHERE timeframe = '5m'
                AND time >= '2025-11-04 00:00:00+00'
                AND time <= '2025-11-12 23:59:59+00'
                AND rsi14 IS NOT NULL
                AND trend_state IS NOT NULL
                AND (rsi14 <= 30 OR rsi14 >= 70)
            ORDER BY time
            LIMIT 20
        """)
        result = await session.execute(query_entry_conditions)
        rows = result.fetchall()

        print(f"🎯 5. 진입 조건 충족 캔들 (RSI ≤30 or ≥70)")
        if rows:
            print(f"   {'시간':<20} {'Close':<12} {'RSI14':<8} {'EMA7':<12} {'MA20':<12} {'Trend'}")
            print(f"   {'-'*80}")

            for row in rows:
                rsi_str = f"{row.rsi14:.2f}" if row.rsi14 is not None else "NULL"
                ema_str = f"{row.ema7:.2f}" if row.ema7 is not None else "NULL"
                ma_str = f"{row.ma20:.2f}" if row.ma20 is not None else "NULL"
                trend_str = str(row.trend_state) if row.trend_state is not None else "NULL"

                print(f"   {row.time} {row.close:>10.2f}  {rsi_str:<8} {ema_str:<12} {ma_str:<12} {trend_str}")
        else:
            print(f"   ⚠️ 진입 조건을 충족하는 캔들이 없습니다!")
            print(f"   → 이 기간 동안 RSI가 30 이하나 70 이상인 캔들이 없었음")

        print()

        # 6. 시간대별 데이터 갭 확인
        query_hourly = text("""
            SELECT
                DATE_TRUNC('hour', time) as hour,
                COUNT(*) as count
            FROM btc_usdt
            WHERE timeframe = '5m'
                AND time >= '2025-11-04 00:00:00+00'
                AND time <= '2025-11-05 23:59:59+00'
            GROUP BY DATE_TRUNC('hour', time)
            ORDER BY hour
            LIMIT 48
        """)
        result = await session.execute(query_hourly)
        rows = result.fetchall()

        print(f"⏰ 6. 시간대별 데이터 (11월 4-5일)")
        missing_hours = []
        for row in rows:
            expected_per_hour = 12  # 5m candles per hour
            if row.count < expected_per_hour:
                missing_hours.append(f"{row.hour} ({row.count}/12)")

        if missing_hours:
            print(f"   ⚠️ 데이터 부족한 시간대:")
            for hour in missing_hours[:10]:  # 처음 10개만
                print(f"      - {hour}")
        else:
            print(f"   ✅ 모든 시간대에 충분한 데이터 존재")

        print()
        print("=" * 80)

    await engine.dispose()


async def main():
    try:
        await analyze_data_gap()
    except Exception as e:
        print(f"❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
