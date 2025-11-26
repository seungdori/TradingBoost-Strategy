#!/usr/bin/env python3
"""
11월 13일 이후 진입 시그널이 없었던 이유 분석
"""

import asyncio
from datetime import datetime, timezone
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

DB_URL = "postgresql+asyncpg://tradeuser:SecurePassword123@158.247.218.188:5432/candlesdb"


async def analyze_no_signal_period():
    """11월 13일 09:20 이후 데이터 분석"""

    engine = create_async_engine(DB_URL, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        print("=" * 80)
        print("📊 진입 시그널 없는 기간 분석: 2025-11-13 09:20 ~ 2025-11-25")
        print("=" * 80)
        print()

        # 1. 전체 통계
        query_stats = text("""
            SELECT
                COUNT(*) as total_candles,
                MIN(close) as min_price,
                MAX(close) as max_price,
                AVG(close) as avg_price,
                STDDEV(close) as price_stddev,
                MIN(rsi14) as min_rsi,
                MAX(rsi14) as max_rsi,
                AVG(rsi14) as avg_rsi,
                COUNT(*) FILTER (WHERE rsi14 <= 30) as rsi_oversold_count,
                COUNT(*) FILTER (WHERE rsi14 >= 70) as rsi_overbought_count,
                COUNT(*) FILTER (WHERE trend_state = 1) as uptrend_count,
                COUNT(*) FILTER (WHERE trend_state = -1) as downtrend_count,
                COUNT(*) FILTER (WHERE trend_state = 0) as neutral_count
            FROM btc_usdt
            WHERE timeframe = '5m'
                AND time > '2025-11-13 09:20:00+00'
                AND time <= '2025-11-25 23:59:59+00'
        """)
        result = await session.execute(query_stats)
        stats = result.fetchone()

        print("📈 1. 전체 통계 (11/13 09:20 이후)")
        print(f"   총 캔들 수: {stats.total_candles:,}개")
        print(f"   가격 범위: ${stats.min_price:,.2f} ~ ${stats.max_price:,.2f}")
        print(f"   평균 가격: ${stats.avg_price:,.2f}")
        print(f"   가격 변동성: ${stats.price_stddev:,.2f}")
        print(f"   가격 변동폭: {((stats.max_price - stats.min_price) / stats.min_price * 100):.2f}%")
        print()
        print(f"   RSI 범위: {stats.min_rsi:.2f} ~ {stats.max_rsi:.2f}")
        print(f"   평균 RSI: {stats.avg_rsi:.2f}")
        print(f"   RSI ≤ 30 (oversold): {stats.rsi_oversold_count}개 ({stats.rsi_oversold_count/stats.total_candles*100:.1f}%)")
        print(f"   RSI ≥ 70 (overbought): {stats.rsi_overbought_count}개 ({stats.rsi_overbought_count/stats.total_candles*100:.1f}%)")
        print()
        print(f"   트렌드 분포:")
        print(f"      상승 (1): {stats.uptrend_count}개 ({stats.uptrend_count/stats.total_candles*100:.1f}%)")
        print(f"      중립 (0): {stats.neutral_count}개 ({stats.neutral_count/stats.total_candles*100:.1f}%)")
        print(f"      하락 (-1): {stats.downtrend_count}개 ({stats.downtrend_count/stats.total_candles*100:.1f}%)")
        print()

        # 2. RSI 극값 분석
        query_rsi_extremes = text("""
            SELECT
                time,
                close,
                rsi14,
                ema7,
                ma20,
                trend_state
            FROM btc_usdt
            WHERE timeframe = '5m'
                AND time > '2025-11-13 09:20:00+00'
                AND time <= '2025-11-25 23:59:59+00'
                AND (rsi14 <= 35 OR rsi14 >= 65)
            ORDER BY time
            LIMIT 30
        """)
        result = await session.execute(query_rsi_extremes)
        rsi_extremes = result.fetchall()

        print(f"🔍 2. RSI 극값 캔들 (RSI ≤35 or ≥65)")
        if rsi_extremes:
            print(f"   {'시간':<20} {'Close':<12} {'RSI14':<8} {'EMA7':<12} {'MA20':<12} {'Trend'}")
            print(f"   {'-'*80}")
            for row in rsi_extremes:
                trend_str = {1: "상승", 0: "중립", -1: "하락"}.get(row.trend_state, "N/A")
                print(f"   {row.time} {row.close:>10.2f}  {row.rsi14:>6.2f}  {row.ema7:>10.2f}  {row.ma20:>10.2f}  {trend_str}")
        else:
            print(f"   ⚠️ RSI가 35~65 범위를 벗어난 캔들이 없습니다!")
        print()

        # 3. 날짜별 RSI 분포
        query_daily_rsi = text("""
            SELECT
                DATE(time) as date,
                COUNT(*) as candle_count,
                MIN(rsi14) as min_rsi,
                MAX(rsi14) as max_rsi,
                AVG(rsi14) as avg_rsi,
                COUNT(*) FILTER (WHERE rsi14 <= 30) as oversold_count,
                COUNT(*) FILTER (WHERE rsi14 >= 70) as overbought_count,
                MIN(close) as min_price,
                MAX(close) as max_price
            FROM btc_usdt
            WHERE timeframe = '5m'
                AND time > '2025-11-13 09:20:00+00'
                AND time <= '2025-11-25 23:59:59+00'
            GROUP BY DATE(time)
            ORDER BY date
        """)
        result = await session.execute(query_daily_rsi)
        daily_rsi = result.fetchall()

        print(f"📅 3. 날짜별 RSI 분석")
        print(f"   {'날짜':<12} {'캔들':<8} {'RSI 범위':<15} {'평균RSI':<10} {'OS':<6} {'OB':<6} {'가격 변동폭'}")
        print(f"   {'-'*85}")
        for row in daily_rsi:
            rsi_range = f"{row.min_rsi:.1f}~{row.max_rsi:.1f}"
            price_change = (row.max_price - row.min_price) / row.min_price * 100
            print(f"   {row.date} {row.candle_count:>6}개  {rsi_range:<15} {row.avg_rsi:>8.2f}  {row.oversold_count:>4}개 {row.overbought_count:>4}개  {price_change:>5.2f}%")
        print()

        # 4. 진입 조건 near-miss 분석 (RSI가 30~35 또는 65~70 범위)
        query_near_miss = text("""
            SELECT
                time,
                close,
                rsi14,
                trend_state,
                CASE
                    WHEN rsi14 <= 35 THEN 'LONG 후보'
                    WHEN rsi14 >= 65 THEN 'SHORT 후보'
                END as signal_type
            FROM btc_usdt
            WHERE timeframe = '5m'
                AND time > '2025-11-13 09:20:00+00'
                AND time <= '2025-11-25 23:59:59+00'
                AND ((rsi14 > 30 AND rsi14 <= 35) OR (rsi14 >= 65 AND rsi14 < 70))
            ORDER BY time
            LIMIT 20
        """)
        result = await session.execute(query_near_miss)
        near_misses = result.fetchall()

        print(f"🎯 4. 진입 조건 Near-Miss 분석 (RSI가 거의 진입 조건에 근접)")
        if near_misses:
            print(f"   {'시간':<20} {'Close':<12} {'RSI14':<8} {'Trend':<8} {'신호 타입'}")
            print(f"   {'-'*70}")
            for row in near_misses:
                trend_str = {1: "상승", 0: "중립", -1: "하락"}.get(row.trend_state, "N/A")
                print(f"   {row.time} {row.close:>10.2f}  {row.rsi14:>6.2f}  {trend_str:<8} {row.signal_type}")
        else:
            print(f"   ⚠️ RSI가 진입 조건에 근접한 캔들이 없습니다!")
        print()

        # 5. 시간대별 RSI 분포
        query_hourly_rsi = text("""
            SELECT
                EXTRACT(HOUR FROM time) as hour,
                COUNT(*) as candle_count,
                AVG(rsi14) as avg_rsi,
                MIN(rsi14) as min_rsi,
                MAX(rsi14) as max_rsi,
                COUNT(*) FILTER (WHERE rsi14 <= 30) as oversold_count,
                COUNT(*) FILTER (WHERE rsi14 >= 70) as overbought_count
            FROM btc_usdt
            WHERE timeframe = '5m'
                AND time > '2025-11-13 09:20:00+00'
                AND time <= '2025-11-25 23:59:59+00'
            GROUP BY EXTRACT(HOUR FROM time)
            ORDER BY hour
        """)
        result = await session.execute(query_hourly_rsi)
        hourly_rsi = result.fetchall()

        print(f"⏰ 5. 시간대별 RSI 분포 (가장 극단적인 시간대)")
        print(f"   {'시간':<6} {'캔들':<8} {'평균RSI':<10} {'RSI 범위':<15} {'OS':<6} {'OB'}")
        print(f"   {'-'*60}")

        # 극단적인 RSI를 가진 시간대만 출력
        extreme_hours = [h for h in hourly_rsi if h.min_rsi <= 35 or h.max_rsi >= 65]
        if extreme_hours:
            for row in extreme_hours:
                rsi_range = f"{row.min_rsi:.1f}~{row.max_rsi:.1f}"
                print(f"   {int(row.hour):>02d}:00  {row.candle_count:>6}개  {row.avg_rsi:>8.2f}  {rsi_range:<15} {row.oversold_count:>4}개 {row.overbought_count:>4}개")
        else:
            print(f"   ⚠️ 모든 시간대에서 RSI가 35~65 범위 내에 있습니다!")
        print()

        # 6. 결론
        print("=" * 80)
        print("💡 분석 결론")
        print("=" * 80)

        if stats.rsi_oversold_count == 0 and stats.rsi_overbought_count == 0:
            print("✅ RSI 조건 미충족:")
            print(f"   - RSI가 한 번도 30 이하로 내려가지 않음 (최저: {stats.min_rsi:.2f})")
            print(f"   - RSI가 한 번도 70 이상으로 올라가지 않음 (최고: {stats.max_rsi:.2f})")
            print(f"   - 평균 RSI: {stats.avg_rsi:.2f} (중립 범위)")
            print()
            print("📊 시장 상황:")
            print(f"   - 가격 변동폭: {((stats.max_price - stats.min_price) / stats.min_price * 100):.2f}%")
            if ((stats.max_price - stats.min_price) / stats.min_price * 100) < 5:
                print("   → 횡보장 (낮은 변동성)")
            else:
                print("   → 적당한 변동성이지만 RSI 극값 없음")

        print()

    await engine.dispose()


async def main():
    try:
        await analyze_no_signal_period()
    except Exception as e:
        print(f"❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
